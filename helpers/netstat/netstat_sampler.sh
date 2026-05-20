#!/usr/bin/env bash
# Sample /proc/net/netstat into an @TS-framed raw file. Parsing is deferred to
# scripts/netstat_parser.py so the sampling loop stays cheap. Designed to be
# run in the background by `tracer.sh -t`; loops until terminated.
#
# Usage:
#   netstat_sampler.sh -o FILE [-p PERIOD]

OUT=
PERIOD=1

print_help()
{
    cat <<EOF
Usage: $(basename "$0") -o FILE [-p PERIOD]
  -o FILE    raw output file (@TS-framed /proc/net/netstat snapshots)
  -p PERIOD  seconds between samples (default: 1)
  -h         show this help
EOF
}

while getopts ":o:p:h" opt; do
    case $opt in
        o) OUT="$OPTARG";;
        p) PERIOD="$OPTARG";;
        h) print_help; exit 0;;
        ?) print_help; exit 1;;
    esac
done
shift $((OPTIND - 1))

if [ -z "$OUT" ]; then
    echo "Error: -o FILE is required" >&2
    exit 1
fi

mkdir -p "$(dirname "$OUT")"

sample_loop()
{
    while true; do
        local ts
        ts=$(awk '{print $1}' /proc/uptime)
        {
            echo "@TS $ts"
            cat /proc/net/netstat
        } >> "$OUT"
        sleep "$PERIOD"
    done
}

sample_loop &
SAMPLER_PID=$!

cleanup()
{
    kill "$SAMPLER_PID" 2>/dev/null || true
    wait "$SAMPLER_PID" 2>/dev/null || true
}

trap 'cleanup; exit 0' INT TERM
wait "$SAMPLER_PID"
