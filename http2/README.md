# HTTP/2 LAN file-transfer experiment

Python 3.9+ and `h2==4.3.0`. This project uses cleartext HTTP/2 over TCP (prior knowledge, no TLS). It does not implement HTTP/3.

## How A and B travel through one connection

Computer 1 (your laptop) runs the server and holds the A files. Computer 2 (the other laptop) runs the client and holds the B files. Their roles stay the same throughout the experiment.

| Action | Who starts it? | What travels between the laptops? |
| --- | --- | --- |
| Download A using GET | Computer 2's client asks for an A file | Computer 1 sends the A file to computer 2 |
| Upload B using POST | Computer 2's client sends a B file | Computer 2 sends the B file to computer 1; computer 1 confirms receipt |

The client opens one TCP connection, downloads all A files, then uploads all B files through that same connection. Each transfer uses a new HTTP/2 stream inside the connection. You do not type individual GET or POST requests: the client script sends them automatically.

The server does not request B. It receives B, checks its size and SHA-256 hash, and acknowledges the upload. Uploaded B files are verified in memory and are not saved to disk. Downloads are also verified in memory rather than saved as separate copies. The original source files are unchanged.

**Assignment wording:** the instructions say both computers should *fetch* files. This arrangement transfers files in both directions over exactly one TCP connection, but computer 1 receives B through an upload. Confirm that GET + POST is accepted for submission. If the intended requirement is one connection per direction with both computers fetching, use the alternative near the end of this README. Use the same accepted arrangement for HTTP/3, which uses a QUIC connection over UDP rather than TCP.

## Step 1: prepare both laptops

Use Python 3.9 or newer. Copy these files to the HTTP/2 project folder on both laptops:

- `server.py`
- `client.py`
- `http2_common.py`
- `requirements.txt`
- `calculate_http2_results.py`

Beside the scripts, create a folder named **`Data files`**, including the space. Keep the original filenames without adding an extension:

| Computer 1: server | Computer 2: client |
| --- | --- |
| `Data files/A_10kB` | `Data files/B_10kB` |
| `Data files/A_100kB` | `Data files/B_100kB` |
| `Data files/A_1MB` | `Data files/B_1MB` |
| `Data files/A_10MB` | `Data files/B_10MB` |

Open a terminal in the HTTP/2 folder on each laptop, where `client.py` and `server.py` are located. If necessary, change to that folder first, replacing the example path with its actual location:

```bash
cd "/path/to/http2"
```

On **both laptops**, create a local virtual environment and install the dependency. Do not copy a virtual environment from one laptop to the other.

Mac/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, use Command Prompt and run `.venv\Scripts\activate.bat`, then the install command. In a new terminal, return to the project folder and activate the existing environment again; you do not need to recreate it.

## Step 2: find computer 1's LAN IP address

Connect both laptops to a LAN that allows them to communicate. On **computer 1**, find its current local IPv4 address.

Mac (Wi-Fi commonly uses `en0`):

```bash
ipconfig getifaddr en0
```

If that prints nothing, try `ipconfig getifaddr en1`, or check the active network's TCP/IP settings. On Windows, run `ipconfig` and read the IPv4 address of the active Wi-Fi/Ethernet adapter. On Linux, run `hostname -I` and select the active LAN address.

In every client command below, replace **`SERVER_IP`** with that address. Do not use `localhost`, `127.0.0.1`, or `0.0.0.0` to reach the other laptop. An IP from an older experiment may have changed.

## Step 3: start the server on computer 1

With its virtual environment active, run on **computer 1**:

```bash
python server.py
```

With only the four A files present, expect:

```text
HTTP/2 listening on 0.0.0.0:8080; 4 files loaded
```

Leave this terminal running throughout the checks and experiment. Allow Python/inbound TCP port 8080 in the server's firewall if prompted. For this arrangement, only computer 1 runs the server and only computer 2 runs the client.

## Step 4: check both directions on computer 2

With its virtual environment active, run on **computer 2**, replacing `SERVER_IP`:

```bash
python client.py --host SERVER_IP --mode smoke --prefix A --upload-prefix B
```

Expected: `PASS: 6 transfers verified.` This checks three A_10kB downloads and three B_10kB uploads. To check all four sizes once in each direction, also run:

```bash
python client.py --host SERVER_IP --mode suite --repeat 1 --prefix A --upload-prefix B
```

Expected: `PASS: 8 transfers verified.` Each check opens and closes its own TCP connection. These are preliminary checks, not part of the full experiment. Keep their measurements separate from the final results.

## Step 5: run the full experiment on computer 2

Keep computer 1's server running. On **computer 2**, run:

```bash
python client.py --host SERVER_IP --mode suite --prefix A --upload-prefix B --output results/http2_one_connection.csv
```

The script performs these transfers automatically:

| File size | A downloads: computer 1 → computer 2 | B uploads: computer 2 → computer 1 |
| --- | ---: | ---: |
| 10kB | 1,000 | 1,000 |
| 100kB | 100 | 100 |
| 1MB | 10 | 10 |
| 10MB | 1 | 1 |
| **Total** | **1,111** | **1,111** |

All **2,222 transfers** in this invocation use one TCP connection. The client never reconnects within a run. Do not start another client for the reverse direction: this command already includes both directions.

After success, expect `PASS: 2222 transfers verified.` The following files are saved on **computer 2**:

- `results/http2_one_connection.csv`: all individual transfer measurements.
- `results/http2_one_connection.summary.csv`: summaries by file and direction.
- `results/http2_one_connection.session.json`: run completion and connection information.

Open the session JSON and check that `completed` is `true`, `tcp_connections` is `1`, and both `planned_transfers` and `successful_transfers` are `2222`. A failed or interrupted run is not a completed experiment.

For another full run, use a fresh name such as `results/http2_one_connection_run2.csv`. Existing files are preserved; the client refuses to overwrite them.

## Step 6: calculate the spreadsheet values on computer 2

Select the new raw CSV explicitly so that older experiments are not mixed into this result:

```bash
python calculate_http2_results.py results/http2_one_connection.csv --output http2_one_connection_table.csv
```

This creates `http2_one_connection_table.csv` and `http2_one_connection_table.row.tsv` in the project folder. Paste the **second line** of the TSV into **B4:I4**, the HTTP 2 throughput row of the supplied spreadsheet. The eight values are the average and standard deviation for 10kB, 100kB, 1MB, and 10MB, in that order.

Keep all three experiment files with the calculated outputs, and copy them back to your laptop for the report. For a later run, give the calculator the matching raw CSV and a new output filename.

## Step 7: stop the server

After the client has finished, press **Ctrl+C** in computer 1's server terminal. Run `deactivate` in each terminal when you are finished using the virtual environment.

## Results and measurement definitions

By default, every client invocation creates three uniquely named files under `results/`:

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

## How the throughput calculation works

The calculator uses the standard library only. The explicit input command in
step 6 selects your new experiment. It pools **every individual A and B transfer
rate of each size** across the selected full experiments. One full bidirectional
run gives 2,000 rates for 10kB, 200 for 100kB, 20 for 1MB, and 2 for 10MB.

To combine repeated experiments made with the same setup, list their raw CSVs:

```bash
python calculate_http2_results.py results/http2_one_connection.csv results/http2_one_connection_run2.csv --output http2_combined_table.csv
```

Additional full runs add their measurements to the corresponding size pools.
Do not combine the old two-connection experiments with the new one-connection
experiment when reporting the performance of the new setup.

If no input CSV is supplied, the calculator discovers full raw experiments in
`results/`, excludes smoke/short tests and summaries, and pools all discovered
full runs. Use that option only when you intend to combine those experiments:

```bash
python calculate_http2_results.py --output http2_all_experiments_table.csv
```

For each transfer, `rate_kbps = file_bytes * 8 / seconds / 1000`. Use actual byte
sizes, not the nominal filename, and keep full precision until final display.
For each size, calculate the arithmetic mean of its pooled rates and their standard
deviation. This is an average of transfer rates, not total bytes divided by total
time, and standard deviations must be calculated from the pooled rates rather than
averaged from separate A/B summaries.

The default standard deviation is **sample** (`n-1`, equivalent to Google Sheets
`STDEV.S`); it reproduces the supplied screenshot's values. The sheet does not
explicitly specify sample versus population. If population deviation is required,
use `--stdev population` (`n`, equivalent to `STDEV.P`).

The output CSV has four rows with full precision and transfer counts. The matching
`.row.tsv` contains eight numbers rounded to two decimal places in the sheet's
column order. Paste its **second line** into **B4:I4**. If `--output` is omitted,
the names default to `http2_table_values.csv` and `http2_table_values.row.tsv`.
Use a new `--output` filename to recalculate without overwriting earlier output.

The script rejects wrong byte sizes, nonfinite/nonpositive times or rates, failed
integrity flags, incomplete schedules, duplicate input paths, and inconsistent or
incomplete session JSON when present. Missing session JSON is reported, but a full
validated raw CSV is still usable for this throughput calculation.

## Alternative: both laptops fetch files, one connection per direction

Use this arrangement only if the TA confirms that one connection **per direction**
is intended. It uses two TCP connections in total and is separate from steps 3–6.

With the environments active and files arranged as in step 1:

1. On computer 1, start `python server.py`.
2. On computer 2, download A through one persistent connection:

   ```bash
   python client.py --host SERVER_IP --mode suite --prefix A --output results/http2_A_downloads.csv
   ```

3. After the A run finishes, start `python server.py` on computer 2 in a separate terminal with its environment active.
4. On computer 1, open a separate terminal, activate its environment, and download B. Replace `COMPUTER_2_IP` with computer 2's LAN address:

   ```bash
   python client.py --host COMPUTER_2_IP --mode suite --prefix B --output results/http2_B_downloads.csv
   ```

Each client run should report `PASS: 1111 transfers verified.` Copy the A run's raw
CSV and matching session JSON from computer 2 into computer 1's `results/` folder
(with its summary for your records). Calculate both directions on computer 1:

```bash
python calculate_http2_results.py results/http2_A_downloads.csv results/http2_B_downloads.csv --output http2_two_connections_table.csv
```

Stop both servers with Ctrl+C when finished. Ordinary HTTP/2 request handling does
not let the server issue a GET request back to its client on the existing
connection; starting another GET client is a separate TCP session.

## Troubleshooting

- **Connection refused:** start the server and check the IP and port (default TCP 8080).
- **Timeout:** allow inbound TCP 8080/Python in the server firewall. eduroam may isolate devices; being on the same Wi-Fi name does not guarantee connectivity. If blocked, use a permitted home LAN, hotspot that allows peer traffic, or a lab network.
- **HTTP 404:** the requested file is missing from the server's data folder. Filenames are case-sensitive. Use `--data-dir '/path/to/Data files'` for a different folder.
- **Address in use:** stop the older server with Ctrl+C, or use the same alternate `--port 8081` on server and client.
- **Slow link:** both scripts accept `--timeout 120`; this is a socket inactivity timeout, not a limit on the full suite.
- **Output already exists:** choose a new `--output` filename for the client or calculator. Preserve the earlier run.
- **B upload file not found:** the B files must be in computer 2's `Data files` folder, with the exact names listed in step 1.
- **Calculator rejects an incomplete experiment:** use a successfully completed full suite, not a smoke test, an interrupted run, or a summary CSV.

For a single file:

```bash
python client.py --host SERVER_IP --file A_10MB --repeat 3
```

`python server.py --help` and `python client.py --help` list the options.

## Validation and implementation notes

```bash
python -B -m unittest discover -s tests -v
```

Tests use temporary localhost servers/results and the original fixtures. They verify all 2,222 GET/POST transfers on a single connection, all B download sizes in a later session, exact sizes and independent hashes, encoded byte accounting across fragmented reads, missing files, path rejection, invalid upload hashes, and output preservation. They require permission to open localhost sockets.

The server bounds each DATA frame by both the peer's current flow-control window and maximum frame size, flushes pending bytes, then processes incoming updates before resuming. Both endpoints acknowledge consumed DATA, advertise a 1 MiB receive window, and use TCP_NODELAY. The server accepts sessions sequentially and intentionally serves only the eight assignment filenames. Transfers are sequential within each session; this is not a concurrent-stream benchmark.

Library: [hyper-h2](https://github.com/python-hyper/h2), [flow-control documentation](https://python-hyper.org/projects/hyper-h2/en/stable/advanced-usage.html). AI assistance was used to revise the implementation, add validation, and write tests/documentation; disclose this in your report as required by the project. The Excel results template was not provided here, so the scripts export CSV summaries rather than editing that workbook.
