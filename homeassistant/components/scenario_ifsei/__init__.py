"""The Scenario IFSEI integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_PROTOCOL,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONTROLLER_ENTRY, COVERS_ENTRY, DOMAIN, LIGHTS_ENTRY, MANUFACTURER
from .ifsei.ifsei import IFSEI, NetworkConfiguration, Protocol
from .ifsei.manager import Device

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 28000
DEFAULT_IP = "192.168.15.22"
YAML_DEVICES = "device_config.yaml"

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

PLATFORMS: list[Platform] = [Platform.COVER, Platform.LIGHT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Scenario IFSEI from a config entry."""

    entry_id = entry.entry_id
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    protocol = Protocol[entry.data[CONF_PROTOCOL].upper()]

    network_configuration = NetworkConfiguration(host, port, port, protocol)
    ifsei = IFSEI(network_config=network_configuration)

    try:
        await hass.async_add_executor_job(ifsei.load_devices)
        if ifsei.device_manager is None:
            return False
    except vol.Invalid as err:
        _LOGGER.error("Configuration error in %s: %s", YAML_DEVICES, str(err))
        return False

    try:
        _LOGGER.debug("Trying to connect to ifsei")
        await ifsei.async_connect()
    except (ConnectionRefusedError, TimeoutError) as e:
        raise ConfigEntryNotReady(  # noqa: B904
            f"Timed out while trying to connect to {host}, error {e}"
        )

    _LOGGER.debug(f"Connected to host: {host}:{port}, protocol: {protocol}")  # noqa: G004

    if not entry.unique_id:
        hass.config_entries.async_update_entry(entry, unique_id=ifsei.get_device_id())

    _async_register_scenario_device(hass, entry_id, ifsei)

    hass.data.setdefault(DOMAIN, {})
    entry_data = hass.data[DOMAIN].setdefault(entry.entry_id, {})
    entry_data[CONTROLLER_ENTRY] = ifsei
    entry_data[LIGHTS_ENTRY] = ifsei.device_manager.get_devices_by_type("light")
    entry_data[COVERS_ENTRY] = ifsei.device_manager.get_devices_by_type("covers")

    async def on_hass_stop(event: Event) -> None:
        """Stop push updates when hass stops."""
        await ifsei.async_close()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, on_hass_stop)
    )
    entry.async_on_unload(ifsei.async_close)

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
        configuration_url="https://scenario.ind.br",
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
        self._attr_name = device.name
        self._attr_unique_id = device.unique_id
        self._device_name = ifsei.name
        self._device_manufacturer = MANUFACTURER
        self._device_id = ifsei.get_device_id()
        info = DeviceInfo(
            identifiers={(DOMAIN, str(device.unique_id))},
            manufacturer=MANUFACTURER,
            name=self._attr_name,
            via_device=(DOMAIN, str(device.unique_id)),
            suggested_area=device.zone,
        )
        self._attr_device_info = info

    @property
    def available(self):
        """Check availability of the device."""
        return self._ifsei.is_connected
