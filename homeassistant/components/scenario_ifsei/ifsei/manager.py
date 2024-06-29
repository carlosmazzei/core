"""Device Manager."""

from collections.abc import Callable
from typing import Any

import yaml

from .config_schema import device_config_schema


class Device:
    """Device class."""

    def __init__(self) -> None:
        """Device class."""
        self.unique_id: int = -1
        self.name: str = ""
        self.zone: str = ""
        self.address: dict[str, Any] = {}
        self.callback_: Callable[[], None] | None = None
        self.state = 0

    def update_state(self, state):
        """Update state."""
        self.state = state

    def get_device_id(self):
        """Return unique id."""
        return self.unique_id

    def get_name(self):
        """Return name."""
        return self.name

    def get_address(self):
        """Return address."""
        return self.address

    def add_subscriber(self, callback_: Callable[[], None]):
        """Set a callback function to be called when a response is received."""
        self.callback_ = callback_

    def remove_subscriber(self):
        """Remove callback function."""
        self.callback_ = None


class Light(Device):
    """Light class."""

    def __init__(
        self, unique_id: int, name: str, zone: str, is_rgb: bool, address
    ) -> None:
        """Init light class."""

        super().__init__()
        self.unique_id = unique_id
        self.name = name
        self.zone = zone
        self.is_rgb = is_rgb
        self.address = address

    def get_is_rgb(self):
        """Return if the light is RGB."""
        return self.is_rgb


class DeviceManager:
    """Device Manager."""

    def __init__(self, lights, zones, ifsei) -> None:
        """Device Manager."""
        self._lights = lights
        self._zones = zones
        self._ifsei = ifsei

    @classmethod
    def from_config(cls, config_file, ifsei):
        """Create Device Manager from config file."""
        try:
            with open(config_file, encoding="utf-8") as file:
                data = yaml.safe_load(file)

            device_config_schema(data)

            zones_list = data.get("zones", [])
            zones = {zone["id"]: zone["name"] for zone in zones_list}

            lights = []
            for light_data in data["lights"]:
                addresses = light_data.get("address", [])
                for address in addresses:
                    address["state"] = 0
                light = Light(
                    unique_id=light_data["id"],
                    name=f"{light_data["name"]}",
                    zone=zones[light_data["zone"]],
                    is_rgb=light_data["isRGB"],
                    address=addresses,
                )
                lights.append(light)

            return cls(lights, zones, ifsei)
        except FileNotFoundError:
            return None

    def get_devices_by_type(self, device_type: str):
        """Get devices by type."""
        if device_type == "light":
            return self._lights
        return None

    # def get_device_by_name(self, name: str):
    #     """Get device."""
    #     for device in self.devices:
    #         if device.name == name:
    #             return device
    #     return None

    # def get_device_by_module_number_and_channel(self, module_number: int, channel: int):
    #     """Get device by module number and channel."""
    #     for device in self.devices:
    #         if device.module_number == module_number and device.channel == channel:
    #             return device
    #     return None

    def get_device_by_id(self, id):
        """Get device by id."""
        for device in self._lights:
            if device.unique_id == id:
                return device

    async def async_handle_state_change(self, module_number, channel, state):
        """Update device intensity."""
        for light in self._lights:
            for address in light.address:
                if address["module"] == module_number and address["channel"] == channel:
                    address["state"] = state
                    address_name = address["name"]

                    if light.callback_ is not None:
                        kwargs = {address_name: state}
                        light.callback_(**kwargs)

    async def async_update_device_state(self, device_id, colors: list):
        """Update device state."""

        if len(colors) != 4:
            raise ValueError("List must have exactly 4 elements")

        for device in self._lights:
            if device.unique_id == device_id:
                # Propagate changes to every address
                for address in device.address:
                    value = 0
                    if address["name"] == "r":
                        value = colors[0]
                    elif address["name"] == "g":
                        value = colors[1]
                    elif address["name"] == "b":
                        value = colors[2]
                    elif address["name"] == "w":
                        value = colors[3]

                    await self._ifsei.async_set_zone_intensity(
                        address["module"],
                        address["channel"],
                        value,
                    )

                return

    def notify_subscriber(self, **kwargs):
        """Notify change."""
        for device in self._lights:
            if device.callback_ is not None:
                device.callback_(**kwargs)
