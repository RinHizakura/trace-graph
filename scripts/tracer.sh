#!/usr/bin/env bash
set -e

SYSFS_TRACE=/sys/kernel/debug/tracing

function enable_event()
{
    EVENT=$1
    echo write enable to $SYSFS_TRACE/events/$EVENT/enable
    echo 1 > $SYSFS_TRACE/events/$EVENT/enable
}

function net_sampler()
{
    local ss_out=$1
    local netstat_out=$2
    local period=$3
    while true; do
        local ts
        ts=$(awk '{print $1}' /proc/uptime)
        {
            echo "@TS $ts"
            ss -tin 2>/dev/null
        } >> "$ss_out"
        {
            echo "@TS $ts"
            cat /proc/net/netstat
        } >> "$netstat_out"
        sleep "$period"
    done
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
            ;;
    esac
}

function print_help()
{
    usage="$(basename "$0") [-h] [-o output] [-e event] [-a] [-b] [-c] [-i] [-s] [-p] [-n]  \n
where:                                                 \n
    -h  show this help text                            \n
    -o  specify the output directory (default /tmp/trace_log) \n
    -e  select the event for ftrace                    \n
    -a  select all events for ftrace                   \n
    -b  select the bio event for ftrace                \n
    -c  selec the cpuidle event for ftrace             \n
    -i  select the irq event for ftrace                \n
    -s  select the sched event for ftrace              \n
    -p  trace only the run command and its childs' PID \n
    -n  sample network status every 1s into <output>/ss.log and <output>/netstat.log"

    echo -e $usage
}

OUTPUT="/tmp/trace_log"
EVENT=$SYSFS_TRACE/events
EVENT_LIST=()
ALL_EVENTS=0
PID=0
NET=0
NET_PERIOD=1
while getopts ":o:e:bcispahn" opt
do
    case $opt in
        o)
            OUTPUT="$OPTARG";;
        a)
            ALL_EVENTS=1;;
        e)
            EVENT_LIST+=("$OPTARG");;
        b)
            EVENT_LIST+=("block/block_rq_insert" "block/block_rq_complete");;
        c)
            EVENT_LIST+=("power/cpu_idle");;
        i)
            EVENT_LIST+=("irq/irq_handler_entry" "irq/irq_handler_exit");
            EVENT_LIST+=("irq/softirq_entry" "irq/softirq_exit");;
        s)
            EVENT_LIST+=("sched/sched_switch");;
        p)
            PID=1;;
        n)
            NET=1;;
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
SS_OUTPUT="$OUTPUT/ss.log"
NETSTAT_OUTPUT="$OUTPUT/netstat.log"

FTRACE=0
if [[ $ALL_EVENTS -eq 1 || ${#EVENT_LIST[@]} -gt 0 ]]; then
    FTRACE=1
else
    echo "No event is selected for ftrace, will skip ftrace part."
fi

if [[ $FTRACE -eq 1 ]]; then
    ftrace_sampler setup
fi

# Enable trace and start running the command
(sleep 5; eval $CMD) &
CPID=$!
echo "Run command '$CMD'(ppid=$$ pid=$CPID) and enable tracing..."

if [[ $FTRACE -eq 1 ]]; then
    ftrace_sampler start $CPID
fi

NET_PID=
if [[ $NET -eq 1 ]]; then
    net_sampler "$SS_OUTPUT" "$NETSTAT_OUTPUT" "$NET_PERIOD" &
    NET_PID=$!
fi

# Stop error exit temporary to make sure we can get the return code of the command
set +e
wait $CPID
ret=$?
set -e
echo "Command '$CMD' finished. Return code: $ret"

# Stop the sampler and output the result
if [[ -n "$NET_PID" ]]; then
    kill "$NET_PID" 2>/dev/null || true
    wait "$NET_PID" 2>/dev/null || true
    echo "Network sampler stopped. ss=$SS_OUTPUT netstat=$NETSTAT_OUTPUT"
fi

if [[ $FTRACE -eq 1 ]]; then
    ftrace_sampler stop
    echo "ftrace sampler stopped. Output: $FTRACE_OUTPUT"
fi

echo "Done. Please find $OUTPUT for the trace log and network status."
