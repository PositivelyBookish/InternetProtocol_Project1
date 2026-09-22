"""Shared settings and framing helpers for the HTTP/2 LAN experiment."""
from collections import defaultdict
from pathlib import Path
from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.settings import SettingCodes

DATA_DIR = Path(__file__).resolve().parent / 'Data files'
SCHEDULE = (('10kB', 1000), ('100kB', 100), ('1MB', 10), ('10MB', 1))
SIZES = {'10kB': 10240, '100kB': 102400, '1MB': 1048576, '10MB': 10485760}
FILES = {f'{prefix}_{size}': length for prefix in ('A', 'B') for size, length in SIZES.items()}
WINDOW = 1024 * 1024


class FrameCounter:
    """Count serialized frames correctly across partial socket reads.

    File bytes include HEADERS, CONTINUATION, DATA and their 9-byte headers.
    Other frames and the client preface are counted separately.
    """
    def __init__(self, has_preface=False):
        self.buffer = bytearray()
        self.preface_remaining = 24 if has_preface else 0
        self.total = 0
        self.file_bytes = defaultdict(int)
        self.control_bytes = 0

    def feed(self, data):
        self.total += len(data)
        if self.preface_remaining:
            count = min(len(data), self.preface_remaining)
            self.preface_remaining -= count
            self.control_bytes += count
            data = data[count:]
        self.buffer.extend(data)
        offset = 0
        while len(self.buffer) - offset >= 9:
            length = int.from_bytes(self.buffer[offset:offset + 3], 'big') + 9
            if len(self.buffer) - offset < length:
                break
            frame_type = self.buffer[offset + 3]
            stream = int.from_bytes(self.buffer[offset + 5:offset + 9], 'big') & 0x7fffffff
            if stream and frame_type in (0, 1, 9):
                self.file_bytes[stream] += length
            else:
                self.control_bytes += length
            offset += length
        del self.buffer[:offset]


def new_connection(client_side):
    conn = H2Connection(config=H2Configuration(client_side=client_side, header_encoding='utf-8'))
    conn.initiate_connection()
    conn.update_settings({SettingCodes.INITIAL_WINDOW_SIZE: WINDOW})
    conn.increment_flow_control_window(WINDOW - 65535)
    return conn


def flush(sock, conn, counter=None):
    data = conn.data_to_send()
    if data:
        sock.sendall(data)
        if counter is not None:
            counter.feed(data)


def queue_body(conn, stream, body, offset):
    """Queue only what the peer permits; caller flushes, receives, and retries."""
    while offset < len(body):
        count = min(conn.local_flow_control_window(stream),
                    conn.max_outbound_frame_size, len(body) - offset)
        if count <= 0:
            break
        end = offset + count
        conn.send_data(stream, body[offset:end], end_stream=end == len(body))
        offset = end
    return offset
