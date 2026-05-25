# trace-graph

## Introduction

Trace-graph is a tool for leveraging time-sampling event traces on Linux systems
and plotting them on the [Perfetto UI](https://ui.perfetto.dev/) for visual analysis.

For example, run the following command to capture the scheduler ftrace and convert it
to the native Perfetto trace format
([synthetic track event](https://perfetto.dev/docs/reference/synthetic-track-event)).
```
$ sudo scripts/tracer.sh -o trace_output --ftrace sched "sleep 5"
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

## Features
### general_counter format

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

### Pre-command warmup trim

`tracer.sh` brings every tracer up *before* releasing the target command and
records a `START_TS` (matching `/proc/uptime`, captured against the boot
clock that ftrace is also pinned to) at the exact moment the command is
allowed to run. The value is written to `<output>/start_ts`. The raw
artifacts on disk — `ftrace.log` and the `.counter` files — keep the full
sample series including the warmup window.

`parser/main.py` reads `<output>/start_ts` and drops the pre-command rows
when it builds the Perfetto trace, so every track lines up at the moment
the command really started. The file is mandatory — `parser/main.py`
refuses to run without it.

## Ftrace event selection

`tracer.sh` enables ftrace events for the duration of the target command and
dumps the resulting trace into `ftrace.log`. Pick events with `-e <event>` for
a single raw event by name (e.g. `sched/sched_switch`, repeatable), or with
`--ftrace <preset>` for a curated group of related events. Each preset expands
to a small set of events that are usually wanted together; presets are
repeatable and may be mixed with `-e`:

| Preset      | Events enabled                                                            |
|-------------|---------------------------------------------------------------------------|
| `all`       | every event the kernel exposes (large traces)                             |
| `bio`       | `block/block_rq_insert`, `block/block_rq_complete`                        |
| `cpuidle`   | `power/cpu_idle`                                                          |
| `irq`       | `irq/irq_handler_entry`, `irq/irq_handler_exit`, `irq/softirq_entry`, `irq/softirq_exit` |
| `sched`     | `sched/sched_switch`                                                      |

Combine presets freely — repeat the option, or pass a comma-separated list:

```
$ sudo scripts/tracer.sh --ftrace sched --ftrace irq -o trace_output "sleep 5"
$ sudo scripts/tracer.sh --ftrace sched,irq,bio      -o trace_output "sleep 5"
```

## Tracer helpers

`tracer.sh -t` accepts a *tracer*: a small daemon that collects some kind of
useful, time-aligned data alongside the ftrace. Each `-t` is repeatable, runs
in the background while the target command executes, and is stopped when the
target exits. The bundled helpers below also have a shorthand `--tracer <name>`
form that starts the matching sampler and converts its raw file into a counter
once the target exits, printing the exact `parser/main.py` command to plot the
result:

```
$ sudo scripts/tracer.sh --ftrace sched --tracer ss,netstat,interrupts,diskstats -o trace_output "sleep 5"
```

| Option                | Samples              | Produces                 |
|-----------------------|----------------------|--------------------------|
| `--tracer ss`         | `ss -tin`            | `ss_*.counter`           |
| `--tracer netstat`    | `/proc/net/netstat`  | `netstat.counter`        |
| `--tracer interrupts` | `/proc/interrupts`   | `interrupts.counter`     |
| `--tracer diskstats`  | `/proc/diskstats`    | `diskstats_*.counter`    |

`--tracer` accepts the same comma-separated form as `--ftrace` (e.g.
`--tracer ss,netstat`). The verbose `-t` form documented below stays available
for custom helpers or non-default sampling periods.

### Network sampling

Network state is collected in two steps to keep the sampling loop cheap.

1. **Sample raw snapshots.** Each sampler writes one `@TS`-delimited raw file.
   Hand them to `tracer.sh` with `-t` (repeatable) — they run in the
   background alongside the target command and are stopped when it exits:

   ```
   $ sudo scripts/tracer.sh --ftrace sched -o trace_output \
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

This is complementary to the ftrace `irq` events (`tracer.sh --ftrace irq`): ftrace gives
per-interrupt entry/exit slices, while this gives a cheap, always-on count per
IRQ device that lines up with every other counter on the timeline.

1. **Sample raw snapshots.**

   ```
   $ sudo scripts/tracer.sh --ftrace sched -o trace_output \
       -t "helpers/interrupts/interrupts_sampler.sh -o interrupts.raw -p 1" \
       "sleep 5"
   ```

2. **Convert raw to general_counter.**

   ```
   $ helpers/interrupts/interrupts_parser.py -i interrupts.raw -o trace_output
   $ parser/main.py trace_output --counter 'interrupts.counter'
   ```

### Block device I/O sampling

Per-device throughput (bytes/sec) and IOPS (ops/sec) are derived from
`/proc/diskstats` in the same two-step shape.

1. **Sample raw snapshots.** The sampler dumps `/proc/diskstats` at every
   period:

   ```
   $ sudo scripts/tracer.sh --ftrace sched -o trace_output \
       -t "helpers/diskstats/diskstats_sampler.sh -o trace_output/diskstats.raw -p 1" \
       "sleep 5"
   ```

2. **Convert raw to general_counter.** The parser computes per-interval
   deltas and writes one counter file per device. Use `-d` (repeatable) to
   restrict output to specific devices; omit it to include every device that
   showed activity during the trace:

   ```
   $ helpers/diskstats/diskstats_parser.py -i trace_output/diskstats.raw \
       -o trace_output -d nvme0n1 -d sda
   $ parser/main.py trace_output --counter 'diskstats_*.counter'
   ```

   Each output file has columns `read_bps, write_bps, read_iops, write_iops`.

## Kprobe call-count counters

`--probe FUNC` installs a kprobe on the given kernel symbol for the duration
of the target command and reports its cumulative hit count as one column in
`probe.counter`. The slope of each track on the Perfetto timeline is the call
rate of that function — useful for things that have no dedicated tracepoint.
Repeat the option or pass a comma-separated list to probe several symbols at
once:

```
$ sudo scripts/tracer.sh --ftrace sched -o trace_output \
    --probe arm_smmu_atc_inv_domain,__arm_smmu_tlb_inv_range \
    "sleep 5"
$ parser/main.py trace_output --counter 'probe.counter'
```

The same flow can be driven manually if you want to compose your own
pipeline — hand the sampler to `tracer.sh -t` and run the parser by hand.
The warmup trim still happens in `parser/main.py` via `<output>/start_ts`:

```
$ sudo scripts/tracer.sh --ftrace sched -o trace_output \
    -t "helpers/probe/probe_sampler.sh -o trace_output/probe.raw -p 1 \
        -f arm_smmu_atc_inv_domain -f __arm_smmu_tlb_inv_range" \
    "sleep 5"
$ helpers/probe/probe_parser.py -i trace_output/probe.raw -o trace_output
$ parser/main.py trace_output --counter 'probe.counter'
```

Under the hood this writes `p:<sanitized_name> <FUNC>` to
`/sys/kernel/tracing/kprobe_events` (lands in the default `kprobes/` group),
samples `kprobe_profile` once per second, and removes the probes on exit.
Symbols that the kernel does not expose to kprobes (inlined, `notrace`,
missing) cause the helper to abort with an error before the target command
runs.
