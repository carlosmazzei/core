"""The Scenario IFSEI integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_PROTOCOL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONTROLLER_ENTRY, DOMAIN, LIGHTS_ENTRY, MANUFACTURER
from .ifsei.ifsei import IFSEI, NetworkConfiguration, Protocol
from .ifsei.manager import Device

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 28000
DEFAULT_IP = "192.168.15.22"

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(
            cv.ensure_list,
            [
                {
                    vol.Required(CONF_HOST): cv.string,
                    vol.Required(CONF_PORT): cv.string,
                    vol.Required(CONF_PROTOCOL): cv.string,
                }
            ],
        )
    },
    extra=vol.ALLOW_EXTRA,
)

PLATFORMS: list[Platform] = [Platform.LIGHT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Scenario IFSEI from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    entry_data = hass.data[DOMAIN].setdefault(entry.entry_id, {})

    entry_id = entry.entry_id
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    protocol = Protocol[entry.data[CONF_PROTOCOL].upper()]

    network_configuration = NetworkConfiguration(host, port, port, protocol)
    ifsei = IFSEI(network_config=network_configuration)

    try:
        _LOGGER.debug("Trying to connect to ifsei")
        await ifsei.connect()
    except (ConnectionRefusedError, TimeoutError) as e:
        raise ConfigEntryNotReady(  # noqa: B904
            f"Timed out while trying to connect to {host}, error {e}"
        )
    except:
        _LOGGER.debug("Problem while connectiing")
        raise

    _LOGGER.debug(f"Connected to host: {host}:{port}, protocol: {protocol}")  # noqa: G004

    if not entry.unique_id:
        hass.config_entries.async_update_entry(entry, unique_id=ifsei.get_device_id())

    _async_register_scenario_device(hass, entry_id, ifsei)

    entry_data[CONTROLLER_ENTRY] = ifsei
    entry_data[LIGHTS_ENTRY] = ifsei.device_manager.get_devices_by_type("light")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


@callback
def _async_register_scenario_device(
    hass: HomeAssistant, config_entry_id: str, ifsei: IFSEI
) -> None:
    """Register the bridge device in the device registry."""
    device_registry = dr.async_get(hass)
    device_args = DeviceInfo(
        name="Scenario IFSEI",
        manufacturer=MANUFACTURER,
        identifiers={(DOMAIN, ifsei.get_device_id())},
        model="IFSEI Classic",
        via_device=(DOMAIN, ifsei.get_device_id()),
        configuration_url="https://scenario.com.br",
    )

    device_registry.async_get_or_create(**device_args, config_entry_id=config_entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


class ScenarioUpdatableEntity(Entity):
    """Base entity for Scenario."""

    _attr_should_poll = False

    def __init__(self, device: Device, ifsei: IFSEI) -> None:
        """Initialize a Scenario entity."""
        self._ifsei = ifsei
        self._device = device
        self._attr_name = device.get_name()
        self._attr_unique_id = str(device.get_device_id())
        self._device_name = ifsei.name
        self._device_manufacturer = MANUFACTURER
        self._device_id = ifsei.get_device_id()
        info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            manufacturer=MANUFACTURER,
            name=self._attr_name,
            via_device=(DOMAIN, str(self._device_id)),
        )
        self._attr_device_info = info

    async def async_added_to_hass(self):
        """Register callbacks."""
        self._device.add_subscriber(self.async_write_ha_state)

    async def async_update(self) -> None:
        """Update when forcing a refresh of the device."""
        self._device = self._ifsei.device_manager.get_device_by_id(
            self._device.get_device_id()
        )
        _LOGGER.debug(self._device)
