"""Regression and integration checks; local timings are not LAN results."""
import csv
import hashlib
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from client import Client
from http2_common import DATA_DIR, FILES, FrameCounter, new_connection


@contextmanager
def server(data_dir=DATA_DIR):
    process = subprocess.Popen(
        [sys.executable, '-B', str(ROOT / 'server.py'), '--host', '127.0.0.1',
         '--port', '0', '--data-dir', str(data_dir)], cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        ready, _, _ = select.select([process.stdout], [], [], 10)
        if not ready:
            raise AssertionError('Server did not start within 10 seconds')
        line = process.stdout.readline()
        if 'listening on' not in line:
            raise AssertionError(f'Server failed to start: {line} {process.stderr.read()}')
        port = int(line.split('127.0.0.1:')[1].split(';')[0])
        yield port, process
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


class HTTP2Tests(unittest.TestCase):
    def run_client(self, port, output, *args):
        return subprocess.run(
            [sys.executable, '-B', str(ROOT / 'client.py'), '--host', '127.0.0.1',
             '--port', str(port), '--output', str(output), *args],
            cwd=str(ROOT), capture_output=True, text=True, timeout=90)

    def test_full_assignment_both_directions_on_one_connection(self):
        with tempfile.TemporaryDirectory() as tmp, server() as (port, process):
            output = Path(tmp) / 'full.csv'
            result = self.run_client(port, output, '--mode', 'suite', '--upload-prefix', 'B')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with output.open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2222)
            expected = {f'{p}_{s}': n for p in ('A', 'B')
                        for s, n in [('10kB', 1000), ('100kB', 100), ('1MB', 10), ('10MB', 1)]}
            self.assertEqual(Counter(r['filename'] for r in rows), expected)
            self.assertEqual([int(r['stream_id']) for r in rows], list(range(1, 4444, 2)))
            digests = {name: hashlib.sha256((DATA_DIR / name).read_bytes()).hexdigest() for name in FILES}
            for row in rows:
                self.assertEqual(row['sha256'], digests[row['filename']])
                self.assertEqual(int(row['file_bytes']), FILES[row['filename']])
                self.assertEqual(row['hash_ok'], 'True')
                self.assertGreater(float(row['seconds']), 0)
                self.assertGreater(float(row['overhead_ratio']), 1)
            session = json.loads(output.with_suffix('.session.json').read_text())
            self.assertTrue(session['completed'])
            self.assertEqual(session['tcp_connections'], 1)
            self.assertEqual(session['successful_transfers'], 2222)
            self.assertEqual(session['client_sent_http2_bytes'],
                             sum(int(r['request_app_bytes']) for r in rows) + session['client_sent_control_bytes'])
            self.assertEqual(session['client_received_http2_bytes'],
                             sum(int(r['response_app_bytes']) for r in rows) + session['client_received_control_bytes'])
            with output.with_suffix('.summary.csv').open() as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 8)
            # A second session exercises continued listening and B downloads.
            second = self.run_client(port, Path(tmp) / 'b.csv', '--prefix', 'B', '--mode', 'suite', '--repeat', '1')
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

    def test_missing_file_is_failure_not_successful_zero_byte_transfer(self):
        with tempfile.TemporaryDirectory() as tmp, server(Path(tmp)) as (port, _):
            output = Path(tmp) / 'missing.csv'
            result = self.run_client(port, output)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('HTTP 404', result.stderr)
            session = json.loads(output.with_suffix('.session.json').read_text())
            self.assertFalse(session['completed'])
            self.assertEqual(session['successful_transfers'], 0)
            with output.open() as handle:
                self.assertEqual(list(csv.DictReader(handle)), [])

    def test_traversal_and_bad_upload_hash_rejected(self):
        with server() as (port, _):
            with socket.create_connection(('127.0.0.1', port), timeout=10) as sock:
                client = Client(sock, f'127.0.0.1:{port}')
                with self.assertRaisesRegex(ValueError, 'HTTP 404'):
                    client.transfer('../server.py', 1)
            with socket.create_connection(('127.0.0.1', port), timeout=10) as sock:
                client = Client(sock, f'127.0.0.1:{port}')
                body = (DATA_DIR / 'B_10kB').read_bytes()
                with self.assertRaisesRegex(ValueError, 'HTTP 422'):
                    client.transfer('B_10kB', 1, body, '0' * 64)

    def test_counter_handles_split_frames_and_preface(self):
        conn = new_connection(True)
        setup = conn.data_to_send()
        conn.send_headers(1, [(':method', 'GET'), (':scheme', 'http'),
                              (':authority', 'localhost'), (':path', '/A_10kB')], end_stream=True)
        request = conn.data_to_send()
        counter = FrameCounter(True)
        for byte in setup + request:
            counter.feed(bytes([byte]))
        self.assertEqual(counter.total, len(setup) + len(request))
        self.assertEqual(counter.control_bytes, len(setup))
        self.assertEqual(counter.file_bytes[1], len(request))
        self.assertEqual(counter.buffer, b'')

    def test_existing_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'existing.csv'
            output.write_text('keep this result')
            result = self.run_client(1, output)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('already exists', result.stderr)
            self.assertEqual(output.read_text(), 'keep this result')


if __name__ == '__main__':
    unittest.main()
