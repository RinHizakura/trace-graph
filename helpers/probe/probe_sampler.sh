#!/usr/bin/env bash
# Register kprobes for one or more kernel functions and sample their hit
# counts from /sys/kernel/tracing/kprobe_profile into an @TS-framed raw file.
# Parsing is deferred to helpers/probe/probe_parser.py so the sampling loop
# stays cheap. Designed to be run in the background by `tracer.sh -t`; loops
# until terminated.
#
# Usage:
#   probe_sampler.sh -o FILE -f FUNC [-f FUNC ...] [-p PERIOD]

OUT=
PERIOD=1
FUNCS=()

print_help()
{
    cat <<EOF
Usage: $(basename "$0") -o FILE -f FUNC [-f FUNC ...] [-p PERIOD]
  -o FILE    raw output file (@TS-framed kprobe_profile snapshots)
  -f FUNC    kernel function symbol to probe (repeatable)
  -p PERIOD  seconds between samples (default: 1)
  -h         show this help
EOF
}

while getopts ":o:p:f:h" opt; do
    case $opt in
        o) OUT="$OPTARG";;
        p) PERIOD="$OPTARG";;
        f) FUNCS+=("$OPTARG");;
        h) print_help; exit 0;;
        ?) print_help; exit 1;;
    esac
done
shift $((OPTIND - 1))

if [ -z "$OUT" ]; then
    echo "Error: -o FILE is required" >&2
    exit 1
fi
if [ ${#FUNCS[@]} -eq 0 ]; then
    echo "Error: at least one -f FUNC is required" >&2
    exit 1
fi
if [ "$EUID" -ne 0 ]; then
    echo "Error: must run as root" >&2
    exit 1
fi

TRACEFS=/sys/kernel/tracing
[ -d "$TRACEFS/events" ] || TRACEFS=/sys/kernel/debug/tracing

# Sanitize a symbol into a kprobe event name (kprobe events disallow some chars).
# Use printf to avoid the trailing newline echo would inject.
sanitize() { printf '%s' "$1" | tr -c '[:alnum:]_' '_'; }

# kprobe_profile reports event names without their group, so we make each
# event name PID-unique to keep concurrent / leaked-from-previous-run probes
# from colliding in the output.
GROUP="tg_probe_$$"
NAMES=()
HEADER="@PROBES"
for func in "${FUNCS[@]}"; do
    name="$(sanitize "$func")_p$$"
    NAMES+=("$name")
    HEADER="$HEADER ${func}=${name}"
    if ! printf 'p:%s/%s %s\n' "$GROUP" "$name" "$func" \
            >> "$TRACEFS/kprobe_events" 2>/dev/null; then
        echo "Error: failed to add kprobe for $func" >&2
        exit 1
    fi
    echo 1 > "$TRACEFS/events/${GROUP}/${name}/enable"
done

mkdir -p "$(dirname "$OUT")"
# Header records the func -> kprobe-event-name mapping the parser will need.
echo "$HEADER" > "$OUT"

cleanup()
{
    for name in "${NAMES[@]}"; do
        echo 0 > "$TRACEFS/events/${GROUP}/${name}/enable" 2>/dev/null || true
        printf -- '-:%s/%s\n' "$GROUP" "$name" \
            >> "$TRACEFS/kprobe_events" 2>/dev/null || true
    done
}
trap cleanup EXIT
trap 'exit 0' INT TERM HUP

# Sample inline so kill on this script tears down the whole tree without
# orphaning a sample-loop subshell or its sleep child.
while true; do
    ts=$(awk '{print $1}' /proc/uptime)
    {
        echo "@TS $ts"
        cat "$TRACEFS/kprobe_profile" 2>/dev/null || true
    } >> "$OUT"
    sleep "$PERIOD"
done
