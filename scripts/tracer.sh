#!/usr/bin/env bash
set -e

SYSFS_TRACE=/sys/kernel/debug/tracing

function enable_event()
{
    EVENT=$1
    echo write enable to $SYSFS_TRACE/events/$EVENT/enable
    echo 1 > $SYSFS_TRACE/events/$EVENT/enable
}

function print_help()
{
    usage="$(basename "$0") [-h] [-o output] [-e event] [-b] [-i] [-s] [-p]  \n
where:                                                 \n
    -h  show this help text                            \n
    -o  specific the output name of ftrace file        \n
    -e  select the event for ftrace                    \n
    -b  select the bio event for ftrace                \n
    -i  select the irq event for ftrace                \n
    -s  select the sched event for ftrace              \n
    -p  trace only the run command and its childs' PID"

    echo -e $usage
}

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root user."
    exit 1
fi

OUTPUT="/tmp/trace_log"
EVENT=$SYSFS_TRACE/events
EVENT_LIST=()
PID=0
while getopts ":o:e:bisph" opt
do
    case $opt in
        o)
            OUTPUT=("$OPTARG");;
        e)
            EVENT_LIST+=("$OPTARG");;
        b)
            EVENT_LIST+=("block/block_rq_insert" "block/block_rq_complete");;
        i)
            EVENT_LIST+=("irq/irq_handler_entry" "irq/irq_handler_exit");
            EVENT_LIST+=("irq/softirq_entry" "irq/softirq_exit");;
        s)
            EVENT_LIST+=("sched/sched_switch");;
        p)
            PID=1;;
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

# Clean the trace buffer at start
echo 0 > $SYSFS_TRACE/trace

# Disable the trace first before we setup everything
echo 0 > $SYSFS_TRACE/events/enable
echo 0 > $SYSFS_TRACE/tracing_on

if [[ ${EVENT_LIST[@]} ]]; then
    for ev in ${EVENT_LIST[@]}; do
        echo Enable event $ev
        enable_event $ev
    done
else
    echo Enable all events
    enable_event ""
fi

# Choose the tracer with target setting
echo event-fork > $SYSFS_TRACE/trace_options
echo 1 > $SYSFS_TRACE/options/record-tgid
echo nop > $SYSFS_TRACE/current_tracer

# Enable trace and start running the command
(sleep 5; eval $CMD) &
CPID=$!
echo "Run command '$CMD'(ppid=$$ pid=$CPID) and enable tracing..."

# Extra setting to focus on the process from the command
if [[ $PID -eq 1 ]]; then
    # Add child pid to filter to start tracing it
    echo $CPID > $SYSFS_TRACE/set_event_pid
fi

echo 1 > $SYSFS_TRACE/tracing_on
(cat $SYSFS_TRACE/trace_pipe > $OUTPUT) &
TPID=$!
wait $CPID
echo 0 > $SYSFS_TRACE/tracing_on

# Output result
kill $TPID
echo "Done. Please 'sudo cat $OUTPUT' for the result"

# Cleanup the change of ftrace
echo > $SYSFS_TRACE/set_event_pid
echo nop > $SYSFS_TRACE/current_tracer
echo 0 > $SYSFS_TRACE/events/enable
