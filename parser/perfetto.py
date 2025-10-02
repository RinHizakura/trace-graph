import re
from datetime import datetime, timedelta


# FIXME: This is a Naive id allocator. We assume the event count won't exceed
# the numerical system range, so never reclaim the unused id.
class TrackIdAllocator:

    def __init__(self, start_pid):
        self.map = {}
        self.next_pid = start_pid

    def get(self, name):
        assign = False
        if not name in self.map:
            self.map[name] = self.next_pid
            self.next_pid += 1
            assign = True
        return assign, self.map[name]


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


class PerfettoTraceFile:

    def __init__(self, filename):
        self.output = open(filename, "w")
        self.track_ids = TrackIdAllocator(1000)

    def get_track_id(self, cat):
        assign, pid = self.track_ids.get(cat)
        if assign:
            self.add_process_name(cat, pid)
        return pid

    def start(self):
        self.output.write("{\n")

    def end(self):
        self.output.write("}\n")
        self.output.close()

    def trace_event_start(self):
        self.output.write('"traceEvents":[\n')

    def trace_event_end(self):
        self.output.write("]\n")

    def add_counter_event(self, name, cat, timestamp, data):
        pid = self.get_track_id(cat)

        self.output.write(
            '{"name": "%s", "ph": "C", "ts": %d, "cat": "%s", "pid": %d, "args": {%s}}\n'
            % (name, timestamp, cat, pid, data)
        )

    def add_instant_event(self, name, cat, timestamp, tid, data):
        pid = self.get_track_id(cat)

        self.output.write(
            '{"name": "%s", "ph": "i", "ts": %d, "cat": "%s", "pid": %d, "tid": %d, "s": "t", "args": {%s}}\n'
            % (name, timestamp, cat, pid, tid, data)
        )

    def add_complete_event(self, name, cat, timestamp, dur, tid, data):
        pid = self.get_track_id(cat)

        self.output.write(
            '{"name": "%s", "ph": "X", "ts": %d, "dur": %d, "cat": "%s", "pid": %d, "tid": %d, "args": {%s}}\n'
            % (name, timestamp, dur, cat, pid, tid, data)
        )

    def add_process_name(self, name, pid):
        self.output.write(
            '{"name": "process_name", "ph": "M", "pid": %d, "args": {"name" : "%s"}}\n'
            % (pid, name)
        )

    def add_thread_name(self, name, pid, tid):
        self.output.write(
            '{"name": "thread_name", "ph": "M", "pid": %d, "tid": %d, "args": {"name" : "%s"}}\n'
            % (pid, tid, name)
        )

    def add_process_sortidx(self, idx, pid):
        self.output.write(
            '{"name": "process_sort_index", "ph": "M", "pid": %d, "args": {"sort_index" : %d}}\n'
            % (pid, idx)
        )


def handle_sched_swtich_event(info, cpu, duration, timestamp):
    s = "[\w\<\>\-\.\:\/\(\) ]"
    regex = rf"prev_comm=({s}+) prev_pid=([0-9\-]+) prev_prio=[0-9\-]+ prev_state=([A-Z\+]+) "
    regex += rf"==> next_comm=({s}+) next_pid=([0-9\-]+) next_prio=[0-9\-]+"
    sched = re.findall(regex, info)[0]
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


def handle_bio_start_event(info, cpu, duration, timestamp):
    d = re.findall(r"(\d+),(\d+) (\w+) (\d+) \((\w*)\) (\d+) \+ (\d+) \[([\w\/:-]+)\]", info)[
        0
    ]
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
    d = re.findall(r"(\d+),(\d+) (\w+) \((\w*)\) (\d+) \+ (\d+) \[(\d+)\]", info)[0]
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
    d = re.findall(r"irq=([0-9]+) name=([0-9a-zA-Z_\.]+)", info)[0]
    key, data = int(d[0]), d[1]
    duration.entry(f"irq_handler-{key}@{cpu}", (data, timestamp))

def handle_irq_handler_end_event(info, cpu, duration, timestamp):
    key = int(re.findall(r"irq=([0-9]+)", info)[0])
    exit_info = duration.exit(f"irq_handler-{key}@{cpu}", timestamp)
    return exit_info

def handle_softirq_start_event(info, cpu, duration, timestamp):
    d = re.findall(r"vec=([0-9]+) \[action=([A-Z_]+)\]", info)[0]
    key, data = int(d[0]), d[1]
    duration.entry(f"softirq-{key}@{cpu}", (data, timestamp))

def handle_softirq_end_event(info, cpu, duration, timestamp):
    key = int(re.findall(r"vec=([0-9]+)", info)[0])
    exit_info = duration.exit(f"softirq-{key}@{cpu}", timestamp)
    return exit_info

def parse_ftrace(trace, file):
    # name
    s0 = "[\w\<\>\-\.\:\/\(\) ]"
    # stat
    s4 = "[\w\.]"
    # event
    s6 = "[\w]"
    # info
    s7 = "[\<\>\(\)\[\]a-zA-Z0-9@\+\-\_\.\:\/=, ]"

    # Assume the ftrace format should follow this regular expression
    regex = rf"({s0}+)-(\d+)\s+(\([\d -]+\))\s+\[(\d+)\]\s+({s4}+)\s+(\d+\.\d+):\s+({s6}+):\s({s7}+)"

    dur_events = [
        "sched_switch",
        "suspend_resume",
        "irq_handler",
        "softirq",
        "device_pm_callback",
        "block_rq",
    ]

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

        cpu_max = max(cpu, cpu_max)

        # From seconds to milliseconds
        timestamp = int(time * 10**6)

        goto_next = False
        exit_info = None
        if event == "sched_switch":
            tid = cpu
            exit_info = handle_sched_swtich_event(info, cpu, duration, timestamp)
            goto_next = False if exit_info else True
        elif "block_rq" in event:
            tid = cpu
            if event == "block_rq_insert":
                event = "block_rq"
                handle_bio_start_event(info, cpu, duration, timestamp)
                goto_next = True
            elif event == "block_rq_complete":
                event = "block_rq"
                exit_info = handle_bio_end_event(info, cpu, duration, timestamp)
        elif "irq_handler" in event:
            tid = cpu
            if event == "irq_handler_entry":
                event = "irq_handler"
                handle_irq_handler_start_event(info, cpu, duration, timestamp)
                goto_next = True
            elif event == "irq_handler_exit":
                event = "irq_handler"
                exit_info = handle_irq_handler_end_event(info, cpu, duration, timestamp)
        elif "softirq" in event:
            tid = cpu
            if event == "softirq_entry":
                event = "softirq"
                handle_softirq_start_event(info, cpu, duration, timestamp)
                goto_next = True
            elif event == "softirq_exit":
                event = "softirq"
                exit_info = handle_softirq_end_event(info, cpu, duration, timestamp)
        else:
            tid = process_id

        if goto_next:
            continue

        if exit_info:
            (name, start, dur) = exit_info
            trace.add_complete_event(name, event, start, dur, tid, f'"info": "{info}"')
        else:
            trace.add_instant_event(name, event, timestamp, tid, f'"info": "{info}"')

    # For the type of events that can have duration information from ftrace, we use CPU as
    # their tid, so they will be drawed to different subtrack according to CPU number.
    # Assign the name for these subtrack for better visualization.
    for event in dur_events:
        track_id = trace.get_track_id(event)
        for c in range(cpu_max + 1):
            trace.add_thread_name(f"CPU{c}", track_id, c)
