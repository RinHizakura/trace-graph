# trace-graph

## Introduction

Trace-graph is a tool for leveraging time-sampling event traces on Linux systems
and plotting them on the [Perfetto UI](https://ui.perfetto.dev/) for visual analysis.

For example, run the following command to capture the scheduler ftrace and convert it
to the special JSON format.
```
$ sudo scripts/tracer.sh -o trace.log -s "sleep 5"
$ parser/main.py trace.log --output trace.json
```

Then you can put `trace.json` in [Perfetto UI](https://ui.perfetto.dev/) for visualization.

## Note

The tool aims to customize special data on the graph.

In most cases, using Perfetto's own tools will provide you with greater flexibility
and detailed information. Please find
[Instrumenting the Linux kernel with ftrace](https://perfetto.dev/docs/getting-started/ftrace)
for how to use it.
