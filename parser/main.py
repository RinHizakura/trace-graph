#!/usr/bin/env python3

import argparse
import os

from ftrace_parser import parse_ftrace
from netstat_parser import parse_netstat_log
from ss_parser import parse_ss_log
from trace_writer import PerfettoTraceFile


FTRACE_FILE = "ftrace.log"
SS_FILE = "ss.log"
NETSTAT_FILE = "netstat.log"


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "input", help="output directory produced by tracer.sh"
    )
    parser.add_argument(
        "--output", default="trace.pftrace", help="the name of the output file"
    )
    args = parser.parse_args()
    return args


if __name__ == "__main__":
    args = get_args()
    input_dir = args.input
    output_f = args.output

    if not os.path.isdir(input_dir):
        exit(f"Error: {input_dir} is not a directory")

    ftrace_f = os.path.join(input_dir, FTRACE_FILE)
    ss_f = os.path.join(input_dir, SS_FILE)
    netstat_f = os.path.join(input_dir, NETSTAT_FILE)

    if not any(os.path.exists(p) for p in (ftrace_f, ss_f, netstat_f)):
        exit(f"Error: no known log files found under {input_dir}")

    trace = PerfettoTraceFile(output_f)

    if os.path.exists(ftrace_f):
        with open(ftrace_f, "r") as f:
            parse_ftrace(trace, f)

    if os.path.exists(ss_f):
        with open(ss_f, "r") as f:
            parse_ss_log(trace, f)

    if os.path.exists(netstat_f):
        with open(netstat_f, "r") as f:
            parse_netstat_log(trace, f)

    trace.close()
