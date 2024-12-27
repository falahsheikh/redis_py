import os
import time

import pytest

from app.handler import RedisCommandHandler
from app.serialiser import RedisEncoder
from app.database import Database

encoder = RedisEncoder()
db = Database()


@pytest.mark.asyncio
class TestHandler:

    @pytest.fixture(autouse=True)
    def run_around_tests(self):
        yield
        db.clear()

    async def test_ping(self):
        handler = RedisCommandHandler()
        assert await handler.handle(encoder.encode_simple_string("ping")) == "+PONG\r\n"

    async def test_echo(self):
        handler = RedisCommandHandler()
        assert await handler.handle(encoder.encode_array(["ECHO", "hello"])) == "$5\r\nhello\r\n"

    async def test_set(self):
        handler = RedisCommandHandler()
        assert await handler.handle(encoder.encode_array(["SET", "key", "value"])) == "+OK\r\n"
        assert handler.db.get("key") == "value"

    async def test_xadd(self):
        handler = RedisCommandHandler()
        await handler.handle(encoder.encode_array(["XADD", "stream", "0-1", "field1", "value1", "field2", "value2"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "0-2", "field1", "a", "field2", "b"]))

        assert handler.db.get("stream") == {
            "0-1": {"field1": "value1", "field2": "value2"},
            "0-2": {"field1": "a", "field2": "b"},
        }

    async def test_xadd_invalid_stream_id(self):
        handler = RedisCommandHandler()
        response = await handler.handle(encoder.encode_array(
            ["XADD", "stream", "0-0", "field1", "value1", "field2", "value2"])
        )
        assert response == "-ERR The ID specified in XADD must be greater than 0-0\r\n"

    async def test_xadd_invalid_stream_id_incremental(self):
        handler = RedisCommandHandler()
        response = await handler.handle(encoder.encode_array(
            ["XADD", "stream", "1-5", "field1", "value1", "field2", "value2"])
        )
        assert response == encoder.encode_bulk_string("1-5")

        response = await handler.handle(encoder.encode_array(
            ["XADD", "stream", "1-3", "field1", "value1", "field2", "value2"])
        )
        assert response == "-ERR The ID specified in XADD is equal or smaller than the target stream top item\r\n"

    async def test_xadd_stream_id(self):
        handler = RedisCommandHandler()
        assert await handler.handle(
            encoder.encode_array(["XADD", "stream", "0-*", "k", "v"])
        ) == encoder.encode_bulk_string("0-1")
        assert await handler.handle(
            encoder.encode_array(["XADD", "stream", "0-*", "k", "v"])
        ) == encoder.encode_bulk_string("0-2")

        assert await handler.handle(
            encoder.encode_array(["XADD", "stream", "5-3", "k", "v"])
        ) == encoder.encode_bulk_string("5-3")
        assert await handler.handle(
            encoder.encode_array(["XADD", "stream", "5-*", "k", "v"])
        ) == encoder.encode_bulk_string("5-4")

    async def test_xrange_explicit(self):

        handler = RedisCommandHandler()
        await handler.handle(encoder.encode_array(["XADD", "stream", "5-2", "k", "2"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "5-3", "k", "3"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "5-5", "k", "5"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "5-6", "k", "6"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "5-7", "k", "6"]))

        response = await handler.handle(encoder.encode_array(["XRANGE", "stream", "5-3", "5-6"]))

        expected_response = [
            "*3\r\n",
            "*2\r\n",
            "$3\r\n5-3\r\n",
            "*2\r\n",
            "$1\r\nk\r\n",
            "$1\r\n3\r\n",
            "*2\r\n",
            "$3\r\n5-5\r\n",
            "*2\r\n",
            "$1\r\nk\r\n",
            "$1\r\n5\r\n",
            "*2\r\n",
            "$3\r\n5-6\r\n",
            "*2\r\n",
            "$1\r\nk\r\n",
            "$1\r\n6\r\n",
        ]

        assert response == "".join(expected_response)

    async def test_xrange_implicit(self):

        handler = RedisCommandHandler()
        await handler.handle(encoder.encode_array(["XADD", "stream", "4-2", "k", "2"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "5-3", "k", "3"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "5-5", "k", "5"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "6-6", "k", "6"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "7-7", "k", "6"]))

        response = await handler.handle(encoder.encode_array(["XRANGE", "stream", "5", "6"]))

        expected_response = [
            "*3\r\n",
            "*2\r\n",
            "$3\r\n5-3\r\n",
            "*2\r\n",
            "$1\r\nk\r\n",
            "$1\r\n3\r\n",
            "*2\r\n",
            "$3\r\n5-5\r\n",
            "*2\r\n",
            "$1\r\nk\r\n",
            "$1\r\n5\r\n",
            "*2\r\n",
            "$3\r\n6-6\r\n",
            "*2\r\n",
            "$1\r\nk\r\n",
            "$1\r\n6\r\n",
        ]

        assert response == "".join(expected_response)

    async def test_xread_single_stream(self):

        handler = RedisCommandHandler()
        await handler.handle(encoder.encode_array(["XADD", "stream", "4-2", "k", "2"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "5-3", "k", "3"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "5-5", "k", "5"]))

        response = await handler.handle(encoder.encode_array(["XREAD", "streams", "stream", "5"]))

        expected_response = [
            "*1\r\n",
            "*2\r\n"
            "$6\r\nstream\r\n"
            "*2\r\n",
            "*2\r\n",
            "$3\r\n5-3\r\n",
            "*2\r\n",
            "$1\r\nk\r\n",
            "$1\r\n3\r\n",
            "*2\r\n",
            "$3\r\n5-5\r\n",
            "*2\r\n",
            "$1\r\nk\r\n",
            "$1\r\n5\r\n",
        ]

        assert response == "".join(expected_response)

    async def test_xread_multiple(self):

        handler = RedisCommandHandler()
        await handler.handle(encoder.encode_array(["XADD", "stream", "4-2", "k", "2"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "5-3", "k", "3"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "5-5", "k", "5"]))
        await handler.handle(encoder.encode_array(["XADD", "stream2", "4-2", "k", "2"]))
        await handler.handle(encoder.encode_array(["XADD", "stream2", "5-3", "k", "3"]))
        await handler.handle(encoder.encode_array(["XADD", "stream2", "6-5", "k", "5"]))

        response = await handler.handle(encoder.encode_array(
            ["XREAD", "streams", "stream", "stream2", "5", "6"])
        )

        expected_response = [
            "*2\r\n",

            "*2\r\n"
            "$6\r\nstream\r\n"
            "*2\r\n",
            "*2\r\n",
            "$3\r\n5-3\r\n",
            "*2\r\n",
            "$1\r\nk\r\n",
            "$1\r\n3\r\n",
            "*2\r\n",
            "$3\r\n5-5\r\n",
            "*2\r\n",
            "$1\r\nk\r\n",
            "$1\r\n5\r\n",

            "*2\r\n"
            "$7\r\nstream2\r\n"
            "*1\r\n",
            "*2\r\n",
            "$3\r\n6-5\r\n",
            "*2\r\n",
            "$1\r\nk\r\n",
            "$1\r\n5\r\n",
        ]

        assert response == "".join(expected_response)

    async def test_xread_partial_stream(self):
        """
        If we search across multiple streams, and data is only available in one stream
        WE should only return that single stream
        """

        handler = RedisCommandHandler()
        await handler.handle(encoder.encode_array(["XADD", "stream", "4-2", "k", "2"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "5-3", "k", "3"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "5-5", "k", "5"]))

        response = await handler.handle(encoder.encode_array(["XREAD", "streams", "stream", "stream2", "5", "0"]))

        expected_response = [
            "*1\r\n",
            "*2\r\n"
            "$6\r\nstream\r\n"
            "*2\r\n",
            "*2\r\n",
            "$3\r\n5-3\r\n",
            "*2\r\n",
            "$1\r\nk\r\n",
            "$1\r\n3\r\n",
            "*2\r\n",
            "$3\r\n5-5\r\n",
            "*2\r\n",
            "$1\r\nk\r\n",
            "$1\r\n5\r\n",
        ]

        assert response == "".join(expected_response)

    async def test_xread_nil(self):
        """
        If no response matches we expect nil response
        """

        handler = RedisCommandHandler()
        await handler.handle(encoder.encode_array(["XADD", "stream", "4-2", "k", "2"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "5-3", "k", "3"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "5-5", "k", "5"]))

        response = await handler.handle(encoder.encode_array(["XREAD", "streams", "stream", "stream2", "6", "0"]))
        assert response == "$-1\r\n"

    async def test_get(self):
        handler = RedisCommandHandler()
        await handler.handle(encoder.encode_array(["SET", "key", "value"]))
        assert await handler.handle(encoder.encode_array(["GET", "key"])) == "$5\r\nvalue\r\n"

    async def test_null_get(self):
        handler = RedisCommandHandler()
        assert await handler.handle(encoder.encode_array(["GET", "non_existent_key"])) == "$-1\r\n"

    async def test_set_with_expiry_px(self):
        handler = RedisCommandHandler()
        assert await handler.handle(encoder.encode_array(["SET", "expiry_key", "value", "PX", "10"])) == "+OK\r\n"

        assert await handler.handle(encoder.encode_array(["GET", "expiry_key"])) == "$5\r\nvalue\r\n"
        time.sleep(0.2)
        assert await handler.handle(encoder.encode_array(["GET", "expiry_key"])) == "$-1\r\n"

    @pytest.mark.slow
    async def test_set_with_expiry_ex(self):
        handler = RedisCommandHandler()
        assert await handler.handle(encoder.encode_array(["SET", "expiry_key", "value", "EX", "1"])) == "+OK\r\n"

        assert await handler.handle(encoder.encode_array(["GET", "expiry_key"])) == "$5\r\nvalue\r\n"
        time.sleep(2)
        assert await handler.handle(encoder.encode_array(["GET", "expiry_key"])) == "$-1\r\n"

    async def test_config_get(self):
        handler = RedisCommandHandler()
        os.environ["TEST_VAR"] = "test_value"
        assert await handler.handle(encoder.encode_array(["CONFIG", "GET", "TEST_VAR"])) == "*2\r\n$8\r\nTEST_VAR\r\n$10\r\ntest_value\r\n"

    async def test_keys(self):
        handler = RedisCommandHandler()

        await handler.handle(encoder.encode_array(["SET", "key1", "value1"]))
        await handler.handle(encoder.encode_array(["SET", "key2", "value2"]))
        await handler.handle(encoder.encode_array(["SET", "key3", "value3"]))

        assert await handler.handle(encoder.encode_array(["KEYS", "*"])) == "*3\r\n$4\r\nkey1\r\n$4\r\nkey2\r\n$4\r\nkey3\r\n"
        assert await handler.handle(encoder.encode_array(["KEYS", "*1"])) == "*1\r\n$4\r\nkey1\r\n"

    async def test_info_replication(self):
        handler = RedisCommandHandler()
        master_replication = await handler.handle(encoder.encode_array(["INFO", "replication"]))

        resp = master_replication.split("\r\n")
        resp_map = {}

        for item in resp[1:]:

            if not item:
                continue

            key, value = item.split(":")
            resp_map[key] = value

        assert resp_map["role"] == "master"
        assert resp_map["master_repl_offset"] == "0"
        assert len(resp_map["master_replid"]) == 40

    async def test_info_replication_slave(self):
        handler = RedisCommandHandler()
        os.environ["replicaof"] = "localhost 6379"
        assert await handler.handle(encoder.encode_array(["INFO", "replication"])) == "$10\r\nrole:slave\r\n"
        del os.environ["replicaof"]

    async def test_replconf(self):
        handler = RedisCommandHandler()
        assert await handler.handle(encoder.encode_array(["REPLCONF", "capa", "psycn2"])) == "+OK\r\n"

    async def test_replconf_getack_subcommand(self):
        handler = RedisCommandHandler()
        response = await handler.handle(encoder.encode_array(["REPLCONF", "getack", "subcommand"]))
        assert response == encoder.encode_array(["REPLCONF", "ACK", "0"])

    async def test_psync(self):
        handler = RedisCommandHandler()
        resp = await handler.handle(encoder.encode_array(["psync", "master_replid", "offset"]), "writer")
        assert resp.startswith(b"+FULLRESYNC")

    async def test_type(self):

        handler = RedisCommandHandler()

        await handler.handle(encoder.encode_array(["SET", "key1", "value1"]))
        await handler.handle(encoder.encode_array(["XADD", "stream", "0-2", "field1", "a", "field2", "b"]))

        assert await handler.handle(
            encoder.encode_array(["TYPE", "key1"])
        ) == encoder.encode_simple_string("string")

        assert await handler.handle(
            encoder.encode_array(["TYPE", "key2"])
        ) == encoder.encode_simple_string("none")

        assert await handler.handle(
            encoder.encode_array(["TYPE", "stream"])
        ) == encoder.encode_simple_string("stream")

    async def test_incr(self):

        handler = RedisCommandHandler()

        await handler.handle(encoder.encode_array(["SET", "key1", "3"]))
        assert await handler.handle(
            encoder.encode_array(["INCR", "key1"])
        ) == encoder.encode_integer(4)

    async def test_multi(self):

        handler = RedisCommandHandler()

        assert await handler.handle(encoder.encode_array(["MULTI"])) == "+OK\r\n"
        assert handler.transaction_queue == []
