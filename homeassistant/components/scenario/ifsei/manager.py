"""Device Manager."""

from collections.abc import Callable
from typing import Any

import yaml

from .config_schema import device_config_schema


class Device:
    """Device class."""

    def __init__(self) -> None:
        """Device class."""
        self.unique_id: str = ""
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
        self, unique_id: str, name: str, zone: str, is_rgb: bool, address
    ) -> None:
        """Init light class."""

        super().__init__()
        self.unique_id = str(f"{unique_id}_{zone.lower().replace(" ","_")}")
        self.name = name
        self.zone = zone
        self.is_rgb = is_rgb
        self.address = address

    def get_is_rgb(self):
        """Return if the light is RGB."""
        return self.is_rgb


class Cover(Device):
    """Cover class."""

    def __init__(
        self, unique_id: str, name: str, zone: str, up: str, stop: str, down: str
    ) -> None:
        """Init light class."""

        super().__init__()
        self.unique_id = str(f"{unique_id}_{zone.lower().replace(" ","_")}")
        self.name = name
        self.zone = zone
        self.up = up
        self.stop = stop
        self.down = down
        self.is_closed = False


class DeviceManager:
    """Device Manager."""

    def __init__(self, lights, covers, zones, ifsei) -> None:
        """Device Manager."""
        self._lights = lights
        self._covers = covers
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
                    name=light_data["name"],
                    zone=zones[light_data["zone"]],
                    is_rgb=light_data["isRGB"],
                    address=addresses,
                )
                lights.append(light)

            covers = []
            for covers_data in data["shades"]:
                cover = Cover(
                    unique_id=covers_data["id"],
                    name=covers_data["name"],
                    zone=zones[covers_data["zone"]],
                    up=str(covers_data["address1"]),
                    stop=str(covers_data["address2"]),
                    down=str(covers_data["address3"]),
                )
                covers.append(cover)

            return cls(lights, covers, zones, ifsei)
        except FileNotFoundError:
            return None

    def get_devices_by_type(self, device_type: str):
        """Get devices by type."""
        if device_type == "lights":
            return self._lights

        if device_type == "covers":
            return self._covers

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

    async def async_handle_light_state_change(self, module_number, channel, state):
        """Update device intensity."""
        for light in self._lights:
            for address in light.address:
                if address["module"] == module_number and address["channel"] == channel:
                    address["state"] = state
                    address_name = address["name"]

                    if light.callback_ is not None:
                        kwargs = {address_name: state}
                        light.callback_(**kwargs)

    async def async_update_light_state(self, device_id, colors: list):
        """Update light state."""

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

    async def async_handle_scene_state_change(self, change_address: str):
        """Update scene."""
        kwargs = {}
        for cover in self._covers:
            if change_address in [cover.up, cover.down, cover.stop]:
                if change_address == cover.up:
                    kwargs = {"command": "up"}
                elif change_address == cover.down:
                    kwargs = {"command": "down"}
                elif change_address == cover.stop:
                    kwargs = {"command": "stop"}

                if cover.callback_ is not None:
                    cover.callback_(**kwargs)

    async def async_update_cover_state(self, device_id, address: str):
        """Update cover state."""
        for device in self._covers:
            if device.unique_id == device_id:
                await self._ifsei.async_set_shader_state(address)

    def notify_subscriber(self, **kwargs):
        """Notify change."""
        for device in self._lights:
            if device.callback_ is not None:
                device.callback_(**kwargs)

        for device in self._covers:
            if device.callback_ is not None:
                device.callback_(**kwargs)
