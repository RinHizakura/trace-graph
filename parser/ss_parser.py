import re


# Matches a numeric value optionally followed by a unit suffix (e.g. "204", "0.123", "1ms", "21281.3Mbps").
_SS_NUM_RE = re.compile(r"^([-+]?\d+(?:\.\d+)?)([A-Za-z%]*)$")

# Keys in `ss -tin` detail lines whose value is the NEXT whitespace-separated
# token rather than colon-attached (e.g. "send 21281.3Mbps").
_SS_PAIRED_KEYS = {"send", "pacing_rate", "delivery_rate"}


def _iter_ts_samples(file):
    """Yield (ts_ns, lines) for each '@TS <seconds>'-delimited block."""
    ts_ns = None
    lines = []
    for raw in file:
        line = raw.rstrip("\n")
        if line.startswith("@TS "):
            if ts_ns is not None:
                yield ts_ns, lines
            try:
                ts_ns = int(float(line[4:]) * 10**9)
            except ValueError:
                ts_ns = None
            lines = []
        else:
            lines.append(line)
    if ts_ns is not None:
        yield ts_ns, lines


def _parse_ss_number(s):
    """Parse a `ss` value (optionally with a unit suffix) into a float, or None if non-numeric."""
    m = _SS_NUM_RE.match(s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _emit_ss_metric(trace, conn_key, metric, value, timestamp_ns):
    uuid = trace.make_track(
        f"net/conn/{conn_key}/{metric}",
        name=metric,
        parent_key=f"net/conn/{conn_key}",
        counter=True,
    )
    trace.add_counter_event(uuid, timestamp_ns, value)


def _emit_ss_sample(trace, timestamp_ns, lines):
    """Parse one `ss -tin` snapshot and emit every numeric per-connection metric."""
    conn_key = None
    for line in lines:
        if not line.strip():
            continue
        # Detail lines are indented; state lines start at column 0.
        if not line[0].isspace():
            parts = line.split()
            # Skip the column header line.
            if not parts or parts[0] == "State":
                conn_key = None
                continue
            if len(parts) < 5:
                conn_key = None
                continue
            local, peer = parts[3], parts[4]
            conn_key = f"{local}-{peer}"
            continue

        if conn_key is None:
            continue

        tokens = line.split()
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
                        _emit_ss_metric(trace, conn_key, metric, num, timestamp_ns)
            elif tok in _SS_PAIRED_KEYS and i + 1 < len(tokens):
                num = _parse_ss_number(tokens[i + 1])
                if num is not None:
                    _emit_ss_metric(trace, conn_key, tok, num, timestamp_ns)
                i += 1
            i += 1
        # The detail line ends this connection's record.
        conn_key = None


def parse_ss_log(trace, file):
    """Parse ss.log produced by tracer.sh -n (snapshots of `ss -tin`)."""
    for ts_ns, lines in _iter_ts_samples(file):
        _emit_ss_sample(trace, ts_ns, lines)
