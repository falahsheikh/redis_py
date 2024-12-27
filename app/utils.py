from collections import OrderedDict
from itertools import chain

import string
import random
import time


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            instance = super(Singleton, cls).__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


def gen_random_string(length: int) -> str:
    """
    Generate random alphanumeric string of given length
    """

    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))


class StreamUtils:

    @classmethod
    def validate_stream_ids(cls, current_stream_id: str, incoming_stream_id: str):
        """
        Compare incoming stream_id with current stream_id.
        Stream id is combination of two strings:
            <a>-<b>
            where <a> is timestamp in seconds and <b> is str representation of integer

        incoming_stream_id should always be greater than current_stream_id.
        First timestamp is compared, and if equal then integer part is compared

        Return true if incoming_stream_id is strictly greater than current_stream_id
        (or we can generate incoming stream_id)
        """

        # WE need to generate complete, so no use checking,
        # since we will always generate correct one
        if incoming_stream_id == "*":
            return True

        # Split both stream IDs into their components
        current_timestamp, current_int = current_stream_id.split('-')
        incoming_timestamp, incoming_int = incoming_stream_id.split('-')

        # Convert components to appropriate types for comparison
        current_timestamp = int(current_timestamp)
        incoming_timestamp = int(incoming_timestamp)

        # Compare timestamps first
        if incoming_timestamp > current_timestamp:
            return True

        # We need to generate the integer part
        # We can only generate it if timestamp is equal to or greater than current
        # We already have checked for greater timestamp above
        if incoming_int == "*":
            return incoming_timestamp == current_timestamp

        current_int = int(current_int)
        incoming_int = int(incoming_int)

        if incoming_timestamp == current_timestamp:
            # If timestamps are equal, compare the integer part
            return incoming_int > current_int

        return False

    @classmethod
    def compare_stream_ids(cls, first_stream_id: str, second_stream_id: str, inclusive: bool = True) -> bool:
        """
        Compare two fully formed stream IDS

        Return true if second_stream_id is equal to greater than first_stream_id
        """

        # Split both stream IDs into their components
        first_timestamp, first_int = first_stream_id.split('-')
        second_timestamp, second_int = second_stream_id.split('-')

        first_timestamp = int(first_timestamp)
        second_timestamp = int(second_timestamp)

        if first_timestamp < second_timestamp:
            return True

        if first_timestamp > second_timestamp:
            return False

        first_int = float('inf') if first_int == "*" else int(first_int)
        second_int = float('inf') if second_int == "*" else int(second_int)

        # If timestamps are equal, compare the integer part
        if inclusive:
            return first_int <= second_int

        return first_int < second_int

    @classmethod
    def generate_stream_id(cls, incoming_stream_id: str, current_stream_id: str):
        """
        Stream ID could be:
        - *: we need to generate it
        - <timestamp>-*: We need to generate the sequence number part
        - Explicit: no need to do anything just return as it is
        """

        if incoming_stream_id == "*":
            current_timestamp = time.time_ns() // 1_000_000
            return f"{current_timestamp}-0"

        timestamp, sequence = incoming_stream_id.split("-")

        # This is explicit case
        if sequence != "*":
            return incoming_stream_id

        # Otherwise we need to generate the sequence number part
        # If current stream_id also has same timestamp, then we just increment by 1
        current_timestamp, current_sequence = current_stream_id.split("-")

        if current_timestamp == timestamp:
            seq = int(current_sequence) + 1
            return f"{timestamp}-{seq}"

        # If it is new timestamp, then we need to start from the beginning
        return f"{timestamp}-0"

    @classmethod
    def get_single_stream(cls, start_stream_id: str, end_stream_id: str, stream: OrderedDict):
        """
        Return list of streams for which start and end matches.
        Supports inclusive (default) or exclusive range based on parentheses.
        """

        matched_streams = []

        # Determine inclusivity for start and end
        start_inclusive = not start_stream_id.startswith("(")
        end_inclusive = not end_stream_id.startswith("(")

        # Strip parentheses if present
        if not start_inclusive:
            start_stream_id = start_stream_id[1:]

        if not end_inclusive:
            end_stream_id = end_stream_id[1:]

        # If we are not given sequence, then for start assume 0
        if len(start_stream_id.split("-")) == 1:
            start_stream_id = f"{start_stream_id}-0"

        # If we are not given sequence, then for end assume infinity
        if len(end_stream_id.split("-")) == 1:
            end_stream_id = f"{end_stream_id}-*"

        start_found = False

        for stream_id, value in stream.items():

            if cls.compare_stream_ids(start_stream_id, stream_id, inclusive=start_inclusive):
                start_found = True

            if start_found:

                if not cls.compare_stream_ids(stream_id, end_stream_id, inclusive=end_inclusive):
                    break

                # We have this format:
                # <stream_id>: {
                #     "key1": "value1",
                #     "key2": "value2"
                # }
                # We need to append in this format
                # [ <stream_id>, [ key1, value1, key2, value ] ]

                element = [stream_id, list(chain.from_iterable(value.items()))]
                matched_streams.append(element)

        return matched_streams
