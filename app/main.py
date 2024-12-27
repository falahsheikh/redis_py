import argparse
import asyncio
import logging
import os

from app.connection_registry import ConnectionRegistry
from app.handler import RedisCommandHandler
from app.rdb.parser import RDBParser
from app.database import Database
from app.replica import Replica


logger = logging.getLogger(__name__)


async def handle_client(reader, writer):

    connection_registry = ConnectionRegistry()
    handler = RedisCommandHandler(connection_registry)

    try:
        while True:
            data = await reader.read(1024)

            if not data:
                break

            data = data.decode("utf-8")
            response = await handler.handle(data, writer)

            if response:
                if isinstance(response, str):
                    response = response.encode("utf-8")
                writer.write(response)

            await writer.drain()
    except Exception as e:
        print("Error", e)
    finally:
        # Ensure cleanup of replica if connection closes
        await connection_registry.remove_replica(writer)
        writer.close()
        await writer.wait_closed()


async def run_server(port:int):
    server = await asyncio.start_server(handle_client, "localhost", port)

    async with server:
        await server.serve_forever()


async def run_replica(master_host: str, master_port: int, self_port: int):
    handler = RedisCommandHandler()
    replica = Replica(master_host, master_port, self_port, handler)
    await replica.handshake()
    await replica.listen_for_commands()


async def main(args):

    tasks = []

    if args.dir:
        os.environ["dir"] = args.dir

    if args.dbfilename:
        os.environ["dbfilename"] = args.dbfilename

    # Always add the server task
    server_task = asyncio.create_task(run_server(args.port))
    tasks.append(server_task)

    if args.replicaof:
        os.environ["replicaof"] = args.replicaof
        master_host, master_port = args.replicaof.split()
        replica_task = asyncio.create_task(run_replica(master_host, master_port, args.port))
        tasks.append(replica_task)

    db_data = {}

    if args.dbfilename:
        rdb = RDBParser(args.dir, args.dbfilename)
        db_data = rdb.databases[0] if rdb.databases else {}

    Database(db_data)

    # Keep track of completed tasks
    while tasks:
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED
        )

        for task in done:
            try:
                await task
            except Exception as e:
                logger.exception("Task failed", e)

            # Remove completed task
            tasks.remove(task)

        # Ensure server task keeps running
        if server_task not in tasks and not server_task.done():
            tasks.append(server_task)

        # If replica task failed or completed, it won't be restarted automatically


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--dir")
    parser.add_argument("--dbfilename")
    parser.add_argument("--port", default=6379)
    parser.add_argument(
        "--replicaof",
        help="If this is specified, it is assumed that this is slave replica. '<Master HOST> <Master PORT>' is needed")
    args = parser.parse_args()

    asyncio.run(main(args))
