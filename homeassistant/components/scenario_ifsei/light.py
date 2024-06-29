"""Platform for Scenario Lights."""

import logging
from typing import Any, cast

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ScenarioUpdatableEntity
from .const import (
    CONTROLLER_ENTRY,
    DOMAIN,
    IFSEI_ATTR_AVAILABLE,
    IFSEI_ATTR_BLUE,
    IFSEI_ATTR_BRIGHTNESS,
    IFSEI_ATTR_GREEN,
    IFSEI_ATTR_RED,
    LIGHTS_ENTRY,
)
from .ifsei.ifsei import IFSEI
from .ifsei.manager import Light

_LOGGER = logging.getLogger(__name__)


def to_scenario_level(level):
    """Convert the given Home Assistant light level (0-255) to Scenario (0-100)."""
    return int(round((level * 100) / 255))


def to_hass_level(level):
    """Convert the given Scenario (0-100) light level to Home Assistant (0-255)."""
    return int((level * 255) // 100)


# Function to update an element in the tuple
def update_tuple(tpl, index, value):
    """Update tuple with new value."""
    temp_list = list(tpl)
    temp_list[index] = value
    return tuple(temp_list)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Scenario lights from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    lights = entry_data[LIGHTS_ENTRY]
    ifsei = entry_data[CONTROLLER_ENTRY]

    async_add_entities(ScenarioLight(light, ifsei) for light in lights)


class ScenarioLight(ScenarioUpdatableEntity, LightEntity):
    """Scenario Light Entity."""

    def __init__(self, light: Light, ifsei: IFSEI) -> None:
        """Initialize a scenario light."""
        super().__init__(light, ifsei)

        addresses = light.get_address()

        if not light.get_is_rgb():
            for address in addresses:
                if address["isDimmeable"]:
                    self._attr_color_mode = ColorMode.BRIGHTNESS
                    self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
                else:
                    self._attr_color_mode = ColorMode.ONOFF
                    self._attr_supported_color_modes = {ColorMode.ONOFF}
        else:
            self._attr_color_mode = ColorMode.RGB
            self._attr_supported_color_modes = {ColorMode.RGB}

    @property
    def is_on(self) -> bool:
        """Return whether this light is on or off."""
        if self._attr_is_on is not None:
            return self._attr_is_on
        return False

    @property
    def brightness(self) -> int:
        """Return the brightness of the light."""
        if self._attr_brightness is not None:
            return self._attr_brightness
        return 0

    async def _async_set_brightness(
        self, brightness: int | None, **kwargs: Any
    ) -> None:
        """Set brightness."""
        scaled_colors = [0, 0, 0, 0]

        if brightness is not None:
            brightness = to_scenario_level(brightness)

        rgb = kwargs.get(ATTR_RGB_COLOR, None)

        if rgb is not None:
            colors = list(rgb)
            _LOGGER.debug(f"Current color: {colors}")  # noqa: G004
            scaled_colors[0] = to_scenario_level(colors[0])
            scaled_colors[1] = to_scenario_level(colors[1])
            scaled_colors[2] = to_scenario_level(colors[2])

        scaled_colors[3] = brightness if brightness is not None else 0

        if self._ifsei.device_manager is not None:
            await self._ifsei.device_manager.async_update_light_state(
                self._attr_unique_id, scaled_colors
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""

        brightness = kwargs.pop(ATTR_BRIGHTNESS, None)

        if brightness is None:
            brightness = 255

        await self._async_set_brightness(brightness, **kwargs)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._async_set_brightness(0, **kwargs)

    async def async_added_to_hass(self):
        """Register callbacks."""
        self._device.add_subscriber(self.async_update_callback)

    async def async_will_remove_from_hass(self):
        """Remove callbacks."""
        self._device.remove_subscriber()

    def async_update_callback(self, **kwargs: Any):
        """Update callback."""

        brightness = kwargs.pop(IFSEI_ATTR_BRIGHTNESS, None)
        available = kwargs.pop(IFSEI_ATTR_AVAILABLE, None)
        red = kwargs.pop(IFSEI_ATTR_RED, None)
        green = kwargs.pop(IFSEI_ATTR_GREEN, None)
        blue = kwargs.pop(IFSEI_ATTR_BLUE, None)

        if available is not None:
            self._attr_available = available

        if (
            brightness is not None
            or red is not None
            or red is not None
            or blue is not None
        ) and self._attr_available is True:
            self._attr_is_on = True

        if brightness is not None:
            if brightness == 0:
                self._attr_is_on = False
            else:
                self._attr_brightness = to_hass_level(brightness)

        # Initialize new_colors with the current rgb_color
        new_colors = list(self.rgb_color) if self.rgb_color else [0, 0, 0]

        # Update new_colors based on the provided color values
        if red is not None:
            new_colors[0] = to_hass_level(red)
        if green is not None:
            new_colors[1] = to_hass_level(green)
        if blue is not None:
            new_colors[2] = to_hass_level(blue)

        # Set the updated colors
        self._attr_rgb_color = cast(tuple[int, int, int], new_colors)

        self.async_write_ha_state()
