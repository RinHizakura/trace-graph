import re

from perfetto.trace_builder.proto_builder import StreamingTraceProtoBuilder
from perfetto.protos.perfetto.trace.perfetto_trace_pb2 import TrackEvent


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
        self._file = open(filename, "wb")
        self._builder = StreamingTraceProtoBuilder(self._file)
        self._seq_id = 1
        self._next_uuid = 1
        self._next_pid = 1000
        self._process_tracks = {}  # cat -> (uuid, pid)
        self._thread_tracks = {}   # (cat, tid) -> uuid
        self._counter_tracks = {}  # (cat, counter_name) -> uuid

    def close(self):
        self._file.close()

    def _alloc_uuid(self):
        u = self._next_uuid
        self._next_uuid += 1
        return u

    def _process_track(self, cat):
        if cat not in self._process_tracks:
            uuid = self._alloc_uuid()
            pid = self._next_pid
            self._next_pid += 1
            packet = self._builder.create_packet()
            packet.track_descriptor.uuid = uuid
            packet.track_descriptor.process.pid = pid
            packet.track_descriptor.process.process_name = cat
            self._builder.write_packet(packet)
            self._process_tracks[cat] = (uuid, pid)
        return self._process_tracks[cat]

    def _thread_track(self, cat, tid, thread_name):
        key = (cat, tid)
        if key not in self._thread_tracks:
            (_, pid) = self._process_track(cat)
            uuid = self._alloc_uuid()
            packet = self._builder.create_packet()
            packet.track_descriptor.uuid = uuid
            packet.track_descriptor.thread.pid = pid
            packet.track_descriptor.thread.tid = tid
            packet.track_descriptor.thread.thread_name = thread_name
            self._builder.write_packet(packet)
            self._thread_tracks[key] = uuid
        return self._thread_tracks[key]

    def _counter_track(self, cat, counter_name):
        key = (cat, counter_name)
        if key not in self._counter_tracks:
            (parent_uuid, _) = self._process_track(cat)
            uuid = self._alloc_uuid()
            packet = self._builder.create_packet()
            packet.track_descriptor.uuid = uuid
            packet.track_descriptor.parent_uuid = parent_uuid
            packet.track_descriptor.name = counter_name
            packet.track_descriptor.counter.SetInParent()
            self._builder.write_packet(packet)
            self._counter_tracks[key] = uuid
        return self._counter_tracks[key]

    def ensure_thread_track(self, cat, tid, thread_name):
        self._thread_track(cat, tid, thread_name)

    def add_counter_event(self, cat, timestamp, counter_name, value):
        track_uuid = self._counter_track(cat, counter_name)
        packet = self._builder.create_packet()
        packet.timestamp = timestamp
        packet.track_event.type = TrackEvent.TYPE_COUNTER
        packet.track_event.track_uuid = track_uuid
        packet.track_event.counter_value = value
        packet.trusted_packet_sequence_id = self._seq_id
        self._builder.write_packet(packet)

    def add_instant_event(self, name, cat, timestamp, tid, thread_name, info):
        track_uuid = self._thread_track(cat, tid, thread_name)
        packet = self._builder.create_packet()
        packet.timestamp = timestamp
        packet.track_event.type = TrackEvent.TYPE_INSTANT
        packet.track_event.track_uuid = track_uuid
        packet.track_event.name = name
        if info:
            ann = packet.track_event.debug_annotations.add()
            ann.name = "info"
            ann.string_value = info
        packet.trusted_packet_sequence_id = self._seq_id
        self._builder.write_packet(packet)

    def add_complete_event(self, name, cat, timestamp, dur, tid, thread_name, info):
        track_uuid = self._thread_track(cat, tid, thread_name)

        packet = self._builder.create_packet()
        packet.timestamp = timestamp
        packet.track_event.type = TrackEvent.TYPE_SLICE_BEGIN
        packet.track_event.track_uuid = track_uuid
        packet.track_event.name = name
        if info:
            ann = packet.track_event.debug_annotations.add()
            ann.name = "info"
            ann.string_value = info
        packet.trusted_packet_sequence_id = self._seq_id
        self._builder.write_packet(packet)

        packet = self._builder.create_packet()
        packet.timestamp = timestamp + dur
        packet.track_event.type = TrackEvent.TYPE_SLICE_END
        packet.track_event.track_uuid = track_uuid
        packet.trusted_packet_sequence_id = self._seq_id
        self._builder.write_packet(packet)


def handle_sched_swtich_event(info, cpu, duration, timestamp):
    s = "[\w\<\>\-\.\:\/\(\) ]"
    regex = rf"prev_comm=({s}+) prev_pid=([0-9\-]+) prev_prio=[0-9\-]+ prev_state=([a-zA-Z\+]+) "
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

def handle_cpu_idle_event(info):
    d = re.findall(r"state=(\d+) cpu_id=(\d+)", info)[0]
    state, cpu_id = int(d[0]), int(d[1])
    if 4294967295 == state:
        state = 0
    else:
        state += 1
    return (f"CPU{cpu_id:03d}", state)


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

    events = set()
    cpu_track_events = set(["sched_switch", "cpu_idle", "irq_handler", "softirq", "device_pm_callback", "block_rq"])

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

        if event in cpu_track_events:
            tid = cpu
            thread_name = f"CPU{cpu}"
        else:
            tid = process_id
            thread_name = name

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

        if exit_info:
            (slice_name, start, dur) = exit_info
            trace.add_complete_event(slice_name, event, start, dur, tid, thread_name, info)
        elif counter:
            counter_name, value = counter
            trace.add_counter_event(event, timestamp, counter_name, value)
        else:
            trace.add_instant_event(name, event, timestamp, tid, thread_name, info)

    # Pre-register tracks so all CPUs/processes that appeared show up in the UI even
    # if a particular event category had no entries for them.
    for event in events:
        if event in cpu_track_events:
            for c in range(cpu_max + 1):
                trace.ensure_thread_track(event, c, f"CPU{c}")
        else:
            for process_id, name in pid_map.items():
                trace.ensure_thread_track(event, process_id, name)
