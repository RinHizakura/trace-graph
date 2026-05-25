#!/usr/bin/env python3
"""Convert diskstats.raw (@TS-framed /proc/diskstats snapshots) into one
general_counter file per observed block device, named
``diskstats_<device>.counter`` inside the output directory.

Each output row contains the per-interval throughput and IOPS derived from
consecutive samples:

    read_bps, write_bps, read_iops, write_iops
"""

import argparse
import os
import re


# Linux always reports diskstats sectors as 512 bytes, regardless of the
# device's physical sector size.
_SECTOR_BYTES = 512

_FNAME_SAFE_RE = re.compile(r"[^A-Za-z0-9_.\-]+")


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


def _parse_diskstats_block(lines):
    """Return dict[device] -> (reads_completed, sectors_read, writes_completed,
    sectors_written) from a /proc/diskstats block."""
    devs = {}
    for raw in lines:
        parts = raw.split()
        # Each diskstats line has at least 14 fields (kernel >= 2.6, no
        # extended discard/flush fields). We only need the first 10.
        if len(parts) < 10:
            continue
        try:
            name = parts[2]
            reads_completed = int(parts[3])
            sectors_read = int(parts[5])
            writes_completed = int(parts[7])
            sectors_written = int(parts[9])
        except (ValueError, IndexError):
            continue
        devs[name] = (reads_completed, sectors_read,
                      writes_completed, sectors_written)
    return devs


class CounterFile:
    """Buffer header + rows in memory; flush as a complete file at the end."""

    def __init__(self, path, columns):
        self.path = path
        self.columns = columns
        self.rows = []

    def write(self, ts, values):
        row = [str(v) for v in values]
        self.rows.append((ts, row))

    def flush(self):
        if not self.rows:
            return
        with open(self.path, "w") as f:
            f.write("# " + ",".join(self.columns) + "\n")
            for ts, row in self.rows:
                f.write(f"[{ts}] " + ",".join(row) + "\n")


def _sanitize(name):
    return _FNAME_SAFE_RE.sub("_", name)


def _format_rate(numerator, dt):
    if dt <= 0:
        return 0.0
    return numerator / dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True,
                    help="raw diskstats samples produced by diskstats_sampler.sh")
    ap.add_argument("-o", "--output-dir", required=True,
                    help="directory to write diskstats_<device>.counter files into")
    ap.add_argument("-d", "--device", action="append", default=[],
                    help="device name to include (repeatable). "
                         "If omitted, all devices with non-zero activity are included.")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    wanted = set(args.device) if args.device else None

    columns = ["read_bps", "write_bps", "read_iops", "write_iops"]
    files = {}
    prev_ts = None
    prev_stats = {}

    with open(args.input) as f:
        for ts_str, lines in _iter_ts_samples(f):
            try:
                ts = float(ts_str)
            except ValueError:
                continue
            stats = _parse_diskstats_block(lines)

            if prev_ts is not None:
                dt = ts - prev_ts
                for dev, cur in stats.items():
                    if wanted is not None and dev not in wanted:
                        continue
                    prev = prev_stats.get(dev)
                    if prev is None:
                        continue
                    d_reads = cur[0] - prev[0]
                    d_read_sectors = cur[1] - prev[1]
                    d_writes = cur[2] - prev[2]
                    d_write_sectors = cur[3] - prev[3]
                    # Skip counter resets (negative deltas).
                    if min(d_reads, d_read_sectors, d_writes, d_write_sectors) < 0:
                        continue
                    if wanted is None and d_reads == 0 and d_writes == 0 \
                            and dev not in files:
                        # Avoid creating files for devices that never moved
                        # during the trace window (e.g. idle loop devices).
                        continue
                    cf = files.get(dev)
                    if cf is None:
                        fname = f"diskstats_{_sanitize(dev)}.counter"
                        cf = CounterFile(os.path.join(args.output_dir, fname),
                                         columns)
                        files[dev] = cf
                    cf.write(ts_str, [
                        f"{_format_rate(d_read_sectors * _SECTOR_BYTES, dt):.2f}",
                        f"{_format_rate(d_write_sectors * _SECTOR_BYTES, dt):.2f}",
                        f"{_format_rate(d_reads, dt):.2f}",
                        f"{_format_rate(d_writes, dt):.2f}",
                    ])

            prev_ts = ts
            prev_stats = stats

    for cf in files.values():
        cf.flush()


if __name__ == "__main__":
    main()
