#!/usr/bin/env python3
"""Convert netstat.raw (@TS-framed /proc/net/netstat snapshots) into a single
general_counter file named ``netstat.counter`` inside the output directory.
"""

import argparse
import os


def _iter_ts_samples(file):
    """Yield (ts, lines) for each '@TS <seconds>'-delimited block."""
    ts = None
    lines = []
    for raw in file:
        line = raw.rstrip("\n")
        if line.startswith("@TS "):
            if ts is not None:
                yield ts, lines
            ts = line[4:].strip()
            lines = []
        else:
            lines.append(line)
    if ts is not None:
        yield ts, lines


def _parse_netstat_block(lines):
    """Return list of (section.name, value) pairs in /proc/net/netstat order."""
    pairs = []
    headers = {}
    for line in lines:
        parts = line.split()
        if len(parts) < 2 or not parts[0].endswith(":"):
            continue
        prefix = parts[0]
        if prefix not in headers:
            headers[prefix] = parts[1:]
            continue
        names = headers.pop(prefix)
        values = parts[1:]
        section = prefix.rstrip(":")
        for name, raw in zip(names, values):
            try:
                pairs.append((f"{section}.{name}", int(raw)))
            except ValueError:
                continue
    return pairs


class CounterFile:
    """Buffer header + rows in memory; flush as a complete file at the end."""

    def __init__(self, path):
        self.path = path
        self.columns = []
        self.col_index = {}
        self.rows = []

    def write(self, ts, pairs):
        if not self.columns:
            for name, _ in pairs:
                if name in self.col_index:
                    continue
                self.col_index[name] = len(self.columns)
                self.columns.append(name)
        row = [""] * len(self.columns)
        for name, value in pairs:
            idx = self.col_index.get(name)
            if idx is not None:
                row[idx] = str(value)
        self.rows.append((ts, row))

    def flush(self):
        if not self.columns:
            return
        with open(self.path, "w") as f:
            f.write("# " + ",".join(self.columns) + "\n")
            for ts, row in self.rows:
                f.write(f"[{ts}] " + ",".join(row) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True, help="raw netstat samples produced by netstat_sampler.sh")
    ap.add_argument("-o", "--output-dir", required=True, help="directory to write netstat.counter into")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    cf = CounterFile(os.path.join(args.output_dir, "netstat.counter"))
    with open(args.input) as f:
        for ts, lines in _iter_ts_samples(f):
            pairs = _parse_netstat_block(lines)
            if pairs:
                cf.write(ts, pairs)
    cf.flush()


if __name__ == "__main__":
    main()
