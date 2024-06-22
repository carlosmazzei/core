"""IFSEI Module."""

import asyncio
from asyncio import Queue, Task
from dataclasses import dataclass
from enum import Enum
import json
import logging
import os
import socket

import telnetlib3
from telnetlib3 import TelnetClient, TelnetReader, TelnetWriter

from .manager import DeviceManager

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class Protocol(Enum):
    """An enum that represents the supported protocols."""

    TCP = 1
    UDP = 2


RESPONSE_TERMINATOR = ">"
BUFFER_SIZE = 1024
RETRY_DELAY = 5  # Delay in seconds before retrying connection

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
        self.connection: tuple[TelnetReader, TelnetWriter] | None = None
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.queue_manager = QueueManager()
        self.process_task: Task | None = None
        self.name = "Scenario IFSEI"
        self._telnetclient = None

        # Load device configuration file
        current_module_path = __file__
        absolute_module_path = os.path.abspath(current_module_path)
        current_directory = os.path.dirname(absolute_module_path)
        target_file_name = "device_config.yaml"
        target_file_path = os.path.join(current_directory, target_file_name)

        self.device_manager = DeviceManager.from_config(target_file_path, self)
        self.is_connected = False

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
        logger.info("Reading from log file: %s", config_file)
        with open(config_file, encoding="utf-8") as file:
            return json.load(file)

    async def connect(self) -> bool:
        """Connect to the IFSEI device."""

        try:
            logger.info(
                "Trying to connect to %s:%s",
                self.network_config.host,
                self.network_config.tcp_port,
            )
            reader, writer = await telnetlib3.open_connection(
                self.network_config.host,
                self.network_config.tcp_port,
                client_factory=self._create_client,
            )
        except Exception as e:
            logger.error(
                "Failed to connect to %s:%s: %s.",
                self.network_config.host,
                self.network_config.tcp_port,
                e,
            )
            raise
        else:
            self.connection = (reader, writer)
            self.process_task = asyncio.create_task(self._process_responses())
            return True

    def _create_client(self, **kwds):
        self._telnetclient = telnetclient = _IFSEITelnetClient(
            self, self.queue_manager, **kwds
        )
        return telnetclient

    async def send_command(self, command):
        """Send a command to the send queue."""
        await self.queue_manager.send_queue.put(command)

    async def _process_responses(self):
        """Process responses from the IFSEI device."""
        try:
            logger.info("Starting response processing loop")
            while True:
                response = await self.queue_manager.receive_queue.get()
                self._handle_response(response)
        except asyncio.CancelledError:
            logger.info("Process responses task cancelled")
        except Exception as e:
            logger.error("Error processing responses: %s", e)
            raise

    def _handle_response(self, response):
        """Handle a response from the IFSEI device."""

        logger.info("Received response: %s", response)

        if response == "*IFSEION":
            self.is_connected = True

        elif response.startswith("*Z"):
            self._handle_zone_response(response)

        if response.startswith("E"):
            self._handle_error(response)

    def _handle_zone_response(self, response):
        """Handle a zone response from the IFSEI device."""
        # Dimmer Status: *Z{module_number:2}{channel:2}L{level:3}
        module_number = int(response[2:4])
        channel = int(response[4:6])
        intensity = int(response[7:10])
        logger.info(
            "Zone %s state: %s intensity: %s", module_number, channel, intensity
        )
        self.device_manager.set_device_state(module_number, channel, intensity)

    def _handle_error(self, response):
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
        return "ifsei-scenario"

    # Commands for control/configuration
    async def get_version(self):
        """Get the IFSEI version."""
        return await self.send_command("$VER")

    async def get_ip(self):
        """Get the IP address."""
        return await self.send_command("$IP")

    async def get_gateway(self):
        """Get the gateway."""
        return await self.send_command("$GATEWAY")

    async def get_netmask(self):
        """Get the netmask."""
        return await self.send_command("$NETMASK")

    async def get_tcp_port(self):
        """Get the TCP port."""
        return await self.send_command("$PORT TCP")

    async def get_udp_port(self):
        """Get UDP port."""
        return await self.send_command("$PORT UDP")

    async def monitor(self, level: int):
        """Monitor the network."""
        if level < 1 or level > 7:
            raise ValueError("Monitor level must be between 1 and 6")
        return await self.send_command(f"$MON{level}")

    # Commands for the Scenario Classic-NET network
    async def change_scene(self, module_address, scene_number):
        """Change the scene."""
        return await self.send_command(f"$D{module_address:02}C{scene_number:02}")

    async def toggle_zone(self, module_address, zone_number, state):
        """Toggle the zone."""
        return await self.send_command(f"$D{module_address:02}Z{zone_number}{state}")

    async def multiple_zones_command(self, module_address, commands, time):
        """Send multiple zones command."""
        command_string = "".join(
            [f"Z{zone}{intensity:02}" for zone, intensity in commands]
        )
        return await self.send_command(f"$D{module_address:02}{command_string}T{time}")

    async def get_scene_status(self, module_address):
        """Get scene status."""
        return await self.send_command(f"$D{module_address:02}ST")

    async def set_zone_intensity(self, module_address, channel, intensity):
        """Set zone intensity."""
        return await self.send_command(
            f"Z{module_address:02}{channel:01}L{intensity:03}T1"
        )

    async def get_zone_intensity(self, module_address, zone_number):
        """Get zone intensity."""
        return await self.send_command(f"$D{module_address:02}Z{zone_number}I")

    async def increase_scene_intensity(self, module_address):
        """Increase scene intensity."""
        return await self.send_command(f"$D{module_address:02}C+")

    async def decrease_scene_intensity(self, module_address):
        """Decrease scene intensity."""
        return await self.send_command(f"$D{module_address:02}C-")

    # async def increase_zone_intensity(self, module_address, zone_number):
    #     """Increase zone intensity."""
    #     return await self.send_command(f"$D{module_address:02}Z{zone_number}+")

    # async def decrease_zone_intensity(self, module_address, zone_number):
    #     """Decrease zone intensity."""
    #     return await self.send_command(f"$D{module_address:02}Z{zone_number}-")

    # async def record_scene(self, module_address):
    #     """Record scene."""
    #     return await self.send_command(f"$D{module_address:02}GRAVA")

    async def get_module_configuration(self, module_address, setup_number):
        """Get module configuration."""
        return await self.send_command(f"$D{module_address:02}P{setup_number}ST")

    async def execute_macro_key_press(self, prid, key_number):
        """Execute macro key press."""
        return await self.send_command(f"I{prid}{key_number}P")

    async def execute_macro_key_release(self, prid, key_number):
        """Execute macro key release."""
        return await self.send_command(f"I{prid}{key_number}R")


class _IFSEITelnetClient(TelnetClient):
    """Protocol to have the base client."""

    def __init__(
        self, connection: IFSEI, queue_manager: QueueManager, *args, **kwds
    ) -> None:
        """Initialize protocol to handle connection errors."""
        super().__init__(*args, **kwds)
        self.connection = connection
        self.task_manager = TaskManager()
        self.queue_manager = queue_manager
        self.shell = self._run_shell

    async def _run_shell(self, reader, writer):
        await self._start_tasks()

    async def _start_tasks(self):
        self._stop_tasks()
        logger.info("Starting tasks.")
        self.task_manager.send_task = asyncio.create_task(self._send_data())
        self.task_manager.receive_task = asyncio.create_task(self._receive_data())

    def _stop_tasks(self):
        tasks = [self.task_manager.send_task, self.task_manager.receive_task]
        for task in tasks:
            if task:
                task.cancel()
                logger.info(f"Stopping task: {task.get_name()}")  # noqa: G004
                try:
                    # await task
                    task = None
                except asyncio.CancelledError:
                    logger.info("Task %s successfully cancelled.", task.get_name())

    async def _send_data(self):
        """Send data to the IFSEI device from the queue."""
        try:
            logger.info("Starting data sending loop")
            while True:
                command = await self.queue_manager.send_queue.get()
                if self.connection.network_config.protocol == Protocol.TCP:
                    await self._send_command_tcp(command)
                elif self.connection.network_config.protocol == Protocol.UDP:
                    self._send_command_udp(command)
        except asyncio.CancelledError:
            logger.info("Send task cancelled")

    async def _send_command_tcp(self, command: str) -> None:
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

    async def _receive_data(self):
        """Receive data from the IFSEI device."""
        try:
            logger.info("Starting data receiving loop")
            while True:
                if self.connection is None:
                    await asyncio.sleep(0.1)  # Wait for the reader to be set
                    continue
                response = await self._read_until_prompt()
                if response:
                    await self.queue_manager.receive_queue.put(response)
        except Exception as e:
            logger.error("Error receiving data: %s", e)
            raise

    async def _read_until_prompt(self):
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
        # This is called each time when you connection is lost
        super().connection_lost(exc)
        self._stop_tasks()

    async def close(self):
        """Disconnect from the IFSEI device."""
        try:
            await self._stop_tasks()
            self.writer.close()
            await self.writer.wait_closed()
            logger.info("Disconnected")
        except Exception as e:
            logger.error("Failed to disconnect: %s", e)
            raise
