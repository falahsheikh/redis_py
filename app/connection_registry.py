import asyncio


class ConnectionRegistry:
    _instance = None

    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._replicas = []
            cls._instance._lock = asyncio.Lock()
        return cls._instance

    async def add_replica(self, writer, replication_id=None, offset=0):
        """
        Add a replica connection with thread-safe registration
        """
        async with self._lock:
            replica = {
                'writer': writer,
                'replication_id': replication_id,
                'offset': offset,
                'registered_at': asyncio.get_event_loop().time()
            }
            self._replicas.append(replica)
            return replica

    async def remove_replica(self, writer):
        """
        Remove a replica connection
        """
        async with self._lock:
            self._replicas = [
                replica for replica in self._replicas
                if replica['writer'] != writer
            ]

    def get_replicas(self):
        """
        Get all registered replicas
        """
        return self._replicas.copy()

    async def update_replica_offset(self, writer, offset):
        """
        Update the offset for a specific replica
        """
        for replica in self._replicas:
            if replica['writer'] == writer:
                replica['offset'] = offset
                break

    async def broadcast(self, data):
        """
        Broadcast data to all registered replicas
        """

        if isinstance(data, str):
            data = data.encode('utf-8')

        async with self._lock:
            # Create tasks for sending to each replica
            tasks = []
            for replica in self._replicas:
                try:
                    replica['writer'].write(data)
                    tasks.append(asyncio.create_task(replica['writer'].drain()))
                except Exception as e:
                    print(f"Error broadcasting to replica: {e}")

            # Wait for all send operations to complete
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    def check_replica_sync(self, offset):
        """
        Check how many replicas are synced to given offset
        """

        return sum(1 for replica in self._replicas if replica['offset'] >= offset)
