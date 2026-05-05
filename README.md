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

## Note

The tool aims to customize special data on the graph.

In most cases, using Perfetto's own tools will provide you with greater flexibility
and detailed information. Please find
[Instrumenting the Linux kernel with ftrace](https://perfetto.dev/docs/getting-started/ftrace)
for how to use it.
