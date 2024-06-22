"""Device Manager."""

from collections.abc import Callable
from typing import Any

import yaml


class Device:
    """Device class."""

    def __init__(self) -> None:
        """Device class."""
        self._unique_id: int = -1
        self._name: str = ""
        self._zone: int = -1
        self._address: dict[str, Any] = {}
        self.callback_: Callable[[], None] | None = None
        self.state = 0

    def update_state(self, state):
        """Update state."""
        self.state = state

    def get_device_id(self):
        """Return unique id."""
        return self._unique_id

    def get_name(self):
        """Return name."""
        return self._name

    def get_address(self):
        """Return address."""
        return self._address

    def add_subscriber(self, callback_: Callable[[], None]):
        """Set a callback function to be called when a response is received."""
        self.callback_ = callback_


class Light(Device):
    """Light class."""

    def __init__(
        self, unique_id: int, name: str, zone: int, is_rgb: bool, address
    ) -> None:
        """Init light class."""

        super().__init__()
        self._unique_id = unique_id
        self._name = name
        self._zone = zone
        self._is_rgb = is_rgb
        self._address = address

    def get_is_rgb(self):
        """Return if the light is RGB."""
        return self._is_rgb


class DeviceManager:
    """Device Manager."""

    def __init__(self, lights, ifsei) -> None:
        """Device Manager."""
        self._lights = lights
        self._ifsei = ifsei

    @classmethod
    def from_config(cls, config_file, ifsei):
        """Create Device Manager from config file."""
        with open(config_file, encoding="utf-8") as file:
            data = yaml.safe_load(file)

        lights = []
        for light_data in data["lights"]:
            addresses = light_data.get("address", [])
            for address in addresses:
                address["state"] = 0
            light = Light(
                unique_id=light_data["id"],
                name=f"{light_data["name"]} - {light_data["zone"]}",
                zone=light_data["zone"],
                is_rgb=light_data["isRGB"],
                address=addresses,
            )
            lights.append(light)

        return cls(lights, ifsei)

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

    def set_device_state(self, module_number, channel, state):
        """Update device intensity."""
        for light in self._lights:
            if (
                light.get_address()[0]["module"] == module_number
                and light.get_address()[0]["channel"] == channel
            ):
                light.get_address()[0]["state"] = state

                if light.callback_ is not None:
                    light.callback_()

                return

    async def update_device_state(self, device_id, value):
        """Update device state."""
        for device in self._lights:
            if device.get_device_id() == device_id:
                await self._ifsei.set_zone_intensity(
                    device.get_address()[0]["module"],
                    device.get_address()[0]["channel"],
                    value,
                )

                if device.callback_ is not None:
                    device.callback_()

                return
