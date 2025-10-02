#!/usr/bin/env python

import argparse
import os

from perfetto import *


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="ftrace file as parser input")
    parser.add_argument(
        "--output", default="trace.json", help="the name of the output file"
    )
    args = parser.parse_args()
    return args


if __name__ == "__main__":
    args = get_args()
    input_f = args.input
    output_f = args.output

    # Check whether the source file exist
    if not os.path.exists(input_f):
        exit(f"Error: {input_f} not exists")

    trace = PerfettoTraceFile(output_f)
    trace.start()
    trace.trace_event_start()

    with open(input_f, "r") as f:
        parse_ftrace(trace, f)

    trace.trace_event_end()
    trace.end()
