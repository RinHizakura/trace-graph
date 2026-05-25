#!/usr/bin/env python3
"""Convert probe.raw (@TS-framed kprobe_profile snapshots) into a single
general_counter file named ``probe.counter`` inside the output directory.

Each row of kprobe_profile is one kprobe event: ``<name>  <hits>  <misses>``.
The parser keeps only the names listed in the ``@PROBES`` header line emitted
by probe_sampler.sh, and writes one column per probe carrying the cumulative
hit count. On the Perfetto timeline the slope of each track is the call rate
of the probed function.
"""

import argparse
import os


def _iter_samples(file):
    """Read the whole raw file and return (funcs, name2func, samples).

    The @PROBES header lists ``func=kprobe_event_name`` pairs so we can map
    the kprobe_profile rows back to the user-facing function name.
    """
    funcs = []
    name2func = {}
    samples = []
    ts = None
    lines = []
    for raw in file:
        line = raw.rstrip("\n")
        if line.startswith("@PROBES "):
            for token in line.split()[1:]:
                if "=" not in token:
                    continue
                func, name = token.split("=", 1)
                funcs.append(func)
                name2func[name] = func
        elif line.startswith("@TS "):
            if ts is not None:
                samples.append((ts, lines))
            ts = line[4:].strip()
            lines = []
        else:
            lines.append(line)
    if ts is not None:
        samples.append((ts, lines))
    return funcs, name2func, samples


def _parse_kprobe_profile(lines, name2func):
    out = []
    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            continue
        # kprobe_profile reports event names without their group prefix.
        name = parts[0]
        func = name2func.get(name)
        if func is None:
            continue
        try:
            hits = int(parts[1])
        except ValueError:
            continue
        out.append((func, hits))
    return out


class CounterFile:
    """Buffer header + rows in memory; flush as a complete file at the end."""

    def __init__(self, path):
        self.path = path
        self.columns = []
        self.col_index = {}
        self.rows = []

    def set_columns(self, names):
        for name in names:
            if name in self.col_index:
                continue
            self.col_index[name] = len(self.columns)
            self.columns.append(name)

    def write(self, ts, pairs):
        row = [""] * len(self.columns)
        for name, value in pairs:
            idx = self.col_index.get(name)
            if idx is not None:
                row[idx] = str(value)
        self.rows.append((ts, row))

    def flush(self):
        if not self.columns or not self.rows:
            return
        with open(self.path, "w") as f:
            f.write("# " + ",".join(self.columns) + "\n")
            for ts, row in self.rows:
                f.write(f"[{ts}] " + ",".join(row) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True,
                    help="raw probe samples produced by probe_sampler.sh")
    ap.add_argument("-o", "--output-dir", required=True,
                    help="directory to write probe.counter into")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    with open(args.input) as f:
        funcs, name2func, samples = _iter_samples(f)

    cf = CounterFile(os.path.join(args.output_dir, "probe.counter"))
    cf.set_columns(funcs)
    for ts, lines in samples:
        pairs = _parse_kprobe_profile(lines, name2func)
        if pairs:
            cf.write(ts, pairs)
    cf.flush()


if __name__ == "__main__":
    main()
