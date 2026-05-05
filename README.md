# trace-graph

## Introduction

Trace-graph is a tool for leveraging time-sampling event traces on Linux systems
and plotting them on the [Perfetto UI](https://ui.perfetto.dev/) for visual analysis.

For example, run the following command to capture the scheduler ftrace and convert it
to the native Perfetto trace format
([synthetic track event](https://perfetto.dev/docs/reference/synthetic-track-event)).
```
$ sudo scripts/tracer.sh -o trace.log -s "sleep 5"
$ parser/main.py trace.log --output trace.pftrace
```

Then you can put `trace.pftrace` in [Perfetto UI](https://ui.perfetto.dev/) for visualization.

The parser depends on the [`perfetto`](https://pypi.org/project/perfetto/) Python package:
```
$ pip install perfetto
```

## Why trace-graph?

Perfetto already accepts the ftrace format natively, and for typical
kernel-tracing workflows its built-in importer gives you more detail
out of the
box (see
[Instrumenting the Linux kernel with ftrace](https://perfetto.dev/docs/getting-started/ftrace)).

Trace-graph exists for two cases where owning the parser pays off:

1. **Combining ftrace with other time-aligned data.** Once we control the
   parsing, we can splice in data that ftrace itself does not carry — power
   rails, thermal sensors, custom userspace samples — and emit them as
   additional tracks on the same timeline as the kernel events.

2. **Customised grouping.** The parser decides how events are organised into
   tracks. For example, interrupts can be grouped by IRQ number (one track per
   device) instead of by the CPU they fired on, depending on what you are
   investigating. Pick whichever grouping fits the question at hand.
