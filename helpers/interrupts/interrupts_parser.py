#!/usr/bin/env python3
"""Convert interrupts.raw (@TS-framed /proc/interrupts snapshots) into a single
general_counter file named ``interrupts.counter`` inside the output directory.

Each row of /proc/interrupts is one IRQ line: a label, one cumulative count per
CPU, and (for numbered IRQs) a chip/device description. Counts are summed across
CPUs so every IRQ becomes a single counter track; on the Perfetto timeline the
slope of the cumulative count is the interrupt rate.
"""

import argparse
import os
import re


_FNAME_SAFE_RE = re.compile(r"[^A-Za-z0-9_.:%\-]+")


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


def _sanitize(name):
    return _FNAME_SAFE_RE.sub("_", name)


def _parse_interrupts_block(lines):
    """Return list of (irq_name, total_count) pairs from a /proc/interrupts block.

    The first line is the CPU header; its column count tells us how many leading
    integer tokens on each row are per-CPU counts. Counts are summed; for numbered
    IRQs the trailing device name disambiguates the track, while named lines
    (NMI, LOC, ...) keep just their label.
    """
    if not lines:
        return []

    ncpu = sum(1 for tok in lines[0].split() if tok.startswith("CPU"))
    pairs = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 2 or not parts[0].endswith(":"):
            continue
        label = parts[0].rstrip(":")

        total = 0
        idx = 1
        while idx < len(parts) and (ncpu == 0 or idx <= ncpu):
            tok = parts[idx]
            if not tok.lstrip("-").isdigit():
                break
            total += int(tok)
            idx += 1

        desc = parts[idx:]
        if label.isdigit() and desc:
            name = f"{label}_{_sanitize(desc[-1])}"
        else:
            name = _sanitize(label)
        pairs.append((name, total))
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

    def _active_columns(self):
        """Indices of columns whose count rises above its first sample.

        The first snapshot is the reference; an IRQ that never increments over
        the run carries no information, so its track is dropped.
        """
        keep = []
        for i in range(len(self.columns)):
            first = None
            active = False
            for _, row in self.rows:
                cell = row[i]
                if not cell:
                    continue
                val = int(cell)
                if first is None:
                    first = val
                elif val > first:
                    active = True
                    break
            if active:
                keep.append(i)
        return keep

    def flush(self):
        if not self.columns:
            return
        keep = self._active_columns()
        if not keep:
            return
        with open(self.path, "w") as f:
            f.write("# " + ",".join(self.columns[i] for i in keep) + "\n")
            for ts, row in self.rows:
                f.write(f"[{ts}] " + ",".join(row[i] for i in keep) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True, help="raw interrupts samples produced by interrupts_sampler.sh")
    ap.add_argument("-o", "--output-dir", required=True, help="directory to write interrupts.counter into")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    cf = CounterFile(os.path.join(args.output_dir, "interrupts.counter"))
    with open(args.input) as f:
        for ts, lines in _iter_ts_samples(f):
            pairs = _parse_interrupts_block(lines)
            if pairs:
                cf.write(ts, pairs)
    cf.flush()


if __name__ == "__main__":
    main()
