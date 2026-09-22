"""Run verified HTTP/2 file transfers over one persistent TCP connection."""
import argparse
import csv
import hashlib
import json
import socket
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from h2.events import (ConnectionTerminated, DataReceived, RemoteSettingsChanged,
                       ResponseReceived, SettingsAcknowledged, StreamEnded, StreamReset)
from h2.exceptions import H2Error
from http2_common import (DATA_DIR, FILES, SCHEDULE, WINDOW, FrameCounter, flush,
                         new_connection, queue_body)

FIELDS = ['protocol', 'direction', 'method', 'filename', 'trial', 'stream_id',
          'file_bytes', 'seconds', 'throughput_MiB_s', 'app_bytes', 'overhead_ratio',
          'request_app_bytes', 'response_app_bytes', 'sha256', 'hash_ok']


class Client:
    def __init__(self, sock, authority):
        self.sock, self.authority = sock, authority
        self.conn = new_connection(True)
        self.sent = FrameCounter(has_preface=True)
        self.received = FrameCounter()
        self.flush()
        # Two outgoing SETTINGS frames: initial settings and the larger window.
        # Finish setup before measuring the first request.
        remote_seen, acknowledgements = False, 0
        while not remote_seen or acknowledgements < 2:
            for event in self.receive():
                if isinstance(event, RemoteSettingsChanged):
                    remote_seen = True
                elif isinstance(event, SettingsAcknowledged):
                    acknowledgements += 1
            self.flush()

    def flush(self):
        flush(self.sock, self.conn, self.sent)

    def receive(self):
        data = self.sock.recv(65536)
        if not data:
            raise ConnectionError('Server closed the connection before completion')
        self.received.feed(data)
        events = self.conn.receive_data(data)
        for event in events:
            if isinstance(event, ConnectionTerminated):
                raise ConnectionError(f'Server sent GOAWAY: {event.error_code}')
            if isinstance(event, StreamReset):
                raise ConnectionError(f'Stream {event.stream_id} reset: {event.error_code}')
        return events

    def transfer(self, filename, trial, upload=None, upload_hash=None):
        stream = self.conn.get_next_available_stream_id()
        method = 'POST' if upload is not None else 'GET'
        headers = [(':method', method), (':scheme', 'http'),
                   (':authority', self.authority), (':path', f'/{filename}')]
        if upload is not None:
            headers.extend([('content-length', str(len(upload))), ('x-file-sha256', upload_hash)])
        self.conn.send_headers(stream, headers, end_stream=upload is None)
        body, response = bytearray(), {}
        offset, finished = 0, None
        start = time.perf_counter()
        while finished is None:
            if upload is not None and offset < len(upload):
                offset = queue_body(self.conn, stream, upload, offset)
            self.flush()
            for event in self.receive():
                if getattr(event, 'stream_id', stream) != stream:
                    continue
                if isinstance(event, ResponseReceived):
                    response = dict(event.headers)
                    if response.get(':status') != '200':
                        raise ValueError(f"{filename}: server returned HTTP {response.get(':status')}")
                elif isinstance(event, DataReceived):
                    body.extend(event.data)
                    if len(body) > FILES[filename]:
                        raise ValueError(f'{filename}: response exceeds expected file size')
                    self.conn.acknowledge_received_data(event.flow_controlled_length, stream)
                elif isinstance(event, StreamEnded):
                    finished = time.perf_counter()
        self.flush()
        seconds = finished - start
        if response.get(':status') != '200':
            raise ValueError(f'{filename}: no successful response')
        if upload is None:
            digest = hashlib.sha256(body).hexdigest()
            size, length = len(body), response.get('content-length')
        else:
            digest, size = upload_hash, len(upload)
            length = response.get('x-file-bytes')
            if offset != size:
                raise ValueError(f'{filename}: server ended upload early')
        if size != FILES[filename] or length != str(size):
            raise ValueError(f'{filename}: expected {FILES[filename]} bytes; got {size}, header {length}')
        if digest != response.get('x-file-sha256'):
            raise ValueError(f'{filename}: SHA-256 validation failed')
        request_bytes = self.sent.file_bytes[stream]
        response_bytes = self.received.file_bytes[stream]
        app_bytes = response_bytes if upload is None else request_bytes
        return dict(zip(FIELDS, [
            'HTTP/2', 'server_to_client' if upload is None else 'client_to_server',
            method, filename, trial, stream, size, seconds,
            size / seconds / 1048576, app_bytes, app_bytes / size,
            request_bytes, response_bytes, digest, True,
        ]))


def write_summary(path, rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['direction'], row['filename'])].append(row)
    fields = ['direction', 'filename', 'transfers', 'mean_seconds', 'mean_MiB_s',
              'aggregate_MiB_s', 'mean_overhead_ratio']
    with path.open('w', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for (direction, filename), group in groups.items():
            writer.writerow(dict(zip(fields, [
                direction, filename, len(group), statistics.mean(r['seconds'] for r in group),
                statistics.mean(r['throughput_MiB_s'] for r in group),
                sum(r['file_bytes'] for r in group) / sum(r['seconds'] for r in group) / 1048576,
                statistics.mean(r['overhead_ratio'] for r in group),
            ])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, help='Server LAN IP, e.g. 10.152.29.191')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--prefix', choices=('A', 'B'), default='A', help='Files to download')
    parser.add_argument('--mode', choices=('smoke', 'suite'), default='smoke',
                        help='Smoke: three 10kB downloads; suite: assignment schedule')
    parser.add_argument('--file', choices=sorted(FILES), help='Test only this file')
    parser.add_argument('--repeat', type=int, help='Override repetition count for each selected file')
    parser.add_argument('--upload-prefix', choices=('A', 'B'),
                        help='Also upload this file set on the SAME connection (see README)')
    parser.add_argument('--data-dir', type=Path, default=DATA_DIR)
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--output', type=Path, help='New CSV path; refuses to overwrite')
    args = parser.parse_args()
    if args.timeout <= 0 or (args.repeat is not None and args.repeat <= 0):
        parser.error('--timeout and --repeat must be positive')
    if args.file and args.upload_prefix:
        parser.error('--file cannot be combined with --upload-prefix')
    schedule = SCHEDULE if args.mode == 'suite' else (('10kB', 3),)
    downloads = ([(args.file, args.repeat or 1)] if args.file else
                 [(f'{args.prefix}_{size}', args.repeat or count) for size, count in schedule])
    jobs = [(name, count, None, None) for name, count in downloads]
    if args.upload_prefix:
        for size, count in schedule:
            name = f'{args.upload_prefix}_{size}'
            body = (args.data_dir / name).read_bytes()
            if len(body) != FILES[name]:
                raise ValueError(f'{name}: wrong local file size')
            jobs.append((name, args.repeat or count, body, hashlib.sha256(body).hexdigest()))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    output = args.output or Path('results') / f'http2_{args.prefix}_{stamp}.csv'
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = output.with_suffix('.summary.csv')
    session_path = output.with_suffix('.session.json')
    if any(p.exists() for p in (output, summary, session_path)):
        raise ValueError(f'Output already exists: choose a new --output path ({output})')
    rows, client = [], None
    session = dict(server=f'{args.host}:{args.port}', started_utc=stamp, mode=args.mode,
                   receive_window_bytes=WINDOW, planned_transfers=sum(j[1] for j in jobs),
                   completed=False,
                   timing='GET: request to response end; POST: request to verified server acknowledgement',
                   app_bytes_definition='File-direction HEADERS/CONTINUATION/DATA including 9-byte frame headers; excludes control frames and transport overhead')
    try:
        with output.open('x', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            handle.flush()
            with socket.create_connection((args.host, args.port), timeout=args.timeout) as sock:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                client = Client(sock, f'{args.host}:{args.port}')
                print(f'Connected to {args.host}:{args.port}; one TCP connection for all transfers')
                for name, count, body, digest in jobs:
                    print(f"{'POST' if body is not None else 'GET'} {name} x {count}", flush=True)
                    for trial in range(1, count + 1):
                        row = client.transfer(name, trial, body, digest)
                        writer.writerow(row)
                        handle.flush()
                        rows.append(row)
                    print(f'  Verified {count}/{count}; mean '
                          f"{statistics.mean(r['throughput_MiB_s'] for r in rows[-count:]):.3f} MiB/s")
                client.conn.close_connection()
                client.flush()
                session['completed'] = True
    except (Exception, KeyboardInterrupt) as exc:
        session['error'] = str(exc) or type(exc).__name__
        raise
    finally:
        session['successful_transfers'] = len(rows)
        if client is not None:
            session.update(tcp_connections=1, client_sent_http2_bytes=client.sent.total,
                           client_received_http2_bytes=client.received.total,
                           client_sent_control_bytes=client.sent.control_bytes,
                           client_received_control_bytes=client.received.control_bytes)
        session_path.write_text(json.dumps(session, indent=2) + '\n')
        write_summary(summary, rows)
    print(f'PASS: {len(rows)} transfers verified. Results: {output}\nSummary: {summary}')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit('Interrupted; completed transfers remain in the CSV')
    except (OSError, H2Error, ValueError) as exc:
        sys.exit(f'Test failed: {exc}\nCheck the server, LAN IP, TCP port, and firewall. '
                 'Campus Wi-Fi may block communication between devices.')
