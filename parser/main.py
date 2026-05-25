#!/usr/bin/env python3

import argparse
import glob
import os

from ftrace_parser import parse_ftrace
from general_counter_parser import parse_general_counter_file
from trace_writer import PerfettoTraceFile


FTRACE_FILE = "ftrace.log"
START_TS_FILE = "start_ts"


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "input", help="output directory produced by tracer.sh"
    )
    parser.add_argument(
        "--output", default="trace.pftrace", help="the name of the output file"
    )
    parser.add_argument(
        "--counter",
        action="append",
        default=[],
        metavar="PATTERN",
    )
    args = parser.parse_args()
    return args


def _read_start_ts(input_dir):
    """Return the warmup cutoff in seconds.

    ``<input>/start_ts`` is written by tracer.sh at the exact moment the
    target command is released; we refuse to parse without it so the
    Perfetto timeline can never accidentally include pre-command warmup
    samples.
    """
    path = os.path.join(input_dir, START_TS_FILE)
    if not os.path.exists(path):
        exit(f"Error: {path} not found — was this directory produced by tracer.sh?")
    with open(path) as f:
        text = f.read().strip()
    if not text:
        exit(f"Error: {path} is empty")
    return float(text)


if __name__ == "__main__":
    args = get_args()
    input_dir = args.input
    output_f = args.output

    if not os.path.isdir(input_dir):
        exit(f"Error: {input_dir} is not a directory")

    ftrace_f = os.path.join(input_dir, FTRACE_FILE)

    counter_fs = []
    for pat in args.counter:
        # Allow glob patterns relative to the input directory.
        joined = pat if os.path.isabs(pat) else os.path.join(input_dir, pat)
        matched = sorted(glob.glob(joined))
        if not matched:
            exit(f"Error: --counter pattern matched nothing: {pat}")
        counter_fs.extend(matched)

    if not os.path.exists(ftrace_f) and not counter_fs:
        exit(f"Error: no known log files found under {input_dir}")

    start_ts = _read_start_ts(input_dir)

    trace = PerfettoTraceFile(output_f)

    if os.path.exists(ftrace_f):
        with open(ftrace_f, "r") as f:
            parse_ftrace(trace, f, start_ts=start_ts)

    for p in counter_fs:
        parse_general_counter_file(trace, p, start_ts=start_ts)

    trace.close()
