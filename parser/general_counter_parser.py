import os
import re


# Matches a row like "[12345.678] 1,2,3" or "[12345.678] 1.5,2.0".
_ROW_RE = re.compile(r"^\[\s*([0-9]+(?:\.[0-9]+)?)\s*\]\s*(.*)$")


def _parse_value(s):
    """Parse one token into int/float, or None if non-numeric."""
    s = s.strip()
    if not s:
        return None
    try:
        if "." in s or "e" in s or "E" in s:
            return float(s)
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return None


def _iter_rows(file):
    """Yield (header, ts_ns, values) for each '[ts] v1,v2,...' row.

    Lines starting with '#' before the first data row are treated as an
    optional header naming the columns. Blank lines and other '#' lines
    are ignored.
    """
    header = None
    for raw in file:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if header is None:
                header = [c.strip() for c in line.lstrip("#").strip().split(",")]
            continue
        m = _ROW_RE.match(line)
        if not m:
            continue
        try:
            ts_ns = int(float(m.group(1)) * 10**9)
        except ValueError:
            continue
        values = [_parse_value(tok) for tok in m.group(2).split(",")]
        yield header, ts_ns, values


def parse_general_counter_log(trace, file, group_name):
    """Parse a general_counter file and emit one counter track per column.

    Format per line: ``[<seconds>] v1,v2,v3,...``. An optional leading
    ``# col1,col2,...`` line names the columns; otherwise tracks are named
    ``v1, v2, v3, ...``. All tracks for one file are grouped under
    ``counter/<group_name>``.
    """
    parent_key = f"counter/{group_name}"
    column_names = None
    for header, ts_ns, values in _iter_rows(file):
        if column_names is None:
            if header:
                column_names = header
            else:
                column_names = [f"v{i + 1}" for i in range(len(values))]
        for idx, value in enumerate(values):
            if value is None:
                continue
            col = column_names[idx] if idx < len(column_names) else f"v{idx + 1}"
            uuid = trace.make_track(
                f"{parent_key}/{col}",
                name=col,
                parent_key=parent_key,
                counter=True,
            )
            trace.add_counter_event(uuid, ts_ns, value)


def parse_general_counter_file(trace, path):
    """Open `path` and parse it as a general_counter file.

    The group name is derived from the file's basename without its extension.
    """
    group_name = os.path.splitext(os.path.basename(path))[0]
    with open(path, "r") as f:
        parse_general_counter_log(trace, f, group_name)
