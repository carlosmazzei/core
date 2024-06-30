"""Platform for Scenario Covers."""

from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ScenarioUpdatableEntity
from .const import CONTROLLER_ENTRY, COVERS_ENTRY, DOMAIN, IFSEI_ATTR_AVAILABLE
from .ifsei.ifsei import IFSEI
from .ifsei.manager import Cover


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Scenario lights from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    covers = entry_data[COVERS_ENTRY]
    ifsei = entry_data[CONTROLLER_ENTRY]

    async_add_entities(ScenarioCover(cover, ifsei) for cover in covers)


class ScenarioCover(ScenarioUpdatableEntity, CoverEntity):
    """Scenario Cover Entity."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )
    _attr_device_class = CoverDeviceClass.SHADE

    def __init__(self, cover: Cover, ifsei: IFSEI) -> None:
        """Initialize a scenario light."""
        super().__init__(cover, ifsei)
        self.up = cover.up
        self.stop = cover.stop
        self.down = cover.down
        self._attr_is_closed = True

    @property
    def is_closed(self) -> bool | None:
        """Return true if cover is closed."""
        return self._attr_is_closed

    async def async_added_to_hass(self):
        """Register callbacks."""
        self._device.add_subscriber(self.async_update_callback)

    async def async_open_cover(self, **kwargs):
        """Open the cover."""
        await self._ifsei.device_manager.async_update_cover_state(
            self.unique_id, self.up
        )

    async def async_close_cover(self, **kwargs):
        """Close the cover."""
        await self._ifsei.device_manager.async_update_cover_state(
            self.unique_id, self.down
        )

    async def async_stop_cover(self, **kwargs):
        """Stop the cover."""
        await self._ifsei.device_manager.async_update_cover_state(
            self.unique_id, self.stop
        )

    async def async_will_remove_from_hass(self):
        """Remove callbacks."""
        self._device.remove_subscriber()

    def async_update_callback(self, **kwargs: Any):
        """Update callback."""
        available = kwargs.pop(IFSEI_ATTR_AVAILABLE, None)
        command = kwargs.pop("command", None)

        if available is not None:
            self._attr_available = available

        if command is not None:
            if command == "down":
                self._attr_is_closed = True
            elif command == "up":
                self._attr_is_closed = False

        self.async_write_ha_state()
