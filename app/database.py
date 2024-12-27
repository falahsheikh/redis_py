from collections import OrderedDict
from datetime import datetime
from enum import Enum

from app.exceptions import RedisException
from app.utils import Singleton, StreamUtils

STREAM = "stream"


class Stream(OrderedDict):
    """
    Base class for stream
    """


class DBErrorCode(Enum):
    STREAM_ID_SMALLER_THAN_TOP = (STREAM, "small-top", "Stream ID is smaller than top element")
    STREAM_ID_SMALLER_THAN_0 = (STREAM, "small-first", "Stream ID is smaller than 0-1")

    def __init__(self, module, code, message):
        self.code = code
        self.module = module
        self.message = message


class RedisDBException(RedisException):
    """
    Base class for DB Exceptions
    """

    def __init__(self, error_code: DBErrorCode):
        self.error_code = error_code
        super().__init__(f"[{error_code.code}] {error_code.message}")

    @property
    def code(self):
        return self.error_code.code

    @property
    def module(self):
        return self.error_code.module

    @property
    def message(self):
        return self.error_code.message


class Database(metaclass=Singleton):

    def __init__(self, data=None):
        self.data = data or OrderedDict()

    def clear(self):
        self.data = {}

    def set(self, key, value, expires=None):
        self.data[key] = {
            "value": value,
            "expires_at": expires,
        }

    def add_stream(self, stream_key, stream_id, *args):
        """
        Add the stream_id to the stream_key

        Final stream format:
        <stream_key>: {
            "<stream_id_1">: {
                "key1": "value1",
                "key2": "value2"
            },
            ...
        }
        """

        if not StreamUtils.validate_stream_ids("0-0", stream_id):
            raise RedisDBException(DBErrorCode.STREAM_ID_SMALLER_THAN_0)

        # First check if stream_key exists, if not, create one
        if stream_key not in self.data:
            self.data[stream_key] = Stream()
            last_stream_id = "0-0"
        else:
            last_stream_id = next(reversed(self.data[stream_key]))
            if not StreamUtils.validate_stream_ids(last_stream_id, stream_id):
                raise RedisDBException(DBErrorCode.STREAM_ID_SMALLER_THAN_TOP)

        stream_id = StreamUtils.generate_stream_id(stream_id, last_stream_id)

        # Args are key1, value1, key2, value2 format
        result = {args[i]: args[i + 1] for i in range(0, len(args), 2)}
        self.data[stream_key][stream_id] = result
        return stream_id

    def get_range_stream(self, stream_key: str, start_stream_id: str, end_stream_id: str="+") -> list:
        """
        Return a list of stream_ids from start_stream_id to end_stream_id, inclusive.
        """

        streams = self.get(stream_key)
        if streams is None:
            return []

        if start_stream_id == "-":
            start_stream_id = "0-0"

        if end_stream_id == "+":
            end_stream_id = max(self.data[stream_key].keys())

        return StreamUtils.get_single_stream(start_stream_id, end_stream_id, streams)

    def get(self, key: str):
        value = self.data.get(key)

        if isinstance(value, Stream):
            return value

        if value is not None:
            if value["expires_at"] is not None and value["expires_at"] < datetime.now():
                self.del_key(key)
                value = {}

        if value is None:
            value = {}

        return value.get("value")

    def del_key(self, key):
        if key in self.data:
            del self.data[key]

    def __iter__(self):
        return iter(self.data)
