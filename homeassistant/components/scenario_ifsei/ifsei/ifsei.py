"""IFSEI Module."""

import asyncio
from asyncio import Queue, Task
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import json
import logging
import os
import socket

import telnetlib3
from telnetlib3 import TelnetClient, TelnetReader, TelnetWriter

from .manager import DeviceManager

logger = logging.getLogger(__name__)


class Protocol(Enum):
    """An enum that represents the supported protocols."""

    TCP = 1
    UDP = 2


RESPONSE_TERMINATOR = ">"
BUFFER_SIZE = 1024
RETRY_DELAY = 5  # Delay in seconds before retrying connection
IFSEI_ATTR_SEND_DELAY = 0.1  # Delay in seconds between messages
DEVICE_FILE = "device_config.yaml"

ERROR_CODES = {
    "E1": "Buffer overflow on input. Too many characters were sent without sending the <CR> character.",
    "E2": "Buffer overflow on output. Too much traffic on the Classic-NET and the IFSEI is unable to transmit the commands to the controller.",
    "E3": "Non-existent module addressed.",
    "E4": "Syntax error. The controller sent a command that was not recognized by the IFSEI.",
}


@dataclass
class NetworkConfiguration:
    """A class that represents the default network configuration."""

    host: str = "192.168.1.20"
    tcp_port: int = 23
    udp_port: int = 25200
    protocol: Protocol = Protocol.TCP


@dataclass
class QueueManager:
    """A class that manages queues."""

    send_queue: Queue = Queue()
    receive_queue: Queue = Queue()


@dataclass
class TaskManager:
    """A class that manages tasks."""

    send_task: Task | None = None
    receive_task: Task | None = None


class IFSEI:
    """A class that represents an IFSEI device."""

    def __init__(self, network_config: NetworkConfiguration | None = None) -> None:
        """Initialize ifsei device."""
        if network_config is None:
            self.network_config = NetworkConfiguration()
        else:
            self.network_config = network_config
        self.name = "Scenario IFSEI"
        self.connection: tuple[TelnetReader, TelnetWriter] | None = None
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.queue_manager = QueueManager()
        self.process_task: Task | None = None
        self.device_manager: DeviceManager | None = None
        self.is_connected: bool = False
        self.is_closing: bool = False
        self._reconnect_task: Task | None = None
        self._telnetclient: TelnetClient | None = None

    @classmethod
    def from_config(cls, config_file):
        """Create an IFSEI object from a configuration file."""
        config = cls._load_config(config_file)
        network_config = NetworkConfiguration(
            config.get("host"),
            config.get("tcp_port"),
            config.get("udp_port"),
            Protocol[config.get("protocol", "TCP").upper()],
        )
        return cls(network_config=network_config)

    @staticmethod
    def _load_config(config_file):
        """Load config file and return it."""
        logger.info("Reading from log file: %s", config_file)
        with open(config_file, encoding="utf-8") as file:
            return json.load(file)

    def load_devices(self):
        """Load device manager from config file."""
        current_module_path = __file__
        absolute_module_path = os.path.abspath(current_module_path)
        current_directory = os.path.dirname(absolute_module_path)
        target_file_name = DEVICE_FILE
        target_file_path = os.path.join(current_directory, target_file_name)

        self.device_manager = DeviceManager.from_config(target_file_path, self)
        self.is_connected = False

    async def async_connect(self) -> bool:
        """Connect to the IFSEI device."""

        try:
            logger.info(
                "Trying to connect to %s:%s",
                self.network_config.host,
                self.network_config.tcp_port,
            )

            # if self.connection is not None:
            #     logger.info("Ifsei already connected")
            #     return True

            reader, writer = await telnetlib3.open_connection(
                self.network_config.host,
                self.network_config.tcp_port,
                client_factory=self._create_client,
            )
        except (ConnectionRefusedError, TimeoutError) as e:
            logger.error(
                "Failed to connect to %s:%s: %s.",
                self.network_config.host,
                self.network_config.tcp_port,
                e,
            )
            raise
        else:
            self.connection = (reader, writer)
            self.process_task = asyncio.create_task(self._async_process_responses())
            return True

    async def async_close(self):
        """Close client connection."""
        self.is_closing = True
        await self._telnetclient.async_close()

    def _create_client(self, **kwds):
        """Create a telnet client using the factory."""
        self._telnetclient = telnetclient = _IFSEITelnetClient(
            self, self.queue_manager, self.on_connection_lost, **kwds
        )
        return telnetclient

    def on_connection_lost(self):
        """Lost connection callback."""
        logger.info("Lost connection to ifsei")
        if self.is_closing:
            logger.info("Closing, do not start reconnect thread")
            return

        if self._reconnect_task is None:
            self.connection = None
            self._reconnect_task = asyncio.create_task(self._async_reconnect())

        self.set_is_connected(False)

    async def _async_reconnect(self):
        """Reconnect when connection is lost."""

        logger.info("Start reconnect loop")
        while True:
            try:
                await self.async_connect()
            except (TimeoutError, ConnectionResetError, ConnectionError):
                logger.error("Reconnection attempt failed. Waiting for 10s")
                await asyncio.sleep(10)
            else:
                logger.info("Connection reestablished to ifsei")
                self._reconnect_task = None
                break

    async def async_send_command(self, command):
        """Send a command to the send queue."""
        await self.queue_manager.send_queue.put(command)

    async def _async_process_responses(self):
        """Process responses from the IFSEI device."""
        try:
            logger.info("Starting response processing loop")
            while True:
                response = await self.queue_manager.receive_queue.get()
                await self._async_handle_response(response)
        except asyncio.CancelledError:
            logger.info("Process responses task cancelled")
        except Exception as e:
            logger.error("Error processing responses: %s", e)
            raise

    async def _async_handle_response(self, response):
        """Handle a response from the IFSEI device."""

        logger.info("Received response: %s", response)

        if response == "*IFSEION":
            self.set_is_connected(True)

        elif response.startswith("*Z"):
            await self._async_handle_zone_response(response)

        elif response.startswith("*C"):
            await self._async_handle_scene_response(response)

        if response.startswith("E"):
            await self._async_handle_error(response)

    async def _async_handle_zone_response(self, response):
        """Handle a zone response from the IFSEI device."""
        # Dimmer Status: *Z{module_number:2}{channel:2}L{level:3}
        module_number = int(response[2:4])
        channel = int(response[4:6])
        intensity = int(response[7:10])
        logger.info(
            "Zone %s state: %s intensity: %s", module_number, channel, intensity
        )
        await self.device_manager.async_handle_light_state_change(
            module_number, channel, intensity
        )

    async def _async_handle_scene_response(self, response):
        """Handle a scene response from the IFSEI device."""
        # Scene status: *C{address:4}1
        address = str(response[2:6])
        logger.info("Scene address %s", address)
        await self.device_manager.async_handle_scene_state_change(address)

    async def _async_handle_error(self, response):
        """Handle an error response from the IFSEI device."""
        error_code = response.strip().split(" ")[0]
        error_message = ERROR_CODES.get(error_code, f"Unknown error code: {error_code}")
        if error_code.startswith("E3"):
            module_address = error_code[2:]
            error_message += f" Module Address: {module_address}"
        logger.error(error_message)

    def set_protocol(self, protocol=Protocol.TCP):
        """Set the protocol to use for communication."""
        self.network_config.protocol = protocol

    def get_device_id(self):
        """Get device unique id."""
        return f"ifsei-scenario-{self.network_config.host}"

    def set_is_connected(self, is_available: bool = False):
        """Set connection status."""
        self.is_connected = is_available
        if self.device_manager is not None:
            self.device_manager.notify_subscriber(available=is_available)

    # Commands for control/configuration
    async def async_get_version(self):
        """Get the IFSEI version."""
        return await self.async_send_command("$VER")

    async def async_get_ip(self):
        """Get the IP address."""
        return await self.async_send_command("$IP")

    async def async_get_gateway(self):
        """Get the gateway."""
        return await self.async_send_command("$GATEWAY")

    async def async_get_netmask(self):
        """Get the netmask."""
        return await self.async_send_command("$NETMASK")

    async def async_get_tcp_port(self):
        """Get the TCP port."""
        return await self.async_send_command("$PORT TCP")

    async def async_get_udp_port(self):
        """Get UDP port."""
        return await self.async_send_command("$PORT UDP")

    async def async_monitor(self, level: int):
        """Monitor the network."""
        if level < 1 or level > 7:
            raise ValueError("Monitor level must be between 1 and 6")
        return await self.async_send_command(f"$MON{level}")

    # Commands for the Scenario Classic-NET network
    async def async_change_scene(self, module_address, scene_number):
        """Change the scene."""
        return await self.async_send_command(f"$D{module_address:02}C{scene_number:02}")

    async def async_toggle_zone(self, module_address, zone_number, state):
        """Toggle the zone."""
        return await self.async_send_command(
            f"$D{module_address:02}Z{zone_number}{state}"
        )

    async def async_multiple_zones_command(self, module_address, commands, time):
        """Send multiple zones command."""
        command_string = "".join(
            [f"Z{zone}{intensity:02}" for zone, intensity in commands]
        )
        return await self.async_send_command(
            f"$D{module_address:02}{command_string}T{time}"
        )

    async def async_get_scene_status(self, module_address):
        """Get scene status."""
        return await self.async_send_command(f"$D{module_address:02}ST")

    async def async_set_zone_intensity(self, module_address, channel, intensity):
        """Set zone intensity."""
        return await self.async_send_command(
            f"Z{module_address:02}{channel:01}L{intensity:03}T1"
        )

    async def async_set_shader_state(self, module_address: str):
        """Set shader state."""
        return await self.async_send_command(f"C{module_address:04}1")

    async def async_get_zone_intensity(self, module_address, zone_number):
        """Get zone intensity."""
        return await self.async_send_command(f"$D{module_address:02}Z{zone_number}I")

    async def async_increase_scene_intensity(self, module_address):
        """Increase scene intensity."""
        return await self.async_send_command(f"$D{module_address:02}C+")

    async def async_decrease_scene_intensity(self, module_address):
        """Decrease scene intensity."""
        return await self.async_send_command(f"$D{module_address:02}C-")

    async def async_increase_zone_intensity(self, module_address, zone_number):
        """Increase zone intensity."""
        return await self.send_command(f"$D{module_address:02}Z{zone_number}+")

    async def async_decrease_zone_intensity(self, module_address, zone_number):
        """Decrease zone intensity."""
        return await self.send_command(f"$D{module_address:02}Z{zone_number}-")

    # async def async_record_scene(self, module_address):
    #     """Record scene."""
    #     return await self.send_command(f"$D{module_address:02}GRAVA")

    async def async_get_module_configuration(self, module_address, setup_number):
        """Get module configuration."""
        return await self.async_send_command(f"$D{module_address:02}P{setup_number}ST")

    async def async_execute_macro_key_press(self, prid, key_number):
        """Execute macro key press."""
        return await self.async_send_command(f"I{prid}{key_number}P")

    async def async_execute_macro_key_release(self, prid, key_number):
        """Execute macro key release."""
        return await self.async_send_command(f"I{prid}{key_number}R")


class _IFSEITelnetClient(TelnetClient):
    """Protocol to have the base client."""

    def __init__(
        self,
        connection: IFSEI,
        queue_manager: QueueManager,
        on_connection_lost_callback: Callable[[], None] | None,
        *args,
        **kwds,
    ) -> None:
        """Initialize protocol to handle connection errors."""
        super().__init__(*args, **kwds)
        self.connection = connection
        self.task_manager = TaskManager()
        self.queue_manager = queue_manager
        self.shell = self._async_run_shell
        self.on_connection_lost_callback: Callable[[], None] | None = (
            on_connection_lost_callback
        )

    async def _async_run_shell(self, reader, writer):
        await self._async_start_tasks()

    async def _async_start_tasks(self):
        """Start tasks."""
        self._stop_tasks()
        logger.info("Starting tasks.")
        self.task_manager.send_task = asyncio.create_task(self._async_send_data())
        self.task_manager.receive_task = asyncio.create_task(self._async_receive_data())

    def _stop_tasks(self):
        """Stop tasks."""
        try:
            if self.task_manager.send_task is not None:
                self.task_manager.send_task.cancel()
                self.task_manager.send_task = None
                logger.info("Send task cancel requested")
        except asyncio.CancelledError:
            logger.info("Send task already cancelled.")

        try:
            if self.task_manager.receive_task is not None:
                self.task_manager.receive_task.cancel()
                self.task_manager.receive_task = None
                logger.info("Receive task cancel requested")
        except asyncio.CancelledError:
            logger.info("Receive task already cancelled.")

    async def _async_send_data(self):
        """Send data to the IFSEI device from the queue."""
        try:
            logger.info("Starting data sending loop")
            while True:
                command = await self.queue_manager.send_queue.get()
                if self.connection.network_config.protocol == Protocol.TCP:
                    await self._async_send_command_tcp(command)
                elif self.connection.network_config.protocol == Protocol.UDP:
                    self._send_command_udp(command)
                await asyncio.sleep(IFSEI_ATTR_SEND_DELAY)
        except asyncio.CancelledError:
            logger.info("Send task cancelled")

    async def _async_send_command_tcp(self, command: str) -> None:
        """Send command using TCP."""
        try:
            self.writer.write(command + "\r")
            await self.writer.drain()
        except ConnectionResetError:
            logger.error("Connection reset")
            raise
        except Exception as e:
            logger.error("Failed to send command %s over TCP: %s", command, e)
            raise
        else:
            logger.info("Command sent (TCP): %s", command)

    def _send_command_udp(self, command):
        """Send command using UDP."""
        try:
            self.connection.udp_socket.sendto(
                (command + "\r").encode(),
                (
                    self.connection.network_config.host,
                    self.connection.network_config.udp_port,
                ),
            )
            logger.info("Command sent (UDP): %s", command)

        except Exception as e:
            logger.error("Failed to send command %s over UDP: %s", command, e)
            raise

    async def _async_receive_data(self):
        """Receive data from the IFSEI device."""
        try:
            logger.info("Starting data receiving loop")
            while True:
                if self.connection is None:
                    await asyncio.sleep(0.1)  # Wait for the reader to be set
                    continue
                response = await self._async_read_until_prompt()
                if response:
                    await self.queue_manager.receive_queue.put(response)
        except Exception as e:
            logger.error("Error receiving data: %s", e)
            raise

    async def _async_read_until_prompt(self):
        """Read data from the IFSEI device until a prompt is received."""
        try:
            response = ""
            while True:
                if self.connection.network_config.protocol == Protocol.TCP:
                    char = await self.reader.read(1)
                elif self.connection.network_config.protocol == Protocol.UDP:
                    char, _ = await self.connection.udp_socket.recvfrom(BUFFER_SIZE)
                response += char
                if response.endswith(RESPONSE_TERMINATOR):
                    break
            return response.strip()[:-2]
        except asyncio.exceptions.CancelledError:
            logger.info("Data receiving loop cancelled")
            raise
        except Exception as e:
            logger.error("Error reading data: %s", e)
            raise

    def connection_lost(self, exc: None | Exception, /) -> None:
        """Call when connection is lost."""
        super().connection_lost(exc)
        self._stop_tasks()
        if self.on_connection_lost_callback is not None:
            self.on_connection_lost_callback()

    async def async_close(self):
        """Disconnect from the IFSEI device."""
        try:
            self._stop_tasks()
            self.writer.close()
            self.reader.close()
            logger.info("Disconnected from ifsei")
        except Exception as e:
            logger.error("Failed to disconnect: %s", e)
            raise
