# HTTP/3 File Transfer

This project implements HTTP/3 file transfers using **QUIC/UDP** and the Python [`aioquic`](https://github.com/aiortc/aioquic) library.

## Requirements

Make sure Python is installed, then install `aioquic` in terminal (make sure file path is correct):

```bash
python -m pip install aioquic
```
## Update the Client IP Address

Before running the client, update the **server IP address in `client.py`** to match the current IP address of the computer running `server.py`.

If both computers are connected through shared Wi-Fi, the server's IP address may change when connecting to a different network. Make sure both computers are on the **same Wi-Fi network** and update the IP address in `client.py` accordingly.

```python
SERVER_IP = "YOUR_SERVER_IP"
```

## How to Run

### 1. Start the Server

Open a terminal in the project directory and run:

```bash
python server.py
```

The server will start and wait for HTTP/3 client connections.

### 2. Start the Client

Second computer will open a terminal in the same project directory and run:

```bash
python client.py
```

The client will connect to the HTTP/3 server and perform the file transfers.

> **Note:** The server must be running before starting the client.

## Files

| File                | Description                                                     |
| ------------------- | --------------------------------------------------------------- |
| `server.py`         | Starts the HTTP/3 server and handles incoming file requests.    |
| `client.py`         | Connects to the server and performs the HTTP/3 file transfers.  |
| `HTTP3_results.csv` | Contains the HTTP/3 transfer results.                           |
| `throughput.csv`    | Contains the throughput measurements from the HTTP/3 transfers. |

## Project Structure

```text
http3/
├── server.py
├── client.py
├── HTTP3_results.csv
├── throughput.csv
└── README.md
```

## Protocol

* **Protocol:** HTTP/3
* **Transport:** QUIC
* **Underlying Transport:** UDP
* **Python Library:** `aioquic`
