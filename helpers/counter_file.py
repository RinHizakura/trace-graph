"""Shared building blocks for @TS-framed sampler raw files.

Every sampler under ``helpers/`` writes a raw file as a stream of
``@TS <seconds>`` lines interleaved with the snapshot body (e.g.
``/proc/diskstats``). Every parser then reduces that into a
``general_counter`` file with one ``#`` header row and ``[ts] v1,v2,...``
data rows. This module factors out the two pieces every parser needs:

* :func:`iter_ts_samples` — yield ``(ts_str, lines)`` per ``@TS`` block.
* :class:`CounterFile` — buffer the counter rows and flush them at the end,
  in either fixed- or dynamic-column mode.

Trimming the pre-command warmup window is the job of ``parser/main.py``,
which reads ``$OUTPUT/start_ts`` and filters rows at plot time; helpers
emit the full sample series unmodified.
"""


def iter_ts_samples(file):
    """Yield ``(ts_str, lines)`` for each ``@TS <seconds>`` block.

    Lines before the first ``@TS`` are discarded — they are the sampler's
    one-off header (e.g. probe_sampler's ``@PROBES`` line). If a caller needs
    that preamble it should read the file directly.
    """
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


class CounterFile:
    """Buffer header + rows in memory; flush as a complete file at the end.

    Two modes:

    * **Fixed columns** — pass ``columns=[...]`` to ``__init__``. Each
      ``write(ts, values)`` call provides a list of values aligned with the
      declared columns. Used when the schema is known up front (diskstats).

    * **Dynamic columns** — omit ``columns``. Each ``write(ts, pairs)`` call
      provides ``[(name, value), ...]``; new names are appended as columns
      in first-seen order. Used when the column set emerges from the data
      (probe, netstat, interrupts, ss).
    """

    def __init__(self, path, columns=None):
        self.path = path
        if columns is None:
            self.columns = []
            self.col_index = {}
            self._dynamic = True
        else:
            self.columns = list(columns)
            self.col_index = {n: i for i, n in enumerate(self.columns)}
            self._dynamic = False
        self.rows = []

    def declare_columns(self, names):
        """Pre-register column names in dynamic mode so they appear in this order
        even if some rows are missing them. No-op for already-registered names."""
        if not self._dynamic:
            return
        for name in names:
            if name in self.col_index:
                continue
            self.col_index[name] = len(self.columns)
            self.columns.append(name)

    def write(self, ts, data):
        if self._dynamic:
            for name, _ in data:
                if name in self.col_index:
                    continue
                self.col_index[name] = len(self.columns)
                self.columns.append(name)
            row = [""] * len(self.columns)
            for name, value in data:
                idx = self.col_index.get(name)
                if idx is not None:
                    row[idx] = str(value)
        else:
            row = [str(v) for v in data]
        self.rows.append((ts, row))

    def _active_columns(self):
        """Indices of columns whose integer value rises above its first sample.

        Drops counter columns that never moved during the trace window. Used
        by interrupts where many IRQ lines are idle. Non-integer columns are
        treated as active (the filter only makes sense for cumulative counts).
        """
        keep = []
        for i in range(len(self.columns)):
            first = None
            active = False
            for _, row in self.rows:
                if i >= len(row):
                    continue
                cell = row[i]
                if not cell:
                    continue
                try:
                    val = int(cell)
                except ValueError:
                    active = True
                    break
                if first is None:
                    first = val
                elif val > first:
                    active = True
                    break
            if active:
                keep.append(i)
        return keep

    def flush(self, drop_inactive=False):
        if not self.columns or not self.rows:
            return
        if drop_inactive:
            keep = self._active_columns()
            if not keep:
                return
        else:
            keep = list(range(len(self.columns)))
        ncols = len(self.columns)
        with open(self.path, "w") as f:
            f.write("# " + ",".join(self.columns[i] for i in keep) + "\n")
            for ts, row in self.rows:
                # Dynamic-mode rows from before later columns appeared are
                # short; pad so column indices line up.
                if len(row) < ncols:
                    row = row + [""] * (ncols - len(row))
                f.write(f"[{ts}] " + ",".join(row[i] for i in keep) + "\n")
