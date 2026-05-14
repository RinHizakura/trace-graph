from perfetto.trace_builder.proto_builder import StreamingTraceProtoBuilder
from perfetto.protos.perfetto.trace.perfetto_trace_pb2 import TrackEvent


class PerfettoTraceFile:

    def __init__(self, filename):
        self._file = open(filename, "wb")
        self._builder = StreamingTraceProtoBuilder(self._file)
        self._seq_id = 1
        self._next_uuid = 1
        self._tracks = {}  # str key -> uuid

    def close(self):
        self._file.close()

    def _alloc_uuid(self):
        u = self._next_uuid
        self._next_uuid += 1
        return u

    def make_track(self, key, name=None, parent_key=None, counter=False):
        """Create or fetch a generic named track identified by a string key.

        Tracks form a tree via `parent_key`. If a referenced parent does not
        yet exist, it is auto-created as a self-named track. Pass
        `counter=True` to mark the track as a counter track.
        """
        if key in self._tracks:
            return self._tracks[key]

        parent_uuid = None
        if parent_key is not None:
            parent_uuid = self.make_track(parent_key)

        uuid = self._alloc_uuid()
        packet = self._builder.create_packet()
        packet.track_descriptor.uuid = uuid
        packet.track_descriptor.name = name if name is not None else key
        if parent_uuid is not None:
            packet.track_descriptor.parent_uuid = parent_uuid
        if counter:
            packet.track_descriptor.counter.SetInParent()
        self._builder.write_packet(packet)
        self._tracks[key] = uuid
        return uuid

    def add_counter_event(self, track_uuid, timestamp, value):
        packet = self._builder.create_packet()
        packet.timestamp = timestamp
        packet.track_event.type = TrackEvent.TYPE_COUNTER
        packet.track_event.track_uuid = track_uuid
        if isinstance(value, float):
            packet.track_event.double_counter_value = value
        else:
            packet.track_event.counter_value = value
        packet.trusted_packet_sequence_id = self._seq_id
        self._builder.write_packet(packet)

    def add_instant_event(self, track_uuid, name, timestamp, info):
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

    def add_complete_event(self, track_uuid, name, timestamp, dur, info):
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
