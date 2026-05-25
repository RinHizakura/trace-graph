#!/usr/bin/env python3
"""Convert ss.raw (@TS-framed `ss -tin` snapshots) into one general_counter file
per observed TCP connection, named ``ss_<local>-<peer>.counter`` inside the
output directory.
"""

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from counter_file import CounterFile, iter_ts_samples


_SS_NUM_RE = re.compile(r"^([-+]?\d+(?:\.\d+)?)([A-Za-z%]*)$")
_SS_PAIRED_KEYS = {"send", "pacing_rate", "delivery_rate"}
_FNAME_SAFE_RE = re.compile(r"[^A-Za-z0-9_.:%\-\[\]]+")


def _parse_ss_number(s):
    m = _SS_NUM_RE.match(s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _parse_ss_block(lines):
    """Return dict[conn_key] -> list[(metric, value)] from a `ss -tin` block."""
    conns = {}
    conn_key = None
    for raw in lines:
        if not raw.strip():
            continue
        if not raw[0].isspace():
            parts = raw.split()
            if not parts or parts[0] == "State" or len(parts) < 5:
                conn_key = None
                continue
            conn_key = f"{parts[3]}-{parts[4]}"
            continue

        if conn_key is None:
            continue

        metrics = []
        tokens = raw.split()
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if ":" in tok:
                key, _, value = tok.partition(":")
                if key and value:
                    sub = re.split(r"[/,]", value)
                    for idx, part in enumerate(sub):
                        num = _parse_ss_number(part)
                        if num is None:
                            continue
                        metric = key if len(sub) == 1 else f"{key}_{idx}"
                        metrics.append((metric, num))
            elif tok in _SS_PAIRED_KEYS and i + 1 < len(tokens):
                num = _parse_ss_number(tokens[i + 1])
                if num is not None:
                    metrics.append((tok, num))
                i += 1
            i += 1
        conns.setdefault(conn_key, []).extend(metrics)
        conn_key = None
    return conns


def _sanitize(name):
    return _FNAME_SAFE_RE.sub("_", name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True, help="raw ss samples produced by ss_sampler.sh")
    ap.add_argument("-o", "--output-dir", required=True, help="directory to write ss_<conn>.counter files into")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    files = {}
    with open(args.input) as f:
        for ts, lines in iter_ts_samples(f):
            for conn_key, pairs in _parse_ss_block(lines).items():
                cf = files.get(conn_key)
                if cf is None:
                    fname = f"ss_{_sanitize(conn_key)}.counter"
                    cf = CounterFile(os.path.join(args.output_dir, fname))
                    files[conn_key] = cf
                if pairs:
                    cf.write(ts, pairs)
    for cf in files.values():
        cf.flush()


if __name__ == "__main__":
    main()
