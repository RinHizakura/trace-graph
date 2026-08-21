import re


def parse_dmesg_line(line):
    """Parse one /dev/kmsg record: "pri,seq,usec_since_boot[,flags...];message".

    Returns (level, time_sec, message) or None for continuation/garbage lines
    (continuation lines start with a space).
    """
    m = re.match(r"(\d+),\d+,(\d+),[^;]*;(.*)", line)
    if not m:
        return None
    pri, usec, msg = int(m[1]), int(m[2]), m[3].rstrip()
    # pri = facility << 3 | severity
    return (pri & 7, usec / 10**6, msg)


def parse_dmesg(trace, file, start_ts=None):
    # ponytail: kmsg timestamps come from the printk clock, which does not
    # advance during suspend; if the device suspends mid-trace they drift
    # from the boot-clock timeline the rest of the tracks use.
    track_uuid = None
    for line in file:
        parsed = parse_dmesg_line(line)
        if not parsed:
            continue
        level, time, msg = parsed
        if start_ts is not None and time < start_ts:
            continue
        if track_uuid is None:
            track_uuid = trace.make_track("dmesg", name="dmesg")
        # Perfetto wants nanoseconds
        trace.add_instant_event(track_uuid, msg, int(time * 10**9), f"level={level}")
