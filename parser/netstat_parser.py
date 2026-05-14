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


def _emit_netstat_sample(trace, timestamp_ns, lines):
    """Parse one /proc/net/netstat snapshot and emit every counter."""
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
                value = int(raw)
            except ValueError:
                continue
            uuid = trace.make_track(
                f"net/netstat/{section}/{name}",
                name=name,
                parent_key=f"net/netstat/{section}",
                counter=True,
            )
            trace.add_counter_event(uuid, timestamp_ns, value)


def parse_netstat_log(trace, file):
    """Parse netstat.log produced by tracer.sh -n (snapshots of /proc/net/netstat)."""
    for ts_ns, lines in _iter_ts_samples(file):
        _emit_netstat_sample(trace, ts_ns, lines)
