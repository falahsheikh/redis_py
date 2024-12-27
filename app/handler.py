import asyncio
import base64
from datetime import datetime, timedelta
import fnmatch
import os

from app.connection_registry import ConnectionRegistry
from app.serialiser import RedisEncoder, RedisDecoder, RedisType
from app.exceptions import RedisException
from app.database import Database, RedisDBException, STREAM
from app.utils import gen_random_string


PING = "ping"
ECHO = "echo"
SET = "set"
GET = "get"
INCR = "incr"
XADD = "xadd"
XRANGE = "xrange"
XREAD = "xread"
MULTI = "multi"
EXEC = "exec"
DISCARD = "discard"
CONFIG = "config"
KEYS = "keys"
INFO = "info"
REPLCONF = "replconf"
PSYNC = "psync"
WAIT = "wait"
TYPE = "type"

EMPTY_RDB = "UkVESVMwMDEx+glyZWRpcy12ZXIFNy4yLjD6CnJlZGlzLWJpdHPAQPoFY3RpbWXCbQi8ZfoIdXNlZC1tZW3CsMQQAPoIYW9mLWJhc2XAAP/wbjv+wP9aog=="


class RedisCommandHandler:

    def __init__(self, connection_registry=None):
        self.encoder = RedisEncoder()
        self.db = Database()

        self.replication_id = None
        self.replication_offset = None

        self.connection_registry = connection_registry or ConnectionRegistry()

        self.is_replica = os.getenv("replicaof", False)
        if not self.is_replica:
            self.replication_id = gen_random_string(40)
            self.replication_offset = 0

        self.bytes_processed = 0

        self.transaction_queue = None

    ####### Actual Command Functions ######################

    async def ping(self, command_arr):
        return "PONG", RedisType.SIMPLE_STRING

    async def echo(self, args):
        return args[0], RedisType.BULK_STRING

    async def set(self, args):
        key = args[0]
        value = args[1]

        optional_args = args[2:]
        expires_at = None

        for idx, arg in enumerate(optional_args):
            if arg.lower() == "px":
                expires_at = datetime.now() + timedelta(milliseconds=int(optional_args[idx+1]))
            elif arg.lower() == "ex":
                expires_at = datetime.now() + timedelta(seconds=int(optional_args[idx+1]))

        self.db.set(key, value, expires_at)

        return "OK", RedisType.SIMPLE_STRING

    async def xadd(self, args):
        """
        Implement Redis XADD operation
        """
        stream_key = args[0]
        id = args[1]
        key_value_pairs = args[2:]

        try:
            stream_id = self.db.add_stream(stream_key, id, *key_value_pairs)
        except RedisDBException as exc:
            if exc.module == STREAM and exc.code == "small-top":
                raise RedisException("The ID specified in XADD is equal or smaller than the target stream top item")
            if exc.module == STREAM and exc.code == "small-first":
                raise RedisException("The ID specified in XADD must be greater than 0-0")

        return stream_id, RedisType.BULK_STRING

    async def xrange(self, args):

        stream = args[0]
        start_id = args[1]
        end_id = args[2]

        return self.db.get_range_stream(stream, start_id, end_id), RedisType.ARRAY

    async def xread(self, args):
        """
        Reads multiple streams starting from specified IDs.

        Args:
            args (list): A list containing:
                - "streams" at an arbitrary position.
                - Stream keys and their corresponding start IDs after "streams".
                - Optionally block argument

        Returns:
            Encoded array containing stream keys and their respective data.
        """
        if not isinstance(args, list) or "streams" not in args:
            raise RedisException("Invalid arguments. Expected streams in argument list")

        args = [item.lower() for item in args]

        # Find the index of "streams"
        streams_index = args.index("streams")
        stream_args = args[streams_index + 1:]

        # Find index of "block"
        try:
            block_index = args.index("block")
        except ValueError:
            block_time = None
        else:
            block_time = int(args[block_index + 1]) # In Milliseconds
            if block_time < 0:
                raise RedisException("Block time must be a non-negative integer.")
            # Calculate when the timeout will occur
            start_time = asyncio.get_event_loop().time()
            end_time = start_time + block_time // 1000

            # Block time of zero is infinite block.
            if block_time == 0:
                end_time = float('inf')

        # Extract stream keys and IDs
        if len(stream_args) % 2 != 0:
            raise RedisException("The number of stream keys must match the number of start IDs.")

        num_streams = len(stream_args) // 2
        stream_keys = stream_args[:num_streams]
        start_ids = stream_args[num_streams:]

        for idx, val in enumerate(start_ids):

            if val == "$":
                stream_key = stream_keys[idx]
                # Hackish way, since we need to freeze the key
                val = max(self.db.data[stream_key].keys())

            # For XREAD, start is exclusive
            start_ids[idx] = f"({val}"

        combined_response = []

        while True:
            for stream_key, start_id in zip(stream_keys, start_ids):
                stream_data = self.db.get_range_stream(stream_key, start_id)
                if stream_data:
                    combined_response.append([stream_key, stream_data])

            if combined_response:
                break

            if block_time is None:
                break

            current_time = asyncio.get_event_loop().time()
            if current_time > end_time:
                break

            # Sleep for a short time to avoid busy waiting
            await asyncio.sleep(0.2)

        if combined_response:
            return combined_response, RedisType.ARRAY

        return None, RedisType.BULK_STRING  # No matching data found for any streams

    async def get(self, key):

        key = key[0]
        value = self.db.get(key)

        return value, RedisType.BULK_STRING

    async def increment(self, key):

        key = key[0]
        value = self.db.get(key)

        if value is None:
            value = 0

        try:
            value = int(value)
        except ValueError:
            raise RedisException("value is not an integer or out of range")
        value += 1

        self.db.set(key, str(value))

        return value, RedisType.INTEGER

    async def type(self, key):
        key = key[0]
        value = self.db.get(key)

        value_type = "none"

        if isinstance(value, str):
            value_type = "string"
        elif isinstance(value, dict):
            value_type = "stream"

        return value_type, RedisType.SIMPLE_STRING

    async def keys(self, pattern):
        """
        Match the pattern against DB keys, and return that
        """

        result = []
        for key in self.db:
            if fnmatch.fnmatch(key, pattern[0]):
                result.append(key)

        return result, RedisType.ARRAY

    async def config_get(self, args):
        key = args[0]
        value = os.getenv(key)
        return [key, value], RedisType.ARRAY

    async def config(self, args):

        subcommand = args[0].lower()

        config_map = {
            "get": self.config_get,
        }

        if subcommand not in config_map:
            raise RedisException(f"Invalid config subcommand: {subcommand}")

        return await config_map[subcommand](args[1:])

    async def info_replication(self):
        is_replica = os.getenv("replicaof")
        role = "slave" if is_replica else "master"

        # Initialize the response dictionary with the role
        response_parts = {"role": role}

        # Add additional master-specific information if the node is a master
        if role == "master":
            response_parts["master_repl_offset"] = self.replication_offset
            response_parts["master_replid"] = self.replication_id

        # Convert dictionary to formatted response lines and encode
        response_lines = [f"{key}:{value}" for key, value in response_parts.items()]
        return "\r\n".join(response_lines), RedisType.BULK_STRING

    async def info(self, args=None):

        args = args or []

        if not args:
            raise RedisException("Currently, INFO command expects subcommand")

        subcommand = args[0].lower()

        info_map = {
            "replication": self.info_replication,
        }

        if subcommand not in info_map:
            raise RedisException(f"Invalid info subcommand: {subcommand}")

        return await info_map[subcommand]()

    async def wait(self, args):
        """
        Sends response back to wait command with continuous checking for replica sync.
        Exits when either the required number of replicas are synced or timeout is reached.

        Args:
            args[0]: Required minimum number of synced replicas
            args[1]: Timeout in milliseconds
        """
        required_min_sync = int(args[0])
        timeout_ms = int(args[1])
        timeout_seconds = timeout_ms / 1000.0  # Convert milliseconds to seconds

        # Capture the current offset before sending REPLCONF
        # This ensures we wait for all writes that occurred before the WAIT command
        target_offset = self.replication_offset

        if target_offset == 0:
            return len(self.connection_registry.get_replicas()), RedisType.INTEGER

        # Calculate when the timeout will occur
        start_time = asyncio.get_event_loop().time()
        end_time = start_time + timeout_seconds

        # Send initial GETACK command to all replicas
        await self.write_to_replicas(self.encoder.encode_array(["REPLCONF", "GETACK", "*"]))

        while True:
            # Check current sync status
            replicas_synced = self.connection_registry.check_replica_sync(target_offset)

            # If we have enough synced replicas, return immediately
            if replicas_synced >= required_min_sync:
                return replicas_synced, RedisType.INTEGER

            # Check if we've exceeded the timeout
            current_time = asyncio.get_event_loop().time()
            if current_time >= end_time:
                return replicas_synced, RedisType.INTEGER

            # Calculate how long to wait before next check
            # Use a small interval (e.g., 100ms) but don't exceed remaining timeout
            remaining_time = end_time - current_time
            wait_time = min(0.1, remaining_time)  # 100ms check interval

            # Wait before next check
            await asyncio.sleep(wait_time)

    async def replconf_getack(self, args):
        """
        Sends response back to replconf getack command.
        """

        return ["REPLCONF", "ACK", str(self.bytes_processed)], RedisType.ARRAY

    async def replconf_ack(self, args, writer):
        """
        Once master recives an acknowledgement,
        it updates the correct offset
        """

        await self.connection_registry.update_replica_offset(writer, int(args[0]))

    async def replconf(self, args, writer=None):
        """
        Sends response back to replconf command.
        """

        args = args or []

        if not args:
            raise RedisException("Currently, REPLCONF command expects subcommand")

        subcommand = args[0].lower()

        if subcommand == "getack":
            return await self.replconf_getack(args[1:])

        if subcommand == "ack":
            return await self.replconf_ack(args[1:], writer)

        # If it doesn't match, send OK. We will add error handling later
        return "OK", RedisType.SIMPLE_STRING

    async def psync(self, args, writer):
        """
        Return fullresync response back to psync command.
        """

        full_resync_command = self.encoder.encode_simple_string(
            f"FULLRESYNC {self.replication_id} {self.replication_offset}"
        ).encode('utf-8')

        empty_rdb = base64.b64decode(EMPTY_RDB)

        # Asynchronously add replica to registry
        await self.connection_registry.add_replica(
            writer,
            replication_id=self.replication_id,
            offset=self.replication_offset
        )

        return full_resync_command + self.encoder.encode_file(empty_rdb), None

    async def multi(self, args):

        # Initialize Transaction Queue
        self.transaction_queue = []

        return "OK", RedisType.SIMPLE_STRING

    async def exec(self, args):

        if self.transaction_queue is None:
            raise RedisException("EXEC without MULTI")

        responses = []

        # Dummy transaction for now
        for command, comm_arr in self.transaction_queue:
            response, _ = await self._execute(command, comm_arr, execute_transaction=True)
            responses.append(response)

        self.transaction_queue = None  # Clear the transaction queue

        return responses, RedisType.ARRAY

    async def discard(self, args):

        if self.transaction_queue is None:
            raise RedisException("DISCARD without MULTI")

        self.transaction_queue = None  # Clear the transaction queue

        return "OK", RedisType.SIMPLE_STRING

    ##### Functions which handle meta-logic ####################

    async def write_to_replicas(self, data):
        """
        Write data to all registered replicas
        """
        await self.connection_registry.broadcast(data)
        self.replication_offset += len(data)

    def get_command(self, command_arr):
        command = command_arr
        if isinstance(command_arr, list):
            command = command_arr[0]
            command_arr = command_arr[1:]

        command = command.lower()
        return command, command_arr

    def get_command_kls(self, command):

        kls_map = {
            PING: self.ping,
            ECHO: self.echo,
            SET: self.set,
            GET: self.get,
            INCR: self.increment,
            XADD: self.xadd,
            XRANGE: self.xrange,
            XREAD: self.xread,
            MULTI: self.multi,
            EXEC: self.exec,
            DISCARD: self.discard,
            CONFIG: self.config,
            KEYS: self.keys,
            INFO: self.info,
            REPLCONF: self.replconf,
            PSYNC: self.psync,
            WAIT: self.wait,
            TYPE: self.type,
        }
        kls = kls_map.get(command)
        if not kls:
            raise RedisException("Invalid command")

        return kls

    async def _execute(self, command, command_arg, writer=None, execute_transaction=False):

        # Once we have transaction started, we dont execute any command
        if self.transaction_queue is not None and not execute_transaction:

            # End transaction
            if command == EXEC:
                return await self.exec(command_arg)

            # Discard Transaction
            if command == DISCARD:
                return await self.discard(command_arg)

            self.transaction_queue.append((command, command_arg))
            return "QUEUED", RedisType.SIMPLE_STRING

        # Commands which need to be passed writer argument
        writer_set = {PSYNC, REPLCONF}

        kls = self.get_command_kls(command)

        try:
            if command in writer_set:
                return await kls(command_arg, writer)

            return await kls(command_arg)

        except RedisException as exc:
            return exc, RedisType.ERROR

    async def execute(self, command, command_arg, writer=None, execute_transaction=False):
        response = await self._execute(command, command_arg, writer, execute_transaction)
        if response:
            return self.encode(response[0], response[1])

    async def handle_master_command(self, command_data, writer):

        command_arr = RedisDecoder().decode(command_data)
        command, command_arr = self.get_command(command_arr)

        # Commands which need to be broadcasted to the replicas
        broadcast_set = {SET}
        if command in broadcast_set:
            await self.write_to_replicas(command_data)

        return await self.execute(command, command_arr, writer)

    async def handle_replica(self, command_data, propogated_command):
        """
        If it is replica, it might get multiple Write commands
        """
        command_arr = RedisDecoder().multi_command_decoder(command_data)

        # Commands to which Replicas need to reply in case of propogation
        reply_back_commands = {REPLCONF}

        responses = []

        for command, comm_length in command_arr:
            comm, comm_arr = self.get_command(command)
            response = await self.execute(comm, comm_arr)

            # Send back the response to the client
            # In case this is propogation, only send back replies when needed
            if not propogated_command or comm in reply_back_commands:
                responses.append(response)

            self.bytes_processed += comm_length

        return "".join(responses)

    async def handle(self, command_data, writer=None, propogated_command:bool=False):
        """
        Handle commands from master or replica

        Args:
            propogated_command: Is this command propogated from master to replica?
        """

        if self.is_replica:
            return await self.handle_replica(command_data, propogated_command)

        return await self.handle_master_command(command_data, writer)

    def encode(self, data, data_type):

        if data_type == RedisType.INTEGER:
            return self.encoder.encode_integer(data)
        if data_type == RedisType.BULK_STRING:
            return self.encoder.encode_bulk_string(data)
        if data_type == RedisType.ARRAY:
            return self.encoder.encode_array(data)
        if data_type == RedisType.SIMPLE_STRING:
            return self.encoder.encode_simple_string(data)
        if data_type == RedisType.ERROR:
            return self.encoder.encode_error(data)

        # Special Case, data is already encoded, return as is
        if data_type is None:
            return data

        raise RedisException(f"Unsupported data type: {data_type}")
