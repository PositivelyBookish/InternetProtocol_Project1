"""Cleartext HTTP/2 file server. Run python server.py --help."""
import argparse
import hashlib
import socket
import sys
from pathlib import Path
from h2.events import ConnectionTerminated, DataReceived, RequestReceived, StreamEnded, StreamReset
from h2.exceptions import H2Error
from http2_common import DATA_DIR, FILES, flush, new_connection, queue_body


def load_files(directory):
    files = {}
    for name, expected in FILES.items():
        path = directory / name
        if not path.is_file():
            continue
        body = path.read_bytes()
        if len(body) != expected:
            raise ValueError(f'{path}: expected {expected} bytes, found {len(body)}')
        files[name] = (body, hashlib.sha256(body).hexdigest())
    return files


def serve_connection(sock, files, data_dir=DATA_DIR):
    conn = new_connection(False)
    flush(sock, conn)
    requests, outgoing = {}, {}

    def respond(stream, status, body=b'', extra=()):
        conn.send_headers(stream, [(':status', str(status)),
                                  ('content-length', str(len(body))), *extra], end_stream=not body)
        if body:
            outgoing[stream] = (body, 0)

    while True:
        data = sock.recv(65536)
        if not data:
            return
        for event in conn.receive_data(data):
            if isinstance(event, ConnectionTerminated):
                return
            if isinstance(event, RequestReceived):
                headers = dict(event.headers)
                name = headers.get(':path', '').removeprefix('/')
                method = headers.get(':method')
                error = None
                if name not in FILES:
                    error = 404
                elif method not in ('GET', 'POST'):
                    error = 405
                elif method == 'GET' and name not in files:
                    error = 404
                elif method == 'POST' and headers.get('content-length') != str(FILES[name]):
                    error = 400
                requests[event.stream_id] = dict(headers=headers, name=name, error=error, body=bytearray())
            elif isinstance(event, DataReceived):
                request = requests.get(event.stream_id)
                if request is not None and request['error'] is None:
                    body = request['body']
                    if (request['headers'][':method'] != 'POST'
                            or len(body) + len(event.data) > FILES[request['name']]):
                        request['error'] = 400
                        body.clear()
                    else:
                        body.extend(event.data)
                conn.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
            elif isinstance(event, StreamReset):
                requests.pop(event.stream_id, None)
                outgoing.pop(event.stream_id, None)
            elif isinstance(event, StreamEnded):
                request = requests.pop(event.stream_id, None)
                if request is None:
                    continue
                headers, name = request['headers'], request['name']
                if request['error'] is not None:
                    respond(event.stream_id, request['error'])
                elif headers[':method'] == 'GET':
                    body, digest = files[name]
                    respond(event.stream_id, 200, body, [('x-file-sha256', digest)])
                else:
                    body = request['body']
                    digest = hashlib.sha256(body).hexdigest()
                    if len(body) != FILES[name] or digest != headers.get('x-file-sha256'):
                        respond(event.stream_id, 422)
                    elif name in files and files[name][1] != digest:
                        respond(event.stream_id, 409)  # Preserve a different existing file.
                    else:
                        if name not in files:
                            path = data_dir / name
                            with path.open('xb') as output:
                                output.write(body)
                            files[name] = (bytes(body), digest)
                            print(f'Saved upload: {path}', flush=True)
                        respond(event.stream_id, 200, extra=[
                            ('x-file-sha256', digest), ('x-file-bytes', str(len(body)))])
        for stream, (body, offset) in list(outgoing.items()):
            offset = queue_body(conn, stream, body, offset)
            if offset == len(body):
                del outgoing[stream]
            else:
                outgoing[stream] = (body, offset)
        # Also flush SETTINGS/PING ACKs and upload WINDOW_UPDATE frames.
        flush(sock, conn)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--data-dir', type=Path, default=DATA_DIR)
    parser.add_argument('--timeout', type=float, default=60, help='Socket idle timeout in seconds')
    parser.add_argument('--once', action='store_true', help='Exit after one client session')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    files = load_files(args.data_dir)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((args.host, args.port))
        listener.listen(5)
        print(f'HTTP/2 listening on {args.host}:{listener.getsockname()[1]}; '
              f'{len(files)} files loaded', flush=True)
        while True:
            sock, address = listener.accept()
            with sock:
                sock.settimeout(args.timeout)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                print(f'Client connected: {address}', flush=True)
                try:
                    serve_connection(sock, files, args.data_dir)
                except (OSError, H2Error, ValueError) as exc:
                    print(f'Session failed: {exc}', file=sys.stderr, flush=True)
            print('Session closed', flush=True)
            if args.once:
                break


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nServer stopped')
    except (OSError, ValueError) as exc:
        sys.exit(f'Server error: {exc}')
