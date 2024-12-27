from datetime import datetime
import os

REDIS_METADATA = 250  # b"\xfa"
REDIS_HASH_TABLE = 251  # b"\xfb"   ## Resize DB
REDIS_EXPIRY_MS = 252 # b"\xfc"
REDIS_EXPIRY_SEC = 253 # b"\xfd"
REDIS_DB_SELECTOR = 254 # b"\xfe"
REDIS_EOF = 255       # b"\xff"


# Value Types
STRING_ENCODING = 0
LIST_ENCODING = 1
SET_ENCODING = 2
SORTED_SET_ENCODING = 3
HASH_ENCODING = 4
ZIPMAP_ENCODING = 9
ZIPLIST_ENCODING = 10
INTSET_ENCODING = 11
SORTED_SET_IN_ZIPLIST_ENCODING = 12
HASHMAP_IN_ZIPLIST_ENCODING = 13  # Introduced in RDB version 4
LIST_IN_QUICKLIST_ENCODING = 14  # Introduced in RDB version 7



class RDBParser:
    """
    A file-based database
    File is based on RDB standard
    https://rdb.fnordig.de/file_format.html
    """

    def __init__(self, _dir = None, _file= None):
        filename = _file or os.getenv("dbfilename", "dump.rdb")
        _dir = _dir or os.getenv("dir")

        if _dir:
            filename = os.path.join(_dir, filename)

        self.protocol_version = ""
        self.metadata = {}
        self.databases = {}

        self.load(filename)

    #############  Helper Utiltiies #################################

    def read_length(self, fd):
        """
        Read length.

        This is how length encoding works :
            Read one byte from the stream, compare the two most significant bits

        00	The next 6 bits represent the length
        01	Read one additional byte. The combined 14 bits represent the length
        10	Discard the remaining 6 bits. The next 4 bytes from the stream represent the length
        11	The next object is encoded in a special format. The remaining 6 bits indicate the format
        """

        byte_arr = fd.read(1)
        is_integer = False

        msb_2 = int.from_bytes(byte_arr, 'big') >> 6
        length = 0

        if msb_2 == 0:
            length = int.from_bytes(byte_arr, 'big')

        elif msb_2 == 3:
            # In this case, the remaining 6 bits are read.

            # If the value of those 6 bits is:
            # 0 indicates that an 8 bit integer follows
            # 1 indicates that a 16 bit integer follows
            # 2 indicates that a 32 bit integer follows
            int_rep = int.from_bytes(byte_arr, 'big') & 11

            if int_rep == 0:
                is_integer = True
                length = 1
            elif int_rep == 1:
                is_integer = True
                length = 2
            elif int_rep == 2:
                is_integer = True
                length = 4
            # TODO
            # handle int_rep = 3 which is special case for compression

        elif msb_2 == 2:
            # Discard the remaining 6 bits. The next 4 bytes from the stream represent the length
            length = int.from_bytes(fd.read(4), 'big')

        # TODO
        # handle msb_2 == 1

        return length, is_integer

    def read_string(self, fd) -> str:
        """
        Read string.
        First character gives the length of the string which should be read

        We need to add the cases where encoding is present
        """
        # Read string length
        length, is_integer = self.read_length(fd)

        # Read string data
        data = fd.read(length)

        if is_integer:
            # Convert integer to string
            data = str(int.from_bytes(data, 'little'))
        else:
            data = data.decode('utf-8')

        return data

    def read_integer(self, fd):
        """
        Read size-encoded integer
        """

        length, is_encoded = self.read_length(fd)

        # Read data
        data = fd.read(length)

        if is_encoded:
            # Convert integer to string
            data = int.from_bytes(data, 'little')
        else:
            data = int(data.decode('utf-8'))

        return data

    def read_code(self, fd):
        return int.from_bytes(fd.read(1), 'little')

    #############  File Parser Functions #################################

    def read_header(self, fd):
        # Read RDB header
        magic_str = fd.read(5)
        if magic_str!= b"REDIS":
            raise ValueError("Invalid RDB file")

        version = fd.read(4)
        self.protocol_version = int(version, 2)

    def read_metadata(self, fd):
        """
        After headers, we need to decode metadata
        Metadata are key-value pairs
        Both keys and values are string encoded
        After each key-value pair, we again get the code denoting that next bit is metadata or next section
        """

        code = ""

        while True:
            key = self.read_string(fd)
            value = self.read_string(fd)
            self.metadata[key] = value

            code = self.read_code(fd)
            if code != REDIS_METADATA:
                break

        return code

    def read_db_index(self, fd):
        # Read the db index
        return int(self.read_length(fd)[0])

    def read_hash_sizes(self, fd):
        hash_size = int(self.read_length(fd)[0])
        expiry_sizes = int(self.read_length(fd)[0])
        return hash_size, expiry_sizes

    def read_single_data(self, fd):
        """
        Read a single key-value pair

        Optional expire information (one of the following):
            Timestamp in seconds:
                FD
                Expire timestamp in seconds (4-byte unsigned integer)
            Timestamp in milliseconds:
                FC
                Expire timestamp in milliseconds (8-byte unsigned long)
        Value type (1-byte flag)
        Key (string encoded)
        Value (encoding depends on value type)
        """

        # First determine if it has optional component
        optional_code = self.read_code(fd)
        value_type = optional_code
        value = ""
        expiry_at = None

        if optional_code == REDIS_EXPIRY_SEC:
            expiry_at = int.from_bytes(fd.read(4), "little")
            value_type = self.read_code(fd)

        elif optional_code == REDIS_EXPIRY_MS:
            expiry_at = int.from_bytes(fd.read(8), "little") // 1000
            value_type = self.read_code(fd)

        key = self.read_string(fd)

        if value_type == STRING_ENCODING:
            value = self.read_string(fd)
        # elif value_type == LIST_ENCODING:
        #     value = self.read_list(fd)
        # elif value_type == SET_ENCODING:
        #     value = self.read_set(fd)
        # elif value_type == SORTED_SET_ENCODING:
        #     value = self.read_sorted_set(fd)
        # elif value_type == HASH_ENCODING:
        #     value = self.read_hash(fd)
        # elif value_type == ZIPMAP_ENCODING:
        #     value = self.read_zipmap(fd)
        # elif value_type == ZIPLIST_ENCODING:
        #     value = self.read_ziplist(fd)
        # elif value_type == INTSET_ENCODING:
        #     value = self.read_intset(fd)
        # elif value_type == SORTED_SET_IN_ZIPLIST_ENCODING:
        #     value = self.read_sorted_set_in_ziplist(fd)
        # elif value_type == HASHMAP_IN_ZIPLIST_ENCODING:
        #     value = self.read_hashmap_in_ziplist(fd)
        # elif value_type == LIST_IN_QUICKLIST_ENCODING:
        #     value = self.read_list_in_quicklist(fd)
        else:
            raise ValueError(f"Unknown encoding type: {value_type}")

        return key, value, expiry_at

    def read_single_database(self, fd, db_index):
        """
        Databases are stored as key-value pairs
        Both keys and values are string encoded
        After each key-value pair, we again get the code denoting that next bit is database or next section
        """

        # First thing is we have to read the hash sizes
        fd.read(1)  # Reading the OP Code for Resize DB
        hash_size, _ = self.read_hash_sizes(fd)

        # Now read the data
        for _ in range(hash_size):
            key, value, expiry_at = self.read_single_data(fd)

            # Add data to the database
            self.databases[db_index][key] = {
                "value": value,
                "expires_at": datetime.fromtimestamp(expiry_at) if expiry_at else None
            }

    def read_databases(self, fd):
        """
        After metadata, we need to read databases
        There might be multiple databases stored.
        """

        code = None

        while True:

            db_index = self.read_db_index(fd)

            if db_index not in self.databases:
                self.databases[db_index] = {}

            self.read_single_database(fd, db_index)

            code = self.read_code(fd)

            if code != REDIS_DB_SELECTOR:
                break

        return code

    def read_eof(self, fd):
        """
        End the file
        """

        checksum_size = 8
        fd.read(checksum_size)

    def load(self, _file):
        """
        Load data from the file, and read it.
        Data is arranged in sequential manner:

        Headers
        Metadata
        Database
        End of file

        https://rdb.fnordig.de/file_format.html
        """

        try:
            with open(_file, 'rb') as fd:

                self.read_header(fd)

                while True:

                    code = self.read_code(fd)

                    if code == REDIS_METADATA:
                        code = self.read_metadata(fd)

                    if code == REDIS_DB_SELECTOR:
                        code = self.read_databases(fd)

                    if code == REDIS_EOF:
                        self.read_eof(fd)
                        break
        except FileNotFoundError:
            pass
