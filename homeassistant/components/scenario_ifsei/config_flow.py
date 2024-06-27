"""Config flow for Scenario IFSEI."""

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_PROTOCOL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .const import CONF_CONTROLLER_UNIQUE_ID, DOMAIN
from .ifsei.ifsei import IFSEI, NetworkConfiguration, Protocol

_LOGGER = logging.getLogger(__name__)

PROTOCOLS = [
    selector.SelectOptionDict(value="TCP", label="TCP"),
    selector.SelectOptionDict(value="UDP", label="UDP"),
]

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT): str,
        vol.Required(CONF_PROTOCOL): selector.SelectSelector(
            selector.SelectSelectorConfig(options=PROTOCOLS),
        ),
    }
)


class ScenarioValidator:
    """Validate Scenario config entries."""

    def __init__(self, host, port, protocol, hass: HomeAssistant) -> None:
        """Initialize configuration."""
        self._host = host
        self._port = port
        self._protocol = protocol
        self.hass = hass
        self.ifsei = IFSEI(
            network_config=NetworkConfiguration(
                host, port, port, protocol=Protocol[protocol.upper()]
            )
        )

    async def connect_to_ifsei(self) -> bool:
        """Connect to IFSEI interface."""
        try:
            await self.ifsei.async_connect()
        except (
            TimeoutError,
            ConnectionRefusedError,
            ConnectionAbortedError,
            ConnectionError,
        ) as e:
            _LOGGER.debug(f"Failed to connect to controller, error: {e}")  # noqa: G004
            return False
        else:
            _LOGGER.debug("Connected")
            return True


class ScenarioConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Scenario."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""

        errors = {}
        if user_input is not None:
            scenario = ScenarioValidator(
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                user_input[CONF_PROTOCOL],
                self.hass,
            )
            _LOGGER.debug(
                f"User input, host:{user_input[CONF_HOST]}, port: {user_input[CONF_PORT]}, protocol:{user_input[CONF_PROTOCOL]}"  # noqa: G004
            )
            try:
                if not await scenario.connect_to_ifsei():
                    raise CannotConnect
            except CannotConnect:
                errors["base"] = "cannot_connect"

            if not errors:
                controller_unique_id = scenario.ifsei.get_device_id()
                # mac = (controller_unique_id.split("_", 3))[2]
                # formatted_mac = format_mac(mac)
                # await self.async_set_unique_id(formatted_mac)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=controller_unique_id,
                    data={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: user_input[CONF_PORT],
                        CONF_PROTOCOL: user_input[CONF_PROTOCOL],
                        CONF_CONTROLLER_UNIQUE_ID: controller_unique_id,
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Cannot connect to the device."""
