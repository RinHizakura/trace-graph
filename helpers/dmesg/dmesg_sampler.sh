#!/usr/bin/env bash
# Stream the kernel log (/dev/kmsg) into a raw file. Each record already
# carries a microseconds-since-boot timestamp, so no @TS framing is needed;
# parser/dmesg_parser.py turns each record into a Perfetto instant event.
# Designed to be run in the background by `tracer.sh -t`; runs until terminated.
#
# Usage:
#   dmesg_sampler.sh -o FILE

OUT=

print_help()
{
    cat <<EOF
Usage: $(basename "$0") -o FILE
  -o FILE    raw output file (/dev/kmsg records)
  -h         show this help
EOF
}

while getopts ":o:h" opt; do
    case $opt in
        o) OUT="$OPTARG";;
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

# cat blocks on /dev/kmsg waiting for new records (it replays the existing
# buffer first; the parser's start_ts filter drops the pre-command part).
cat /dev/kmsg > "$OUT" &
SAMPLER_PID=$!

cleanup()
{
    kill "$SAMPLER_PID" 2>/dev/null || true
    wait "$SAMPLER_PID" 2>/dev/null || true
}

trap 'cleanup; exit 0' INT TERM
wait "$SAMPLER_PID"
