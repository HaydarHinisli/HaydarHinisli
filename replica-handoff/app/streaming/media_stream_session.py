"""Twilio Media Streams message parsing + per-track identity/sequence diagnostics
(Sprint 2). Replaces the earlier byte-counting stub (app/integrations/twilio_stream.py,
removed in this sprint) with something that actually separates the two speaker
channels and surfaces transport problems as transport problems — never silently
folded into ASR/SalesBrain behavior, per the explicit requirement that a missing
chunk or a reconnect must not be misread as "the prospect went quiet" or similar.

Wire format (documented assumption, see docs/PROVIDER_REFERENCES.md — this
environment cannot make a live connection to a real Twilio account to confirm
current wire behavior, so this MUST be confirmed against a real Media Stream before
pilot go-live): `connected`/`start`/`media`/`mark`/`stop` JSON messages;
`sequenceNumber` increments per message across the whole connection; `media.chunk`
increments per message WITHIN a track, starting at 1; `media.timestamp` is
milliseconds since the stream started. All three numeric fields arrive as JSON
strings in Twilio's actual payloads, not numbers — parsed defensively here (a
malformed value is a diagnostic anomaly, not a crash).

Correction (docs/DECISIONS.md ADR-063, red-team item 9): `media.track` values
`inbound`/`outbound` are deliberately left undocumented here as anything more than
opaque transport-layer labels — an earlier version of this comment asserted a
fixed inbound=prospect/outbound=seller identity, which was already WRONG for
REPLICA's own confirmed topology even before this correction (ADR-053 established
the opposite: inbound=seller/outbound=prospect for the outbound-sales-flow) and,
more importantly, is exactly the kind of second, uncoordinated place a track->role
assumption could silently drift out of sync with the real mapping. There is
exactly ONE place that mapping is defined: `app/streaming/speaker_mapping.py`'s
`SpeakerRoleResolver` — see that module's docstring for what these two track names
actually mean for REPLICA's supported call topology, and never infer a role from
the track name anywhere else, including here.
"""
from __future__ import annotations
import base64
import time
from dataclasses import dataclass, field

INBOUND = 'inbound'    # Twilio transport label only — see module docstring correction (ADR-063)
OUTBOUND = 'outbound'  # Twilio transport label only — see module docstring correction (ADR-063)
TRACKS = (INBOUND, OUTBOUND)


def _to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class TrackDiagnostics:
    """Sequence/identity bookkeeping for ONE track of ONE media stream connection.
    Every counter here is a transport-layer fact, deliberately kept separate from
    anything ASR- or SalesBrain-related."""
    track: str
    chunks_received: int = 0
    missing_chunks: int = 0
    duplicate_chunks: int = 0
    out_of_order_chunks: int = 0
    audio_gap_events: int = 0
    total_audio_gap_ms: float = 0.0
    bytes_received: int = 0
    highest_chunk_seen: int | None = field(default=None, repr=False)
    _seen_chunks: set[int] = field(default_factory=set, repr=False)
    last_media_timestamp_ms: float | None = None
    last_processing_lag_ms: float | None = None
    max_processing_lag_ms: float = 0.0

    # Twilio's nominal frame duration; used only to size the "is this a real audio
    # gap" threshold, not for anything ASR-relevant.
    _EXPECTED_FRAME_MS = 20.0
    _GAP_THRESHOLD_MULTIPLIER = 2.0

    def observe_chunk(self, chunk: int | None) -> str:
        """Returns one of 'ok' | 'missing_before' | 'duplicate' | 'out_of_order' |
        'unparseable'."""
        self.chunks_received += 1
        if chunk is None:
            return 'unparseable'
        if chunk in self._seen_chunks:
            self.duplicate_chunks += 1
            return 'duplicate'
        self._seen_chunks.add(chunk)
        if self.highest_chunk_seen is None or chunk == self.highest_chunk_seen + 1:
            self.highest_chunk_seen = chunk
            return 'ok'
        if chunk > self.highest_chunk_seen + 1:
            self.missing_chunks += chunk - self.highest_chunk_seen - 1
            self.highest_chunk_seen = chunk
            return 'missing_before'
        self.out_of_order_chunks += 1
        return 'out_of_order'

    def observe_timestamp(self, timestamp_ms: float | None) -> bool:
        """Returns True if this reading opened a new audio gap. A gap is a jump in
        Twilio's own in-stream media timestamp larger than a couple of nominal frame
        durations — real missing audio time, distinct from a missing sequence number
        (which could be a reordering, not a true gap)."""
        if timestamp_ms is None:
            self.last_media_timestamp_ms = None
            return False
        is_gap = False
        if self.last_media_timestamp_ms is not None:
            delta = timestamp_ms - self.last_media_timestamp_ms
            threshold = self._EXPECTED_FRAME_MS * self._GAP_THRESHOLD_MULTIPLIER
            if delta > threshold:
                self.audio_gap_events += 1
                self.total_audio_gap_ms += delta - self._EXPECTED_FRAME_MS
                is_gap = True
        self.last_media_timestamp_ms = timestamp_ms
        return is_gap

    def observe_processing_lag(self, lag_ms: float) -> None:
        """Backpressure signal: how far wall-clock processing has fallen behind the
        nominal in-stream audio time. A healthy consumer keeps this small and
        roughly constant; a growing value means REPLICA can't keep up with the
        real-time audio delivery rate."""
        self.last_processing_lag_ms = lag_ms
        self.max_processing_lag_ms = max(self.max_processing_lag_ms, lag_ms)

    def summary(self) -> dict:
        return {
            'track': self.track,
            'chunks_received': self.chunks_received,
            'missing_chunks': self.missing_chunks,
            'duplicate_chunks': self.duplicate_chunks,
            'out_of_order_chunks': self.out_of_order_chunks,
            'audio_gap_events': self.audio_gap_events,
            'total_audio_gap_ms': round(self.total_audio_gap_ms, 1),
            'bytes_received': self.bytes_received,
            'max_processing_lag_ms': round(self.max_processing_lag_ms, 1),
        }


@dataclass
class MediaStreamSession:
    """One Twilio Media Streams WebSocket connection. Tracks connection-level
    identity (`streamSid`, `callSid`) and per-track (`TrackDiagnostics`) state
    separately — inbound (prospect) and outbound (seller/agent) audio are never
    merged before ASR, so the central turn pipeline always knows which side of the
    conversation produced a given chunk/transcript.
    """
    stream_sid: str | None = None
    call_sid: str | None = None
    custom_parameters: dict = field(default_factory=dict)
    tracks: dict[str, TrackDiagnostics] = field(default_factory=lambda: {t: TrackDiagnostics(t) for t in TRACKS})
    reconnect_count: int = 0
    connection_sequence_missing: int = 0
    connection_sequence_duplicate: int = 0
    connection_sequence_out_of_order: int = 0
    _highest_connection_sequence: int | None = field(default=None, repr=False)
    _seen_connection_sequences: set[int] = field(default_factory=set, repr=False)
    _stream_started_monotonic: float | None = field(default=None, repr=False)

    def _observe_connection_sequence(self, seq: int | None) -> None:
        if seq is None:
            return
        if seq in self._seen_connection_sequences:
            self.connection_sequence_duplicate += 1
            return
        self._seen_connection_sequences.add(seq)
        if self._highest_connection_sequence is None or seq == self._highest_connection_sequence + 1:
            self._highest_connection_sequence = seq
            return
        if seq > self._highest_connection_sequence + 1:
            self.connection_sequence_missing += seq - self._highest_connection_sequence - 1
            self._highest_connection_sequence = seq
            return
        self.connection_sequence_out_of_order += 1

    def consume_start(self, message: dict) -> None:
        start = message.get('start', {})
        new_stream_sid = start.get('streamSid') or message.get('streamSid')
        if self.stream_sid is not None and new_stream_sid != self.stream_sid:
            # A new `start` for a streamSid we've already seen one for is a
            # reconnect — reset per-track sequence expectations (a fresh stream
            # starts its own chunk numbering) while keeping cumulative counters
            # for the connection-level diagnostics summary.
            self.reconnect_count += 1
            self.tracks = {t: TrackDiagnostics(t) for t in TRACKS}
            self._stream_started_monotonic = None
        self.stream_sid = new_stream_sid
        self.call_sid = start.get('callSid')
        self.custom_parameters = start.get('customParameters', {}) or {}
        self._observe_connection_sequence(_to_int(message.get('sequenceNumber')))

    def consume_media(self, message: dict, *, now_monotonic: float | None = None) -> dict:
        """Returns a dict: {'track', 'payload_bytes', 'chunk_status', 'is_gap',
        'lag_ms'} — the pure transport-layer facts about this one chunk, for the
        caller (the pipeline) to feed into VAD/ASR and diagnostics logging."""
        now_monotonic = time.monotonic() if now_monotonic is None else now_monotonic
        self._observe_connection_sequence(_to_int(message.get('sequenceNumber')))
        media = message.get('media', {})
        track_name = media.get('track', 'unknown')
        track = self.tracks.setdefault(track_name, TrackDiagnostics(track_name))

        chunk = _to_int(media.get('chunk'))
        chunk_status = track.observe_chunk(chunk)

        timestamp_ms = _to_int(media.get('timestamp'))
        is_gap = track.observe_timestamp(float(timestamp_ms) if timestamp_ms is not None else None)

        payload_b64 = media.get('payload', '')
        payload_bytes = b''
        if payload_b64:
            try:
                payload_bytes = base64.b64decode(payload_b64)
                track.bytes_received += len(payload_bytes)
            except (ValueError, TypeError):
                pass

        lag_ms = None
        if timestamp_ms is not None:
            if self._stream_started_monotonic is None:
                self._stream_started_monotonic = now_monotonic - (timestamp_ms / 1000.0)
            expected_monotonic = self._stream_started_monotonic + (timestamp_ms / 1000.0)
            lag_ms = max(0.0, (now_monotonic - expected_monotonic) * 1000.0)
            track.observe_processing_lag(lag_ms)

        return {
            'track': track_name, 'payload_bytes': payload_bytes, 'chunk_status': chunk_status,
            'is_gap': is_gap, 'lag_ms': lag_ms, 'timestamp_ms': timestamp_ms,
        }

    def consume_stop(self, message: dict) -> None:
        self._observe_connection_sequence(_to_int(message.get('sequenceNumber')))

    def diagnostics_summary(self) -> dict:
        return {
            'stream_sid': self.stream_sid,
            'call_sid': self.call_sid,
            'reconnect_count': self.reconnect_count,
            'connection_sequence_missing': self.connection_sequence_missing,
            'connection_sequence_duplicate': self.connection_sequence_duplicate,
            'connection_sequence_out_of_order': self.connection_sequence_out_of_order,
            'tracks': {name: track.summary() for name, track in self.tracks.items()},
        }
