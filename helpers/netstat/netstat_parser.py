#!/usr/bin/env python3
"""Convert netstat.raw (@TS-framed /proc/net/netstat snapshots) into a single
general_counter file named ``netstat.counter`` inside the output directory.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from counter_file import CounterFile, iter_ts_samples


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True, help="raw netstat samples produced by netstat_sampler.sh")
    ap.add_argument("-o", "--output-dir", required=True, help="directory to write netstat.counter into")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    cf = CounterFile(os.path.join(args.output_dir, "netstat.counter"))
    with open(args.input) as f:
        for ts, lines in iter_ts_samples(f):
            pairs = _parse_netstat_block(lines)
            if pairs:
                cf.write(ts, pairs)
    cf.flush()


if __name__ == "__main__":
    main()
