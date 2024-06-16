"""Platform for Scenario Lights."""

import logging
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ScenarioUpdatableEntity
from .const import CONTROLLER_ENTRY, DOMAIN, LIGHTS_ENTRY
from .ifsei.ifsei import IFSEI
from .ifsei.manager import Light

_LOGGER = logging.getLogger(__name__)


def to_scenario_level(level):
    """Convert the given Home Assistant light level (0-255) to Lutron (0-100)."""
    return int(round((level * 100) / 255))


def to_hass_level(level):
    """Convert the given Lutron (0-100) light level to Home Assistant (0-255)."""
    return int((level * 255) // 100)


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

        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    @property
    def is_on(self) -> bool:
        """Return whether this light is on or off."""
        return self._device.state > 0

    @property
    def brightness(self) -> int:
        """Return the brightness of the light."""
        return to_hass_level(self._device.state)

    async def _async_set_brightness(
        self, brightness: int | None, **kwargs: Any
    ) -> None:
        """Set brightness."""
        if brightness is not None:
            brightness = to_scenario_level(brightness)

        # await self._smartbridge.set_value(
        #     self.device_id, value=brightness, color_value=color_value, **args
        # )
        await self._ifsei.device_manager.update_device_state(
            self._device.get_device_id(), brightness
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        # first check for "white mode" (WarmDim)
        # if (white_color := kwargs.get(ATTR_WHITE)) is not None:
        #     await self._async_set_warm_dim(white_color)
        #     return

        brightness = kwargs.pop(ATTR_BRIGHTNESS, None)

        # if user is pressing on button nothing is set, so set brightness to 255
        if brightness is None:
            brightness = 255

        await self._async_set_brightness(brightness, **kwargs)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._async_set_brightness(0, **kwargs)
