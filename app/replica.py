import asyncio
import logging

from app.serialiser import RedisEncoder, RedisDecoder
from app.exceptions import RedisException

logger = logging.getLogger(__name__)


class Replica:

    def __init__(self, master_host, master_port, self_port, handler):
        self.master_host = master_host
        self.master_port = int(master_port)
        self.port = int(self_port)
        self.encoder = RedisEncoder()
        self.decoder = RedisDecoder()
        self.reader = None
        self.writer = None
        self.handler = handler

    async def connect_to_master(self):
        """
        Establish a persistent connection to the master.

        Raises:
            RedisException: If connection fails
        """
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.master_host, self.master_port
            )
        except Exception as e:
            raise RedisException(f"Connection failed: {e}") from e

    async def process_command(self, data):
        """
        Process a command received from the master.

        Args:
            command (str): The command received from the master.

        Returns:
            str: The response to the command.

        Raises:
            RedisException: If the command is invalid or fails to process.
        """

        try:
            decoded_data = data.decode("utf-8")
        except UnicodeDecodeError:
            commands = self.complex_decode(data)
            if commands:
                return await self.process_command(commands)
            logger.warning("Unable to decode data: %s", data)
            return

        # Process the command
        response = await self.handler.handle(decoded_data, propogated_command=True, writer=self.writer)

        # Send response back if needed
        if response:
            if isinstance(response, str):
                response = response.encode("utf-8")

            try:
                self.writer.write(response)
                await self.writer.drain()
            except Exception as send_error:
                logger.error(f"Error sending response: {send_error}")

    async def listen_for_commands(self):
        """
        Continuously listen for commands sent by the master and
        process them using RedisCommandHandler.
        """

        if not self.reader or not self.writer:
            raise RedisException("Not connected to master")

        logger.info("Starting to listen for commands from master")

        while True:
            data = await self.reader.read(1024)

            if not data:
                logger.warning("Connection closed by master")
                raise RedisException("Connection closed by master")

            await self.process_command(data)

    async def send_to_master(self, message):
        """
        Send data to a TCP socket.

        Args:
            message (str/bytes): Data to be sent
        """

        self.writer.write(message.encode('utf-8'))
        await self.writer.drain()

        response = await self.reader.read(1024)
        if not response:
            raise RedisException("No response received from master")

        try:
            return response.decode('utf-8')
        except UnicodeDecodeError:
            commands = self.complex_decode(response)
            if commands:
                await self.process_command(commands)
            return response

    async def handshake(self):
        """
        Handshake process with master

        There are three parts to this handshake:

            The replica sends a PING to the master
            The replica sends REPLCONF twice to the master
            The replica sends PSYNC to the master
        """

        await self.connect_to_master()
        await self.ping()
        await self.replconf()
        await self.psync()

    async def ping(self):
        response = await self.send_to_master(self.encoder.encode_array(["PING"]))
        if self.decoder.decode(response) != "PONG":
            logger.warning("Failed to receive PONG")

    async def replconf(self):
        """
        Send REPLCONF commands to configure replication.

        1. Notify master of listening port
        2. Declare replication capabilities
        """
        # Send listening port configuration
        resp = await self.send_to_master(
            self.encoder.encode_array(["REPLCONF", "listening-port", str(self.port)])
        )
        if self.decoder.decode(resp)!= "OK":
            logger.warning("Failed to set listening port")

        # Send capabilities
        resp = await self.send_to_master(
            self.encoder.encode_array(["REPLCONF", "capa", "psync2"])
        )
        if self.decoder.decode(resp)!= "OK":
            logger.warning("Failed to set replication capabilities")

    async def psync(self):
        """
        Initiate replication to master

        The PSYNC command is used to synchronize the state of the replica with the master.
        The replica will send this command to the master with two arguments:

        The first argument is the replication ID of the master
            Since this is the first time the replica is connecting to the master,
            the replication ID will be ? (a question mark)

        The second argument is the offset of the master
            Since this is the first time the replica is connecting to the master, the offset will be -1
        """
        await self.send_to_master(self.encoder.encode_array(["PSYNC", "?", "-1"]))

    def complex_decode(self, response):
        """
        If the command has RDB file, we need to decode it
        """

        # Find Command till the RDB
        rdb_position = response.find(b"REDIS0011")
        rdb_end_position = response.find(b"\xff") + 8 + 1

        response[:rdb_position].decode('utf-8')
        response[rdb_position: rdb_end_position]    # RDB
        other_commands = response[rdb_end_position:]

        return other_commands
