# HTTP/2 file-transfer experiment

Python 3.9+ with `h2==4.3.0`. This implementation uses cleartext HTTP/2 over TCP.

## 1. Setup on both laptops

Copy `server.py`, `client.py`, `http2_common.py`, `requirements.txt`, and `calculate_http2_results.py`. Open a terminal in their folder.

Keep the original files in **`Data files`** (with a space):

- **Computer 1 — server:** `A_10kB`, `A_100kB`, `A_1MB`, `A_10MB`.
- **Computer 2 — client:** `B_10kB`, `B_100kB`, `B_1MB`, `B_10MB`.

Create a separate virtual environment on each laptop. On Mac/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Reactivate the environment when opening a new terminal.

## 2. Start the server on computer 1

Both laptops must be on a LAN that allows communication. Find computer 1's current IP on a Mac:

```bash
ipconfig getifaddr en0
```

If blank, try `ipconfig getifaddr en1`. On Windows, use `ipconfig`; on Linux, use `hostname -I`. Replace `SERVER_IP` below with computer 1's LAN IPv4 address.

Start the server and leave its terminal running:

```bash
python server.py
```

The server listens on TCP port **8080**.

## 3. Test and run on computer 2

First check both directions:

```bash
python client.py --host SERVER_IP --mode smoke --prefix A --upload-prefix B
```

Expected: **`PASS: 6 transfers verified.`** This practice run has its own connection and is excluded from the calculation below.

Then run the full experiment, keeping computer 1's server running:

```bash
python client.py --host SERVER_IP --mode suite --prefix A --upload-prefix B --output results/http2_one_connection.csv
```

The client downloads A using GET, then uploads B using POST, all through **one TCP connection**. The server verifies B, saves one copy of each file in its `Data files` folder (or `--data-dir`), and confirms receipt. Repeated uploads are verified without rewriting the saved copy; an existing file with different contents is rejected with HTTP 409.

| Size | A downloads | B uploads |
| --- | ---: | ---: |
| 10kB | 1,000 | 1,000 |
| 100kB | 100 | 100 |
| 1MB | 10 | 10 |
| 10MB | 1 | 1 |

Expected: **`PASS: 2222 transfers verified.`** In `results/http2_one_connection.session.json`, check `completed: true`, `tcp_connections: 1`, and both transfer counts equal to `2222`.

**Assignment detail:** B is uploaded rather than fetched by computer 1. Confirm that GET + POST is accepted. Running a GET client on each laptop instead uses two TCP connections in total.

## 4. Calculate results on computer 2

Select the new raw CSV explicitly to avoid mixing it with older experiments:

```bash
python calculate_http2_results.py results/http2_one_connection.csv --output http2_one_connection_table.csv
```

Paste the **second line** of `http2_one_connection_table.row.tsv` into **B4:I4** of the results spreadsheet. The values are the average and sample standard deviation for each size, pooling A and B. The rate is `file_bytes × 8 / seconds / 1000` in kbps; actual byte sizes are used.

Keep the raw `.csv`, `.summary.csv`, `.session.json`, and calculated outputs for the report. Use new output filenames for repeat runs; existing files are not overwritten. If no input CSV is supplied, the calculator pools all full experiments in `results/`.

Timing excludes connection setup. GET ends when the response completes; POST ends after the server's verification acknowledgement, including the disk write when a file is first saved. `overhead_ratio = app_bytes / file_bytes` counts file-direction HTTP/2 headers and data frames; shared control frames and TCP/IP overhead are excluded. Match these measurement choices when comparing with HTTP/3.

Press **Ctrl+C** on computer 1 to stop the server when finished.

## Troubleshooting

- **Connection refused/timeout:** check the server, IP, and firewall permission for TCP 8080. Some campus Wi-Fi networks isolate devices.
- **Missing file/404:** check the correct laptop's `Data files` folder and exact filenames.
- **Output already exists:** choose a new `--output` filename.
- **Incomplete experiment:** use a successful full run's raw CSV, not a smoke test or summary.

For additional options, run `python client.py --help` or `python server.py --help`.

Library: [hyper-h2](https://github.com/python-hyper/h2). 
