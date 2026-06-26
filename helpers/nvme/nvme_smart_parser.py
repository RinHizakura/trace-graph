#!/usr/bin/env python3
"""Convert nvme.raw (@TS-framed nvme smart-log JSON snapshots) into
``nvme_smart.counter`` inside the output directory.

Each column is named ``<device>_<field>`` (e.g. ``nvme0_temperature_C``).
The ``temperature`` field (reported in Kelvin by nvme-cli) is converted to
Celsius and renamed accordingly.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from counter_file import CounterFile


def _read_preamble(f):
    line = f.readline().rstrip("\n")
    if not line.startswith("@DEVS "):
        raise ValueError("Missing @DEVS preamble in raw file")
    return line[6:].split()


def _iter_ts_blocks(f):
    """Yield (ts_str, list of (dev, json_text)) per @TS frame."""
    ts = None
    dev = None
    buf = []
    devs = []

    for raw in f:
        line = raw.rstrip("\n")
        if line.startswith("@TS "):
            if ts is not None:
                if dev is not None:
                    devs.append((dev, "".join(buf)))
                yield ts, devs
            ts = line[4:].strip()
            dev = None
            buf = []
            devs = []
        elif line.startswith("@DEV "):
            if dev is not None:
                devs.append((dev, "".join(buf)))
            dev = line[5:].strip()
            buf = []
        else:
            if dev is not None:
                buf.append(line)

    if ts is not None:
        if dev is not None:
            devs.append((dev, "".join(buf)))
        yield ts, devs


def _parse_fields(json_text):
    """Return list of (column_name, value) from a smart-log JSON blob."""
    try:
        data = json.loads(json_text)
    except (json.JSONDecodeError, ValueError):
        return []

    pairs = []
    for key, val in data.items():
        if not isinstance(val, (int, float)):
            continue
        # temperature is Kelvin; convert and rename
        if key == "temperature":
            pairs.append(("temperature_C", int(val) - 273))
        else:
            pairs.append((key, val))
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True,
                    help="raw nvme samples produced by nvme_sampler.sh")
    ap.add_argument("-o", "--output-dir", required=True,
                    help="directory to write nvme_smart.counter into")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    with open(args.input) as f:
        _read_preamble(f)  # consume @DEVS line (device order comes from data)
        cf = CounterFile(os.path.join(args.output_dir, "nvme_smart.counter"))

        for ts_str, dev_blocks in _iter_ts_blocks(f):
            pairs = []
            for dev, json_text in dev_blocks:
                for field, val in _parse_fields(json_text):
                    pairs.append((f"{dev}_{field}", val))
            if pairs:
                cf.write(ts_str, pairs)

    cf.flush()


if __name__ == "__main__":
    main()
