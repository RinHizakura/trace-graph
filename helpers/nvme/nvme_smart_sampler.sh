#!/usr/bin/env bash
# Sample `nvme smart-log` for NVMe devices into an @TS-framed raw file.
# Parsing is deferred to nvme_parser.py. Designed to be run in the background
# by `tracer.sh`; loops until terminated.
#
# Usage:
#   nvme_sampler.sh -o FILE [-p PERIOD] [-d DEV ...]

OUT=
PERIOD=1
DEVS=()

print_help()
{
    cat <<EOF
Usage: $(basename "$0") -o FILE [-p PERIOD] [-d DEV ...]
  -o FILE    raw output file (@TS-framed nvme smart-log snapshots)
  -p PERIOD  seconds between samples (default: 1)
  -d DEV     NVMe device to sample, e.g. /dev/nvme0 (repeatable).
             If omitted, auto-detects /dev/nvme[0-9].
  -h         show this help
EOF
}

while getopts ":o:p:d:h" opt; do
    case $opt in
        o) OUT="$OPTARG";;
        p) PERIOD="$OPTARG";;
        d) DEVS+=("$OPTARG");;
        h) print_help; exit 0;;
        ?) print_help; exit 1;;
    esac
done
shift $((OPTIND - 1))

if [ -z "$OUT" ]; then
    echo "Error: -o FILE is required" >&2
    exit 1
fi

if ! command -v nvme &>/dev/null; then
    echo "Error: nvme-cli not found (install nvme-cli)" >&2
    exit 1
fi

if [ ${#DEVS[@]} -eq 0 ]; then
    mapfile -t DEVS < <(ls /dev/nvme[0-9] 2>/dev/null || true)
fi

if [ ${#DEVS[@]} -eq 0 ]; then
    echo "Error: no NVMe devices found" >&2
    exit 1
fi

mkdir -p "$(dirname "$OUT")"
{
    printf '@DEVS'
    for dev in "${DEVS[@]}"; do
        printf ' %s' "$(basename "$dev")"
    done
    printf '\n'
} > "$OUT"

sample_loop()
{
    while true; do
        local ts
        ts=$(awk '{print $1}' /proc/uptime)
        {
            echo "@TS $ts"
            for dev in "${DEVS[@]}"; do
                echo "@DEV $(basename "$dev")"
                nvme smart-log -o json "$dev" 2>/dev/null || echo '{}'
            done
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
