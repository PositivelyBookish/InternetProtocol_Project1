"""Pool A/B transfer rates by size for the assignment's HTTP 2 row.

With no inputs, find full experiments in results/ (exclude smoke/short tests).
Explicit inputs may be full A/B CSVs or a combined full A-and-B CSV. Multiple
full experiments are pooled. Summary CSVs cannot supply the individual rates.
Rates are file_bytes * 8 / seconds / 1000, in decimal kilobits per second.
Sample standard deviation (n-1) is the default; --stdev population uses n.
"""

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


EXPECTED = {
    "A_10kB": 1000, "B_10kB": 1000,
    "A_100kB": 100, "B_100kB": 100,
    "A_1MB": 10, "B_1MB": 10,
    "A_10MB": 1, "B_10MB": 1,
}
SIZES = ("10kB", "100kB", "1MB", "10MB")
FILE_BYTES = {"10kB": 10240, "100kB": 102400, "1MB": 1048576, "10MB": 10485760}
REQUIRED = {"filename", "file_bytes", "seconds"}


def read_raw_csv(path):
    """Read comma- or tab-separated raw transfer rows from one file."""
    with path.open(newline="", encoding="utf-8-sig") as source:
        sample = source.read(4096)
        source.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(source, dialect=dialect)
        columns = set(reader.fieldnames or ())
        if not REQUIRED <= columns:
            raise ValueError(
                f"{path}: not a raw-transfer CSV. Required columns: "
                f"{', '.join(sorted(REQUIRED))}. Do not use a summary CSV."
            )
        for line_number, row in enumerate(reader, start=2):
            if None in row or any(row.get(key) is None for key in REQUIRED):
                raise ValueError(f"{path}:{line_number}: malformed or incomplete CSV row")
            if "protocol" in columns and (row["protocol"] or "").strip().lower() not in {"http/2", "http2", "http 2"}:
                raise ValueError(f"{path}:{line_number}: expected HTTP/2 protocol")
            if row["filename"] not in EXPECTED:
                raise ValueError(f"{path}:{line_number}: unexpected file {row['filename']!r}")
            try:
                file_bytes = int(row["file_bytes"])
                seconds = float(row["seconds"])
            except (ValueError, OverflowError) as exc:
                raise ValueError(f"{path}:{line_number}: invalid file_bytes or seconds") from exc
            expected_bytes = FILE_BYTES[row["filename"].split("_")[1]]
            if file_bytes != expected_bytes:
                raise ValueError(f"{path}:{line_number}: {row['filename']} requires "
                                 f"{expected_bytes} file_bytes, found {file_bytes}")
            if not math.isfinite(seconds) or seconds <= 0:
                raise ValueError(f"{path}:{line_number}: seconds must be finite and positive")
            if "hash_ok" in columns and (row["hash_ok"] or "").strip().lower() not in {"true", "1", "yes"}:
                raise ValueError(f"{path}:{line_number}: failed integrity check (hash_ok is not TRUE)")
            kbps = file_bytes * 8 / seconds / 1000
            if not math.isfinite(kbps) or kbps <= 0:
                raise ValueError(f"{path}:{line_number}: calculated throughput must be finite and positive")
            yield row["filename"], kbps


def validate_schedule(path, counts):
    """Each input must contain a full A run, a full B run, or both."""
    if any(name not in EXPECTED for name in counts):
        raise ValueError(f"{path}: unexpected or missing filename")
    prefixes = {name.split("_")[0] for name in counts}
    if not prefixes or not prefixes <= {"A", "B"}:
        raise ValueError(f"{path}: no complete A/B experiment")
    wrong = [f"{name}: expected {expected}, found {counts[name]}"
             for name, expected in EXPECTED.items()
             if name.split("_")[0] in prefixes and counts[name] != expected]
    if wrong:
        raise ValueError(f"{path}: incomplete experiment:\n  " + "\n  ".join(wrong)
                         + "\nUse full raw experiments, not smoke/short tests or summaries.")


def discover_inputs(directory):
    """Select full raw experiments by filename counts; verify data afterwards."""
    selected, excluded = [], []
    for path in sorted(directory.glob("*.csv")):
        if path.name.endswith(".summary.csv"):
            continue
        with path.open(newline="", encoding="utf-8-sig") as source:
            sample = source.read(4096)
            source.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(source, dialect=dialect)
            if not REQUIRED <= set(reader.fieldnames or ()):
                continue
            counts = Counter(row.get("filename") for row in reader)
        try:
            validate_schedule(path, counts)
        except ValueError:
            excluded.append(path)
        else:
            selected.append(path)
    return selected, excluded


def calculate_results(inputs, stdev="sample"):
    if stdev not in {"sample", "population"}:
        raise ValueError("stdev must be sample or population")
    by_file, seen = defaultdict(list), set()
    for path in inputs:
        path = Path(path)
        if path.resolve() in seen:
            raise ValueError(f"Duplicate input: {path}")
        seen.add(path.resolve())
        transfers = list(read_raw_csv(path))
        validate_schedule(path, Counter(name for name, _ in transfers))
        session_path = path.with_suffix(".session.json")
        if session_path.exists():
            session = json.loads(session_path.read_text(encoding="utf-8"))
            if (not isinstance(session, dict) or session.get("completed") is not True
                    or session.get("successful_transfers") != len(transfers)
                    or session.get("planned_transfers") != len(transfers)):
                raise ValueError(f"{session_path}: session is incomplete or its counts do not match the CSV")
        for filename, kbps in transfers:
            by_file[filename].append(kbps)
    if any(not by_file[name] for name in EXPECTED):
        raise ValueError("Supply at least one complete A experiment and one complete B experiment")
    deviation = statistics.stdev if stdev == "sample" else statistics.pstdev
    return [dict(file_size=size,
                 transfers=len(by_file[f"A_{size}"]) + len(by_file[f"B_{size}"]),
                 average_kbps=statistics.fmean(by_file[f"A_{size}"] + by_file[f"B_{size}"]),
                 std_dev_kbps=deviation(by_file[f"A_{size}"] + by_file[f"B_{size}"]))
            for size in SIZES]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="*", type=Path, help="Full raw A/B CSV file(s); default: discover in results/")
    parser.add_argument("--results-dir", type=Path, default=Path("results"),
                        help="Folder searched when no explicit inputs are supplied")
    parser.add_argument("--stdev", choices=("sample", "population"), default="sample",
                        help="Standard deviation denominator: sample n-1 (default), population n")
    parser.add_argument("--output", type=Path, default=Path("http2_table_values.csv"),
                        help="Output summary CSV (default: http2_table_values.csv)")
    parser.add_argument("--row-output", type=Path,
                        help="Sheet-order TSV output (default: output name with .row.tsv suffix)")
    args = parser.parse_args()
    row_output = args.row_output or args.output.with_suffix(".row.tsv")
    if args.output.resolve() == row_output.resolve():
        parser.error("--output and --row-output must be different files")
    for path in (args.output, row_output):
        if path.exists():
            parser.error(f"Refusing to overwrite existing output: {path}")
        if not path.parent.is_dir():
            parser.error(f"Output folder does not exist: {path.parent}")
    try:
        inputs = args.inputs
        if not inputs:
            if not args.results_dir.is_dir():
                raise ValueError(f"Results folder does not exist: {args.results_dir}")
            inputs, excluded = discover_inputs(args.results_dir)
            for path in excluded:
                print(f"Excluded smoke/short/incomplete run: {path}")
        rows = calculate_results(inputs, args.stdev)
    except (OSError, ValueError, csv.Error) as exc:
        parser.error(str(exc))

    with args.output.open("x", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=(
            "protocol", "file_size", "transfers", "average_kbps", "std_dev_kbps"))
        writer.writeheader()
        for row in rows:
            writer.writerow({"protocol": "HTTP/2", **row})

    with row_output.open("x", newline="") as output:
        writer = csv.writer(output, delimiter="\t")
        writer.writerow([f"{size}_{metric}_kbps" for size in SIZES
                         for metric in ("average", "std_dev")])
        writer.writerow([f"{row[field]:.2f}" for row in rows
                         for field in ("average_kbps", "std_dev_kbps")])

    print("HTTP/2 throughput table (kilobits per second)")
    print(f"Inputs: {len(inputs)} full raw CSV(s); A and B measurements pooled by size")
    for path in inputs:
        print(f"  {path}")
        if not path.with_suffix(".session.json").exists():
            print("    Session JSON unavailable; CSV schedule/data checks passed.")
    print(f"Standard deviation: {args.stdev} (denominator {'n-1' if args.stdev == 'sample' else 'n'})")
    print(f"{'File size':<10} {'Transfers':>9} {'Average':>14} {'Std. Dev.':>14}")
    for row in rows:
        print(f"{row['file_size']:<10} {row['transfers']:>9} "
              f"{row['average_kbps']:>14,.2f} {row['std_dev_kbps']:>14,.2f}")
    print(f"\nSaved: {args.output}\nSheet-order values: {row_output}")
    print("Paste the second TSV line into B4:I4 of the supplied sheet:")
    print("\t".join(f"{row[field]:.2f}" for row in rows
                    for field in ("average_kbps", "std_dev_kbps")))


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(1)
