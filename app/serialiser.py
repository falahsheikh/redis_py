TERMINATOR = "\r\n"


class RedisType:
    SIMPLE_STRING = "+"
    BULK_STRING = "$"
    ARRAY = "*"
    INTEGER = ":"
    ERROR = "-"


class RedisDecoder:
    """
    Decode Redis Request
    """

    def __init__(self):
        self.bytes_processed = 0

    def decode_simple_string(self, arr: list[str]):
        """
        Processing for example: "+OK\r\n"
        So, bytes would len of +OK + terminator
        """
        self.bytes_processed += len(arr[0]) + len(TERMINATOR)
        return arr[0][1:], arr[1:]

    def decode_bulk_string(self, arr: list[str]):
        """
        Processing for example:
        "$5\r\nhello\r\n"
        So, len would be $5 + terminator + hello + terminator
        """
        self.bytes_processed += len(arr[0]) + len(TERMINATOR) + len(arr[1]) + len(TERMINATOR)
        return arr[1], arr[2:]

    def decode_array(self, arr: list[str]):
        """
        Processing for example:
        "*2\r\n$3\r\nfoo\r\n$3\r\nbar\r\n"
        So, len would be *<count> + len of terminator
        Each array element would be counted successfully in their own function
        """
        val = []
        count = int(arr[0][1:])

        self.bytes_processed += len(arr[0]) + len(TERMINATOR)

        rem_arr = arr[1:]

        while True:
            if len(val) == count:
                break

            item, rem_arr = self._decode(rem_arr)
            val.append(item)

        return val, rem_arr

    def multi_command_decoder(self, data) -> list[(str, int)]:
        """
        Decode potentially multiple commands in a single Redis request string.

        Args:
            data (str): Redis request string containing one or more commands

        Returns:
            list: Each element is tuple of command with length of command
        """
        arr = data.split(TERMINATOR)
        if arr[-1] == "":
            arr = arr[:-1]  # Remove the last empty string

        # List to store multiple decoded commands
        commands = []

        # Continue decoding until all data is processed
        while arr:

            # Decode the first command
            command, arr = self._decode(arr)

            # Add the decoded command to the list
            if command is not None:
                commands.append((command, self.bytes_processed))
                self.bytes_processed = 0  # Reset byte count for next command

        return commands

    def decode(self, data):
        """
        Decodes a Redis request string into a Python object.

        Args:
            str: Redis request string

        Returns:
            Any: The decoded Python object.
        """

        arr = data.split(TERMINATOR)
        return self._decode(arr)[0]

    def _decode(self, arr: list[str]):
        """
        Decodes a Redis request string into a Python object.

        Args:
            arr (str): Array of strings

        Returns:
            Any: The decoded Python object.
            Array: The remaining data after decoding.
        """

        resp_type = arr[0]

        if resp_type[0] == RedisType.SIMPLE_STRING:
            return self.decode_simple_string(arr)

        if resp_type[0] == RedisType.BULK_STRING:
            return self.decode_bulk_string(arr)

        if resp_type[0] == RedisType.ARRAY:
            return self.decode_array(arr)

        return None, []


class RedisEncoder:

    def encode_simple_string(self, data):
        return f"{RedisType.SIMPLE_STRING}{data}{TERMINATOR}"

    def encode_bulk_string(self, data):
        if data is None:
            return f"{RedisType.BULK_STRING}-1{TERMINATOR}"           # Null bulk string
        return f"{RedisType.BULK_STRING}{len(data)}{TERMINATOR}{data}{TERMINATOR}"

    def encode_array(self, data):
        """
        Encode array
        """
        ret = [f"{RedisType.ARRAY}{len(data)}{TERMINATOR}"]

        for item in data:
            if isinstance(item, str):
                ret.append(self.encode_bulk_string(item))
            elif isinstance(item, list):
                ret.append(self.encode_array(item))  # Assume integer for other types of data
            elif isinstance(item, int):
                ret.append(self.encode_integer(item))
            elif isinstance(item, Exception):
                ret.append(self.encode_error(item))

        return "".join(ret)

    def encode_file(self, data: bytes):
        """
        Similar to bulk string except we do not add end terminator.
        Also, we expect data to be in bytes and give back bytes
        """

        return f"{RedisType.BULK_STRING}{len(data)}{TERMINATOR}".encode("utf-8") + data

    def encode_integer(self, data):
        """
        Encode integer
        """
        return f"{RedisType.INTEGER}{str(data)}{TERMINATOR}"

    def encode_error(self, error, error_code=None):
        """
        Encode error
        """
        error_code = error_code or "ERR"
        return f"{RedisType.ERROR}{error_code} {error}{TERMINATOR}"
