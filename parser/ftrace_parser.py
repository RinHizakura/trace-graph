import re


def _findall_first(pattern, line):
    try:
        return re.findall(pattern, line)[0]
    except IndexError:
        print(f"[ERROR] No match for pattern {pattern!r} in line: {line}")
        raise


class DurationTracker:

    def __init__(self):
        self.data = {}

    def entry(self, name, data):
        if self.data.get(name) != None:
            print(
                f"[WARN] Missing the paired end event for {name}, data({self.data[name]}) will be ignored"
            )

        # The data should be a pair of (name, timestamp)
        assert isinstance(data, tuple)
        self.data[name] = data
        return True

    def exit(self, name, timestamp):
        if not self.data.get(name):
            print(
                f"[WARN] Missing the paired start event of {name}, fallback to instant event"
            )
            return None

        data = self.data[name]
        self.data.pop(name)
        name = data[0]
        start = data[1]
        dur = timestamp - start
        return (name, start, dur)


def handle_sched_swtich_event(info, cpu, duration, timestamp):
    s = r"[\w<>\-.:/() ]"
    regex = (
        rf"prev_comm=({s}+) prev_pid=(-?\d+) prev_prio=\S+ prev_state=(\S+) "
        rf"==> next_comm=({s}+) next_pid=(-?\d+) next_prio=\S+"
    )
    sched = _findall_first(regex, info)
    prev, prev_pid, prev_state, cur, cur_pid = (
        sched[0],
        int(sched[1]),
        sched[2],
        sched[3],
        int(sched[4]),
    )

    pid = cpu
    event = "sched"

    # Ignore the swapper thread
    if not "swapper" in cur:
        duration.entry(f"{event}-{cur_pid}@{cpu}", (cur, timestamp))

    if not "swapper" in prev:
        return duration.exit(f"{event}-{prev_pid}@{cpu}", timestamp)
    else:
        return None


def handle_cpu_idle_event(info):
    d = _findall_first(r"state=(\d+) cpu_id=(\d+)", info)
    state, cpu_id = int(d[0]), int(d[1])
    if 4294967295 == state:
        state = 0
    else:
        state += 1
    return (f"CPU{cpu_id:03d}", state)


def handle_bio_start_event(info, cpu, duration, timestamp):
    d = _findall_first(
        r"(\d+),(\d+) (\w+) (\d+) \((\w*)\) (\d+) \+ (\d+) [\w,]+ \[([\w/:-]+)\]",
        info,
    )
    major, minor, rwbs, byte, cmd, sector, nr_sector, comm = (
        int(d[0]),
        int(d[1]),
        d[2],
        int(d[3]),
        d[4],
        int(d[5]),
        int(d[6]),
        d[7],
    )
    key = f"{major}_{minor}_{sector}_{nr_sector}"
    data = f"Comm={comm}"
    duration.entry(f"block_rq-{key}@{cpu}", (data, timestamp))


def handle_bio_end_event(info, cpu, duration, timestamp):
    d = _findall_first(
        r"(\d+),(\d+) (\w+) \((\w*)\) (\d+) \+ (\d+) [\w,]+ \[(\d+)\]", info
    )
    major, minor, rwbs, cmd, sector, nr_sector, err = (
        int(d[0]),
        int(d[1]),
        d[2],
        d[3],
        int(d[4]),
        int(d[5]),
        int(d[6]),
    )
    key = f"{major}_{minor}_{sector}_{nr_sector}"
    exit_info = duration.exit(f"block_rq-{key}@{cpu}", timestamp)
    return exit_info


def handle_irq_handler_start_event(info, cpu, duration, timestamp):
    d = _findall_first(r"irq=(\d+) name=([\w.]+)", info)
    key, data = int(d[0]), d[1]
    duration.entry(f"irq_handler-{key}@{cpu}", (data, timestamp))


def handle_irq_handler_end_event(info, cpu, duration, timestamp):
    key = int(_findall_first(r"irq=(\d+)", info))
    exit_info = duration.exit(f"irq_handler-{key}@{cpu}", timestamp)
    return exit_info


def handle_softirq_start_event(info, cpu, duration, timestamp):
    d = _findall_first(r"vec=(\d+) \[action=([A-Z_]+)\]", info)
    key, data = int(d[0]), d[1]
    duration.entry(f"softirq-{key}@{cpu}", (data, timestamp))


def handle_softirq_end_event(info, cpu, duration, timestamp):
    key = int(_findall_first(r"vec=(\d+)", info))
    exit_info = duration.exit(f"softirq-{key}@{cpu}", timestamp)
    return exit_info


def parse_ftrace(trace, file):
    # ftrace line: name-pid (tgid) [cpu] stat time: event: info
    name = r"[\w<>\-.:/() ]"
    regex = rf"({name}+)-(\d+)\s+(\([\d -]+\))\s+\[(\d+)\]\s+([\w.]+)\s+(\d+\.\d+):\s+(\w+):\s(.+)"

    events = set()
    cpu_track_events = set(
        [
            "sched_switch",
            "cpu_idle",
            "irq_handler",
            "softirq",
            "device_pm_callback",
            "block_rq",
        ]
    )

    pid_map = {}

    # Record the max CPU number during parsing of the ftrace event
    cpu_max = 0
    duration = DurationTracker()

    for line in file:
        sample = line.strip()

        items = re.findall(regex, sample)
        if not items:
            continue

        items = items[0]
        # Define every field of the ftrace sample
        name, process_id, tgid, cpu, stat, time, event, info = (
            items[0],
            int(items[1]),
            items[2],
            int(items[3]),
            items[4],
            float(items[5]),
            items[6],
            items[7],
        )

        events.add(event)
        pid_map[process_id] = name

        cpu_max = max(cpu, cpu_max)

        # Perfetto wants nanoseconds
        timestamp = int(time * 10**9)

        counter = None
        goto_next = False
        exit_info = None
        if event == "sched_switch":
            exit_info = handle_sched_swtich_event(info, cpu, duration, timestamp)
            goto_next = False if exit_info else True
        elif event == "cpu_idle":
            counter = handle_cpu_idle_event(info)
        elif "block_rq" in event:
            if event == "block_rq_insert":
                event = "block_rq"
                handle_bio_start_event(info, cpu, duration, timestamp)
                goto_next = True
            elif event == "block_rq_complete":
                event = "block_rq"
                exit_info = handle_bio_end_event(info, cpu, duration, timestamp)
        elif "irq_handler" in event:
            if event == "irq_handler_entry":
                event = "irq_handler"
                handle_irq_handler_start_event(info, cpu, duration, timestamp)
                goto_next = True
            elif event == "irq_handler_exit":
                event = "irq_handler"
                exit_info = handle_irq_handler_end_event(info, cpu, duration, timestamp)
        elif "softirq" in event:
            if event == "softirq_entry":
                event = "softirq"
                handle_softirq_start_event(info, cpu, duration, timestamp)
                goto_next = True
            elif event == "softirq_exit":
                event = "softirq"
                exit_info = handle_softirq_end_event(info, cpu, duration, timestamp)

        if goto_next:
            continue

        if event in cpu_track_events:
            track_key = f"{event}/CPU{cpu}"
            track_uuid = trace.make_track(
                track_key, name=f"CPU{cpu}", parent_key=event
            )
        else:
            track_key = f"thread:{process_id}"
            track_uuid = trace.make_track(track_key, name=f"{name}-{process_id}")

        if exit_info:
            (slice_name, start, dur) = exit_info
            trace.add_complete_event(track_uuid, slice_name, start, dur, info)
        elif counter:
            counter_name, value = counter
            counter_uuid = trace.make_track(
                f"{event}/{counter_name}",
                name=counter_name,
                parent_key=event,
                counter=True,
            )
            trace.add_counter_event(counter_uuid, timestamp, value)
        else:
            trace.add_instant_event(track_uuid, name, timestamp, info)
