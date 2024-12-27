# Redis Server Prototype  

This repository provides a simple implementation of a Redis-like server. It demonstrates the core concepts of Redis, such as key-value storage, concurrency, persistence, and transactions.  

---

## Features  

### Core Functionality  
- **Basic Commands**:  
  - `PING`, `ECHO` for server interaction.  
  - `SET`, `GET`, `TYPE` for key-value operations.  
  - `INCR` for counters.  
- **Streams**:  
  - Commands like `XADD`, `XRANGE`, and `XREAD` are supported.  
- **Transactions**:  
  - Support for `MULTI`, `EXEC`, and `DISCARD` with error handling.  
- **Utilities**:  
  - `KEYS` to list keys.  
  - `INFO` for server details.  
  - `WAIT` for replication acknowledgment.  
- **Persistence**:  
  - Reads RDB files (v3) for key retrieval.  

### Additional Capabilities  
- **Replication**:  
  - Implements master-slave replication with command propagation.  
- **Configuration**:  
  - Customizable port, directory, and RDB file location via CLI options.  

---

## Requirements  

- **Python**: Version 3.9 or higher.  
- **Testing**: Install `pytest` and `pytest-asyncio` to run tests.  

---

## Setup  

### Starting the Server  
Run the following command to start the server:  
```bash  
./run.sh  
```  
The server defaults to port `6379`. Use `--port <custom_port>` to specify another port if Redis is already running.  

### Connecting a Client  
Once the server is active, you can connect using:  
```bash  
echo -ne '*1\r\n$4\r\nping\r\n' | nc localhost <port>  
```  
You can also use any programming language to send Redis protocol-compatible commands.  

---

## Customization  

### Command-Line Options  
- **Port**: Set with `--port`.  
- **RDB File**: Use `--dir` and `--dbfilename` to customize the location and name of the RDB file.  

---

## Learning Resources  

### Networking  
- [Socket Programming](https://docs.python.org/3/howto/sockets.html)  
- [Async Sockets](https://docs.python.org/3/library/asyncio-eventloop.html#working-with-socket-objects-directly)  

### Asynchronous Programming  
- [Event Loop Introduction](https://www.youtube.com/watch?v=8aGhZQkoFbQ)  
- [RealPython Asyncio Guide](https://realpython.com/async-io-python/)  

### Persistence and Parsing  
- [RDB File Format Documentation](https://rdb.fnordig.de/file_format.html)  
- [Redis RDB Tools Reference](https://github.com/sripathikrishnan/redis-rdb-tools/blob/master/rdbtools/parser.py)  

### Redis Protocol  
- [Protocol Specification](https://redis.io/docs/latest/develop/reference/protocol-spec/)  

---
