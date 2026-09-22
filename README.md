# HTTP/2 LAN file-transfer experiment

Python 3.9+ and `h2==4.3.0`. This project uses cleartext HTTP/2 over TCP (prior knowledge, no TLS). It does not implement HTTP/3.

## Setup on both laptops

Copy `server.py`, `client.py`, `http2_common.py`, and `requirements.txt` to both laptops. Copy the original A files to computer 1 and B files to computer 2, in a folder named `Data files` beside the scripts. Do not copy a virtual environment between laptops.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate with `.venv\Scripts\activate` instead. On the original Mac you can use the existing environment with `source venv/bin/activate`.

The screenshot showed computer 1's LAN IP as **10.152.29.191**. Check it again if the network changes. The server binds to `0.0.0.0` by default; clients must use the server's actual IP.

## First test: computer 1 sends A files to computer 2

On computer 1, from the project folder:

```bash
python server.py
```

Leave that terminal running. On computer 2:

```bash
python client.py --host 10.152.29.191 --mode smoke
```

Expected: `PASS: 3 transfers verified`, with three 10,240-byte downloads on streams 1, 3, and 5. The client does not need a local A-file copy: it checks the downloaded size and SHA-256 against the sender's digest. SHA-256 here checks transfer integrity, not authenticity of the original assignment fixtures.

Test all four sizes once before the full run:

```bash
python client.py --host 10.152.29.191 --mode suite --repeat 1
```

## Full A download experiment

On computer 2, with computer 1's server still running:

```bash
python client.py --host 10.152.29.191 --mode suite --prefix A
```

One TCP connection carries all 1,111 requests: 10kB × 1,000; 100kB × 100; 1MB × 10; 10MB × 1. Each request has a new HTTP/2 stream. The client never reconnects inside a run. The server stays running for subsequent client runs.

## Reverse direction and the assignment's connection requirement

The PDF says both computers fetch files and also says to open only one connection. Two independent GET clients require two connections; ordinary HTTP servers do not issue GET requests back to their client on that same connection.

There are two supported testing arrangements:

1. **GET downloads in both directions, one persistent connection per direction.** Run `python server.py` on computer 2, then run this on computer 1 (replace the placeholder with computer 2's real IP):

   ```bash
   python client.py --host FRIEND_LAN_IP --mode suite --prefix B
   ```

   Together with the A run, this gives 2,222 transfers across two TCP sessions. Confirm that the TA accepts one connection per direction before using this arrangement for submission.

2. **Exactly one connection for both directions, using GET downloads plus POST uploads.** Computer 1 runs the server; computer 2 holds the B files and runs:

   ```bash
   python client.py --host 10.152.29.191 --mode suite --prefix A --upload-prefix B
   ```

   This downloads all A files then uploads all B files on the SAME TCP connection, producing 2,222 rows. The server verifies uploads in memory and returns the received length and digest; it never overwrites the source files. This meets the single-connection transfer arrangement but B files are uploaded rather than fetched by computer 1. Confirm that interpretation with the TA. For a short bidirectional check, replace `--mode suite` with `--mode smoke` (six transfers).

These alternatives are explicit because code alone cannot resolve the assignment's wording. Use the same accepted arrangement in HTTP/3.

## Results and measurement definitions

Every invocation creates three uniquely named files under `results/`:

- `*.csv`: one row per successful, verified transfer, including stream ID, exact file bytes, elapsed seconds, MiB/s, encoded application bytes, overhead ratio, SHA-256, and direction.
- `*.summary.csv`: counts, mean time, arithmetic mean throughput, aggregate throughput, and mean overhead ratio for each file/direction.
- `*.session.json`: run completion status, any error, settings, and connection-level byte totals.

`--output results/my_run.csv` chooses a name. Existing outputs are never intentionally overwritten. Each successful row is flushed before the next request, so an interrupted run retains completed records; the session JSON marks the run incomplete. Do not use an incomplete run as a completed assignment result.

Timing uses `time.perf_counter()`:

- GET: immediately before sending the request until receipt/processing of response END_STREAM. Download hashing and CSV writes happen after the timer stops.
- POST: immediately before sending request headers/body until the server's verification acknowledgement ends. This includes server-side hash validation and acknowledgement latency. Do not compare this with a download-only timer without accounting for the difference.
- TCP establishment and HTTP/2 SETTINGS exchange are excluded. Files and sender-side hashes are loaded before transfers; server disk reads are excluded. Logging and result writes occur between transfers.

Throughput is `file_bytes / seconds / 1048576` in **MiB/s**. The supplied names use kB/MB, but their actual sizes are 10,240; 102,400; 1,048,576; and 10,485,760 bytes. `mean_MiB_s` averages per-transfer rates; `aggregate_MiB_s` divides total bytes by total measured seconds. Choose the statistic requested by the results spreadsheet.

`app_bytes` counts serialized HTTP/2 HEADERS, CONTINUATION, and DATA frames in the file's direction, including compressed HPACK header blocks, our hash metadata, and each 9-byte frame header. It is measured from actual bytes, not estimated from decoded headers. `overhead_ratio = app_bytes / file_bytes`; a ratio of 1.02 means 2% overhead. `request_app_bytes` and `response_app_bytes` expose both sides separately.

Shared HTTP/2 control frames/preface are reported separately in session JSON, rather than arbitrarily attributed to individual files. TCP/IP/link headers and TCP retransmissions are excluded. Client totals cover the bytes it sent/read through completion, including its outgoing GOAWAY, not a packet capture of the entire connection shutdown. Document this accounting convention in the report; if the TA requires shared control bytes allocated per file, agree on an allocation rule for both protocols. HTTP/3 UDP packet sizes are not equivalent to these HTTP-layer counters because they also include QUIC overhead.

For a fair HTTP/3 comparison, use the same machines, direction, files, schedule, timing boundaries, validation metadata, preload strategy, and overhead convention. Run protocols separately. Match persistent QUIC connection reuse. Record that this HTTP/2 code is cleartext and HTTP/3 is encrypted. Loopback test timings are correctness checks, not project LAN measurements.

## Troubleshooting

- **Connection refused:** start the server and check the IP and port (default TCP 8080).
- **Timeout:** allow inbound TCP 8080/Python in the server firewall. eduroam may isolate devices; being on the same Wi-Fi name does not guarantee connectivity. If blocked, use a permitted home LAN, hotspot that allows peer traffic, or a lab network.
- **HTTP 404:** the requested file is missing from the server's data folder. Filenames are case-sensitive. Use `--data-dir '/path/to/Data files'` for a different folder.
- **Address in use:** stop the older server with Ctrl+C, or use the same alternate `--port 8081` on server and client.
- **Slow link:** both scripts accept `--timeout 120`; this is a socket inactivity timeout, not a limit on the full suite.

For a single file:

```bash
python client.py --host 10.152.29.191 --file A_10MB --repeat 3
```

`python server.py --help` and `python client.py --help` list the options.

## Validation and implementation notes

```bash
python -B -m unittest discover -s tests -v
```

Tests use temporary localhost servers/results and the original fixtures. They verify all 2,222 GET/POST transfers on a single connection, all B download sizes in a later session, exact sizes and independent hashes, encoded byte accounting across fragmented reads, missing files, path rejection, invalid upload hashes, and output preservation. They require permission to open localhost sockets.

The server bounds each DATA frame by both the peer's current flow-control window and maximum frame size, flushes pending bytes, then processes incoming updates before resuming. Both endpoints acknowledge consumed DATA, advertise a 1 MiB receive window, and use TCP_NODELAY. The server accepts sessions sequentially and intentionally serves only the eight assignment filenames. Transfers are sequential within each session; this is not a concurrent-stream benchmark.

Library: [hyper-h2](https://github.com/python-hyper/h2), [flow-control documentation](https://python-hyper.org/projects/hyper-h2/en/stable/advanced-usage.html). AI assistance was used to revise the implementation, add validation, and write tests/documentation; disclose this in your report as required by the project. The Excel results template was not provided here, so the scripts export CSV summaries rather than editing that workbook.
