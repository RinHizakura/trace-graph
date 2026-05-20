# trace-graph

## Introduction

Trace-graph is a tool for leveraging time-sampling event traces on Linux systems
and plotting them on the [Perfetto UI](https://ui.perfetto.dev/) for visual analysis.

For example, run the following command to capture the scheduler ftrace and convert it
to the native Perfetto trace format
([synthetic track event](https://perfetto.dev/docs/reference/synthetic-track-event)).
```
$ sudo scripts/tracer.sh -o trace_output -s "sleep 5"
$ parser/main.py trace_output --output trace.pftrace
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

## general_counter format

Any file whose rows look like

```
# col1,col2,col3
[<seconds>] v1,v2,v3
[<seconds>] v1,v2,v3
```

can be plotted as counter tracks. The leading `# ...` header line names the
columns (otherwise they fall back to `v1, v2, ...`); every column becomes one
counter track grouped under `counter/<file basename>`.

Pass each file with `--counter`. The argument is resolved against the input
directory and accepts globs. For example:

```
$ parser/main.py trace_output --counter 'ss_*.counter'
```

## Tracer helpers

`tracer.sh -t` accepts a *tracer*: a small daemon that collects some kind of
useful, time-aligned data alongside the ftrace. Each `-t` is repeatable, runs
in the background while the target command executes, and is stopped when the
target exits. The `-t` slot is the general, customisable interface; the bundled
helpers below also have shorthand long options.

### Convenience options

For the bundled helpers you do not need to spell out the `-t` command and the
parse step. The long options below start the matching sampler alongside the
target and convert its raw file into a counter once the target exits, printing
the exact `parser/main.py` command to plot the result:

```
$ sudo scripts/tracer.sh -s --ss --netstat --interrupts -o trace_output "sleep 5"
```

| Option         | Samples              | Produces                 |
|----------------|----------------------|--------------------------|
| `--ss`         | `ss -tin`            | `ss_*.counter`           |
| `--netstat`    | `/proc/net/netstat`  | `netstat.counter`        |
| `--interrupts` | `/proc/interrupts`   | `interrupts.counter`     |

The verbose `-t` form documented below stays available for custom helpers or
non-default sampling periods.

### Network sampling

Network state is collected in two steps to keep the sampling loop cheap.

1. **Sample raw snapshots.** Each sampler writes one `@TS`-delimited raw file.
   Hand them to `tracer.sh` with `-t` (repeatable) — they run in the
   background alongside the target command and are stopped when it exits:

   ```
   $ sudo scripts/tracer.sh -s -o trace_output \
       -t "helpers/ss/ss_sampler.sh -o ss.raw -p 1" \
       -t "helpers/netstat/netstat_sampler.sh -o netstat.raw -p 1" \
       "sleep 5"
   ```

2. **Convert raw to general_counter.** Each parser reads one raw file and
   writes counter files into the output directory:

   ```
   $ helpers/ss/ss_parser.py -i ss.raw -o trace_output
   $ helpers/netstat/netstat_parser.py -i netstat.raw -o trace_output
   $ parser/main.py trace_output --counter 'netstat.counter' --counter 'ss_*.counter'
   ```

### Interrupt sampling

Interrupt activity is collected the same two-step way. The sampler periodically
snapshots `/proc/interrupts`; the parser sums each IRQ's per-CPU counts into a
single `interrupts.counter`. The counts are cumulative since boot, so on the
Perfetto timeline the slope of each track is the interrupt rate.

This is complementary to the ftrace `irq` events (`tracer.sh -i`): ftrace gives
per-interrupt entry/exit slices, while this gives a cheap, always-on count per
IRQ device that lines up with every other counter on the timeline.

1. **Sample raw snapshots.**

   ```
   $ sudo scripts/tracer.sh -s -o trace_output \
       -t "helpers/interrupts/interrupts_sampler.sh -o interrupts.raw -p 1" \
       "sleep 5"
   ```

2. **Convert raw to general_counter.**

   ```
   $ helpers/interrupts/interrupts_parser.py -i interrupts.raw -o trace_output
   $ parser/main.py trace_output --counter 'interrupts.counter'
   ```


