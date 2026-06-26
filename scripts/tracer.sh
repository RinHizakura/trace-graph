#!/usr/bin/env bash
set -e

SYSFS_TRACE=/sys/kernel/debug/tracing

function enable_event()
{
    EVENT=$1
    echo write enable to $SYSFS_TRACE/events/$EVENT/enable
    echo 1 > $SYSFS_TRACE/events/$EVENT/enable
}

function ftrace_sampler()
{
    local phase=$1
    case $phase in
        setup)
            # Clean the trace buffer at start
            echo 0 > $SYSFS_TRACE/trace

            # Disable the trace first before we setup everything
            echo 0 > $SYSFS_TRACE/events/enable
            echo 0 > $SYSFS_TRACE/tracing_on

            # Use the boot clock so ftrace timestamps line up with /proc/uptime
            # (the clock the samplers and START_TS use); the trace_clock write
            # must happen while the buffer is empty.
            echo boot > $SYSFS_TRACE/trace_clock

            if [[ $ALL_EVENTS -eq 1 ]]; then
                echo Enable all events
                enable_event ""
            else
                for ev in ${EVENT_LIST[@]}; do
                    echo Enable event $ev
                    enable_event $ev
                done
            fi

            # Choose the tracer with target setting
            echo event-fork > $SYSFS_TRACE/trace_options
            echo 1 > $SYSFS_TRACE/options/record-tgid
            echo nop > $SYSFS_TRACE/current_tracer
            ;;
        start)
            local cpid=$2
            # Extra setting to focus on the process from the command
            if [[ $PID -eq 1 ]]; then
                # Add child pid to filter to start tracing it
                echo $cpid > $SYSFS_TRACE/set_event_pid
            fi
            echo 1 > $SYSFS_TRACE/tracing_on
            ;;
        stop)
            echo 0 > $SYSFS_TRACE/tracing_on

            # Output result
            cat $SYSFS_TRACE/trace > $FTRACE_OUTPUT

            # Cleanup the change of ftrace
            echo > $SYSFS_TRACE/set_event_pid
            echo nop > $SYSFS_TRACE/current_tracer
            echo 0 > $SYSFS_TRACE/events/enable
            echo local > $SYSFS_TRACE/trace_clock
            ;;
    esac
}

# Run all the post-cmd reductions: convert each bundled sampler's raw file
# into a general_counter file. Pre-command warmup samples are not trimmed
# here — parser/main.py reads $OUTPUT/start_ts and filters at plot time so
# the raw artifacts on disk stay complete.
function post_parse()
{
    for parse in "${POST_PARSE[@]}"; do
        echo "Parsing: $parse"
        eval "$parse"
    done
}

function print_help()
{
    usage="$(basename "$0") [-h] [-o output] [-e event] [-p] [-t cmd] [--ftrace preset] [--tracer name] [--probe func] \n
where:                                                 \n
    -h  show this help text                            \n
    -o  specify the output directory (default /tmp/trace_log) \n
    -e  select the event for ftrace                    \n
    -p  trace only the run command and its childs' PID \n
    -t  run this tracer helper alongside the target command (repeatable) \n
\n
convenience ftrace presets (named ftrace event groups, repeatable): \n
    --ftrace all       enable every ftrace event                   \n
    --ftrace bio       block_rq_insert / block_rq_complete         \n
    --ftrace cpuidle   power/cpu_idle                              \n
    --ftrace irq       irq + softirq entry/exit                    \n
    --ftrace sched     sched/sched_switch                          \n
\n
convenience bundled tracers (run a helper and convert it to a counter, repeatable): \n
    --tracer ss          sample TCP socket stats (ss -tin) \n
    --tracer netstat     sample /proc/net/netstat          \n
    --tracer interrupts  sample /proc/interrupts           \n
    --tracer diskstats   sample /proc/diskstats            \n
    --tracer nvme-smart  sample NVMe SMART log (all fields, nvme smart-log) \n
\n
kprobe call counters (one column per function in probe.counter, repeatable): \n
    --probe FUNC         add a kprobe on kernel symbol FUNC and emit its hit count \n
\n
Use -e for any raw ftrace event and -t for any custom helper; the long options above are shorthand for the bundled ones."

    echo -e $usage
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPERS_DIR="$SCRIPT_DIR/../helpers"

OUTPUT="/tmp/trace_log"
EVENT=$SYSFS_TRACE/events
EVENT_LIST=()
ALL_EVENTS=0
PID=0
TRACERS=()
SAMPLE_SS=0
SAMPLE_NETSTAT=0
SAMPLE_IRQ=0
SAMPLE_DISKSTATS=0
SAMPLE_NVME=0
NVME_DEVS=()
PROBE_LIST=()
add_ftrace_preset()
{
    local IFS=','
    local item
    for item in $1; do
        [ -z "$item" ] && continue
        case "$item" in
            all) ALL_EVENTS=1;;
            bio) EVENT_LIST+=("block/block_rq_insert" "block/block_rq_complete");;
            cpuidle) EVENT_LIST+=("power/cpu_idle");;
            irq) EVENT_LIST+=("irq/irq_handler_entry" "irq/irq_handler_exit" \
                              "irq/softirq_entry" "irq/softirq_exit");;
            sched) EVENT_LIST+=("sched/sched_switch");;
            *) echo "Unknown --ftrace preset: $item" >&2; print_help; exit 1;;
        esac
    done
}

add_bundled_tracer()
{
    local IFS=','
    local item
    for item in $1; do
        [ -z "$item" ] && continue
        case "$item" in
            ss) SAMPLE_SS=1;;
            netstat) SAMPLE_NETSTAT=1;;
            interrupts) SAMPLE_IRQ=1;;
            diskstats) SAMPLE_DISKSTATS=1;;
            nvme-smart) SAMPLE_NVME=1;;
            nvme-smart=*) SAMPLE_NVME=1; NVME_DEVS+=("${item#nvme-smart=}");;
            *) echo "Unknown --tracer name: $item" >&2; print_help; exit 1;;
        esac
    done
}

add_probe()
{
    local IFS=','
    local item
    for item in $1; do
        [ -z "$item" ] && continue
        PROBE_LIST+=("$item")
    done
}

while getopts ":o:e:t:ph-:" opt
do
    case $opt in
        -)
            case "$OPTARG" in
                ftrace)
                    val="${!OPTIND}"; OPTIND=$((OPTIND + 1))
                    add_ftrace_preset "$val";;
                tracer)
                    val="${!OPTIND}"; OPTIND=$((OPTIND + 1))
                    add_bundled_tracer "$val";;
                probe)
                    val="${!OPTIND}"; OPTIND=$((OPTIND + 1))
                    add_probe "$val";;
                help) print_help; exit 0;;
                *) echo "Unknown option --$OPTARG" >&2; print_help; exit 1;;
            esac;;
        o)
            OUTPUT="$OPTARG";;
        e)
            EVENT_LIST+=("$OPTARG");;
        p)
            PID=1;;
        t)
            TRACERS+=("$OPTARG");;
        h)
            print_help; exit 0;;
        ?)
            print_help; exit 1;;
    esac
done

shift $(($OPTIND - 1))
CMD=$*

if [ "$CMD" == "" ]; then
    print_help
    exit 1
fi

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root user."
    exit 1
fi

rm -rf "$OUTPUT"
mkdir -p "$OUTPUT"
FTRACE_OUTPUT="$OUTPUT/ftrace.log"

# Translate the convenience long options into a bundled sampler (run alongside
# the target via the same -t machinery) plus a parse step run after it stops.
POST_PARSE=()
COUNTER_GLOBS=()
if [[ $SAMPLE_SS -eq 1 ]]; then
    TRACERS+=("$HELPERS_DIR/ss/ss_sampler.sh -o $OUTPUT/ss.raw -p 1")
    POST_PARSE+=("$HELPERS_DIR/ss/ss_parser.py -i $OUTPUT/ss.raw -o $OUTPUT")
    COUNTER_GLOBS+=("'ss_*.counter'")
fi
if [[ $SAMPLE_NETSTAT -eq 1 ]]; then
    TRACERS+=("$HELPERS_DIR/netstat/netstat_sampler.sh -o $OUTPUT/netstat.raw -p 1")
    POST_PARSE+=("$HELPERS_DIR/netstat/netstat_parser.py -i $OUTPUT/netstat.raw -o $OUTPUT")
    COUNTER_GLOBS+=("'netstat.counter'")
fi
if [[ $SAMPLE_IRQ -eq 1 ]]; then
    TRACERS+=("$HELPERS_DIR/interrupts/interrupts_sampler.sh -o $OUTPUT/interrupts.raw -p 1")
    POST_PARSE+=("$HELPERS_DIR/interrupts/interrupts_parser.py -i $OUTPUT/interrupts.raw -o $OUTPUT")
    COUNTER_GLOBS+=("'interrupts.counter'")
fi
if [[ $SAMPLE_DISKSTATS -eq 1 ]]; then
    TRACERS+=("$HELPERS_DIR/diskstats/diskstats_sampler.sh -o $OUTPUT/diskstats.raw -p 1")
    POST_PARSE+=("$HELPERS_DIR/diskstats/diskstats_parser.py -i $OUTPUT/diskstats.raw -o $OUTPUT")
    COUNTER_GLOBS+=("'diskstats_*.counter'")
fi
if [[ $SAMPLE_NVME -eq 1 ]]; then
    nvme_dev_args=""
    for d in "${NVME_DEVS[@]}"; do
        nvme_dev_args+=" -d $d"
    done
    TRACERS+=("$HELPERS_DIR/nvme/nvme_smart_sampler.sh -o $OUTPUT/nvme.raw -p 1$nvme_dev_args")
    POST_PARSE+=("$HELPERS_DIR/nvme/nvme_smart_parser.py -i $OUTPUT/nvme.raw -o $OUTPUT")
    COUNTER_GLOBS+=("'nvme_temp.counter'")
fi
if [[ ${#PROBE_LIST[@]} -gt 0 ]]; then
    probe_args=""
    for f in "${PROBE_LIST[@]}"; do
        probe_args+=" -f $f"
    done
    TRACERS+=("$HELPERS_DIR/probe/probe_sampler.sh -o $OUTPUT/probe.raw -p 1$probe_args")
    POST_PARSE+=("$HELPERS_DIR/probe/probe_parser.py -i $OUTPUT/probe.raw -o $OUTPUT")
    COUNTER_GLOBS+=("'probe.counter'")
fi

FTRACE=0
if [[ $ALL_EVENTS -eq 1 || ${#EVENT_LIST[@]} -gt 0 ]]; then
    FTRACE=1
else
    echo "No event is selected for ftrace, will skip ftrace part."
fi

if [[ $FTRACE -eq 1 ]]; then
    ftrace_sampler setup
fi

# Start tracers BEFORE the target command so the kernel-side setup (kprobe
# registration, file opens, ...) is complete and we know they're healthy
# before any cmd output is sampled. The command is launched in a subshell
# that SIGSTOPs itself just before exec'ing $CMD so we get the cmd's real
# PID into $CPID (exec keeps the PID) and have a precise moment to write
# the ftrace pid filter and capture START_TS. SIGCONT releases it.
(exec bash -c 'kill -STOP $$; exec "$@"' _ $CMD) &
CPID=$!

# Wait until the child is actually stopped so set_event_pid is written
# against a task the kernel knows; /proc/<pid>/stat field 3 = 'T' when
# stopped.
while :; do
    state=$(awk '{print $3}' "/proc/$CPID/stat" 2>/dev/null) || break
    [ "$state" = "T" ] && break
done
echo "Prepared command '$CMD' (pid=$CPID), waiting for tracer setup..."

if [[ $FTRACE -eq 1 ]]; then
    ftrace_sampler start $CPID
fi

TRACER_PIDS=()
for tracer in "${TRACERS[@]}"; do
    # Background inside eval so the cmd runs as a direct child of this shell.
    # `eval "$tracer" &` would fork a subshell first; $! would then be the
    # subshell PID and the actual tracer survives cleanup as an orphan.
    eval "$tracer &"
    TRACER_PIDS+=($!)
    echo "Started tracer '$tracer' pid=${TRACER_PIDS[-1]}"
done

# Give tracers a moment to finish their setup phase, then verify each one is
# still alive. A tracer that died during setup (e.g. kprobe registration
# failed) would otherwise leave the command running with no data and break
# post-parsing on the missing raw file.
if [[ ${#TRACER_PIDS[@]} -gt 0 ]]; then
    sleep 0.5
    for i in "${!TRACER_PIDS[@]}"; do
        pid=${TRACER_PIDS[$i]}
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "Error: tracer '${TRACERS[$i]}' exited during startup" >&2
            for p in "${TRACER_PIDS[@]}"; do
                kill "$p" 2>/dev/null || true
            done
            # $CPID is SIGSTOP'd until release; SIGTERM would be queued, so use SIGKILL.
            kill -KILL "$CPID" 2>/dev/null || true
            if [[ $FTRACE -eq 1 ]]; then
                ftrace_sampler stop
            fi
            exit 1
        fi
    done
fi

# Capture the start timestamp (matches /proc/uptime which the samplers use)
# and release the command. Parsers will drop any sample whose @TS is earlier
# than this so the warmup window doesn't show up on the timeline; the
# timestamp is also persisted to $OUTPUT/start_ts so downstream tools can
# read it back without re-deriving from the parser CLI.
START_TS=$(awk '{print $1}' /proc/uptime)
echo "$START_TS" > "$OUTPUT/start_ts"
kill -CONT "$CPID"
echo "Command released at @TS=$START_TS"

# Stop error exit temporary to make sure we can get the return code of the command
set +e
wait $CPID
ret=$?
set -e
echo "Command '$CMD' finished. Return code: $ret"

for pid in "${TRACER_PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
done
for pid in "${TRACER_PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
done
if [[ ${#TRACER_PIDS[@]} -gt 0 ]]; then
    echo "Tracers stopped."
fi

# Dump the ftrace buffer to $FTRACE_OUTPUT before post-parsing so post_parse
# can prune its warmup tail alongside the bundled counter conversions.
if [[ $FTRACE -eq 1 ]]; then
    ftrace_sampler stop
    echo "ftrace sampler stopped. Output: $FTRACE_OUTPUT"
fi

post_parse

echo "Done. Please find $OUTPUT for the trace log."

counter_args=""
for glob in "${COUNTER_GLOBS[@]}"; do
    counter_args+=" --counter $glob"
done
echo "To plot in the Perfetto trace viewer run:"
echo "  parser/main.py $OUTPUT$counter_args --output trace.pftrace"
