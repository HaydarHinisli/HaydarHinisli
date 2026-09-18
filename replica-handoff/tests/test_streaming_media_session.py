"""Sprint 2: MediaStreamSession — track-separated identity/sequence diagnostics.
Covers requirement 3: missing/duplicate/out-of-order chunks, reconnects, audio gaps.
"""
import base64

from app.streaming import mulaw
from app.streaming.media_stream_session import INBOUND, OUTBOUND, MediaStreamSession


def _media(track, chunk, timestamp, seq, payload=None):
    payload = payload or (bytes([mulaw.SILENCE_BYTE]) * 160)
    return {
        'event': 'media', 'sequenceNumber': str(seq),
        'media': {'track': track, 'chunk': str(chunk), 'timestamp': str(timestamp), 'payload': base64.b64encode(payload).decode()},
    }


def _start(stream_sid, call_sid, seq=1, custom_parameters=None):
    return {'event': 'start', 'sequenceNumber': str(seq), 'start': {
        'streamSid': stream_sid, 'callSid': call_sid, 'customParameters': custom_parameters or {},
    }}


def test_start_sets_identity_and_custom_parameters():
    s = MediaStreamSession()
    s.consume_start(_start('MZ1', 'CA1', custom_parameters={'replica_call_id': '42'}))
    assert s.stream_sid == 'MZ1'
    assert s.call_sid == 'CA1'
    assert s.custom_parameters == {'replica_call_id': '42'}


def test_normal_sequential_chunks_are_all_ok():
    s = MediaStreamSession()
    s.consume_start(_start('MZ1', 'CA1'))
    for i in range(1, 6):
        r = s.consume_media(_media(INBOUND, i, i * 20, i + 1))
        assert r['chunk_status'] == 'ok'
    assert s.tracks[INBOUND].missing_chunks == 0
    assert s.tracks[INBOUND].duplicate_chunks == 0
    assert s.tracks[INBOUND].out_of_order_chunks == 0


def test_missing_chunk_is_detected_and_counted():
    s = MediaStreamSession()
    s.consume_start(_start('MZ1', 'CA1'))
    s.consume_media(_media(INBOUND, 1, 0, 2))
    r = s.consume_media(_media(INBOUND, 5, 80, 3))  # skipped 2, 3, 4
    assert r['chunk_status'] == 'missing_before'
    assert s.tracks[INBOUND].missing_chunks == 3


def test_duplicate_chunk_is_detected_and_does_not_inflate_missing_count():
    s = MediaStreamSession()
    s.consume_start(_start('MZ1', 'CA1'))
    s.consume_media(_media(INBOUND, 1, 0, 2))
    s.consume_media(_media(INBOUND, 2, 20, 3))
    r = s.consume_media(_media(INBOUND, 2, 20, 4))  # exact repeat
    assert r['chunk_status'] == 'duplicate'
    assert s.tracks[INBOUND].duplicate_chunks == 1
    assert s.tracks[INBOUND].missing_chunks == 0


def test_out_of_order_chunk_arriving_late_is_detected():
    s = MediaStreamSession()
    s.consume_start(_start('MZ1', 'CA1'))
    s.consume_media(_media(INBOUND, 1, 0, 2))
    s.consume_media(_media(INBOUND, 2, 20, 3))
    s.consume_media(_media(INBOUND, 3, 40, 4))
    r = s.consume_media(_media(INBOUND, 1, 60, 5))  # chunk 1 arrives again, late, out of order
    assert r['chunk_status'] == 'duplicate'  # chunk 1 was already seen -> duplicate, not out-of-order
    # a genuinely never-seen-but-lower chunk number IS out-of-order:
    s2 = MediaStreamSession()
    s2.consume_start(_start('MZ2', 'CA2'))
    s2.consume_media(_media(INBOUND, 5, 0, 2))  # starts at 5 (gap before it, but nothing "missing" yet since it's first)
    r2 = s2.consume_media(_media(INBOUND, 3, 20, 3))  # 3 < 5, never seen -> out of order
    assert r2['chunk_status'] == 'out_of_order'


def test_two_tracks_are_tracked_completely_independently():
    s = MediaStreamSession()
    s.consume_start(_start('MZ1', 'CA1'))
    s.consume_media(_media(INBOUND, 1, 0, 2))
    s.consume_media(_media(OUTBOUND, 1, 0, 3))
    s.consume_media(_media(OUTBOUND, 2, 20, 4))
    assert s.tracks[INBOUND].chunks_received == 1
    assert s.tracks[OUTBOUND].chunks_received == 2


def test_audio_gap_detected_on_large_timestamp_jump():
    s = MediaStreamSession()
    s.consume_start(_start('MZ1', 'CA1'))
    s.consume_media(_media(INBOUND, 1, 0, 2))
    r = s.consume_media(_media(INBOUND, 2, 500, 3))  # jump of 500ms, way more than 2x20ms
    assert r['is_gap'] is True
    assert s.tracks[INBOUND].audio_gap_events == 1
    assert s.tracks[INBOUND].total_audio_gap_ms > 0


def test_no_gap_for_normal_consecutive_frame_timing():
    s = MediaStreamSession()
    s.consume_start(_start('MZ1', 'CA1'))
    s.consume_media(_media(INBOUND, 1, 0, 2))
    r = s.consume_media(_media(INBOUND, 2, 20, 3))
    assert r['is_gap'] is False


def test_reconnect_detected_via_new_stream_sid_and_resets_track_state():
    s = MediaStreamSession()
    s.consume_start(_start('MZ1', 'CA1'))
    s.consume_media(_media(INBOUND, 1, 0, 2))
    s.consume_media(_media(INBOUND, 2, 20, 3))
    assert s.tracks[INBOUND].chunks_received == 2

    s.consume_start(_start('MZ2', 'CA1', seq=1))  # same call, new stream (reconnect)
    assert s.reconnect_count == 1
    assert s.tracks[INBOUND].chunks_received == 0  # fresh track state for the new stream
    # chunk numbering restarts cleanly for the new stream without false "missing" noise
    r = s.consume_media(_media(INBOUND, 1, 0, 2))
    assert r['chunk_status'] == 'ok'


def test_processing_lag_grows_when_consumer_falls_behind_real_time():
    """Backpressure signal (requirement 3): if wall-clock processing time falls
    behind the nominal in-stream audio timestamp, the lag must grow — this is what
    lets an operator detect REPLICA falling behind real-time audio delivery."""
    s = MediaStreamSession()
    s.consume_start(_start('MZ1', 'CA1'))
    r1 = s.consume_media(_media(INBOUND, 1, 0, 2), now_monotonic=100.0)
    assert r1['lag_ms'] == 0.0
    r2 = s.consume_media(_media(INBOUND, 2, 20, 3), now_monotonic=100.1)  # 100ms wall time for 20ms of audio
    r3 = s.consume_media(_media(INBOUND, 3, 40, 4), now_monotonic=100.3)
    assert r2['lag_ms'] > r1['lag_ms']
    assert r3['lag_ms'] > r2['lag_ms']
    assert s.tracks[INBOUND].max_processing_lag_ms == r3['lag_ms']


def test_processing_lag_stays_near_zero_when_consumer_keeps_up():
    s = MediaStreamSession()
    s.consume_start(_start('MZ1', 'CA1'))
    r1 = s.consume_media(_media(INBOUND, 1, 0, 2), now_monotonic=100.0)
    r2 = s.consume_media(_media(INBOUND, 2, 20, 3), now_monotonic=100.02)  # kept pace with the 20ms frame
    assert r2['lag_ms'] < 5.0


def test_diagnostics_summary_shape():
    s = MediaStreamSession()
    s.consume_start(_start('MZ1', 'CA1'))
    s.consume_media(_media(INBOUND, 1, 0, 2))
    summary = s.diagnostics_summary()
    assert summary['stream_sid'] == 'MZ1'
    assert summary['call_sid'] == 'CA1'
    assert 'inbound' in summary['tracks'] and 'outbound' in summary['tracks']
