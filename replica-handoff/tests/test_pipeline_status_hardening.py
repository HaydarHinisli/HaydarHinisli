"""docs/DECISIONS.md ADR-063: red-team hardening items 3/4/9 — the analysis/
pipeline status pushed independently of the Twilio call's own state, runtime
fail-closed behavior when a critical pipeline component breaks mid-call, and
the speaker-mapping instrumentation for the first real call.

Two layers, matching how this codebase already splits responsibility:
- Direct `MediaStreamPipeline` unit/integration tests (real pipeline.py code,
  a real `LiveSuggestionHub`, a hand-built fake ASR handle whose connection
  health is controllable — same accepted stand-in role SimulatedASRProvider
  already plays elsewhere for "real audio").
- Full `/ws/twilio-media` end-to-end tests (via test_streaming_pipeline_e2e's
  real fixtures) for the failure modes that only manifest at that layer:
  pipeline construction itself failing, and an unhandled mid-stream exception.
"""
import asyncio
import json
import logging

import pytest
from conftest import auth_headers, login

from app.services.live_push import LiveSuggestionHub
from app.streaming.asr import ASREvent, get_asr_provider
from app.streaming.media_stream_session import INBOUND, OUTBOUND, TRACKS
from app.streaming.pipeline import MediaStreamPipeline, PipelineStatus
from app.streaming.speaker_mapping import SpeakerRoleResolver

from test_streaming_pipeline_e2e import StreamSimulator, _connect, _create_call, media_stream_client  # noqa: F401

run = asyncio.run


class _FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


class _ControllableASRProvider:
    """A fake ASR provider (not SimulatedASRProvider — that one is always
    "connected") whose per-track handles' is_connected() the test can flip
    directly, standing in for a real provider's connection health exactly the
    way SimulatedASRProvider already stands in for real audio elsewhere."""
    def __init__(self):
        self.handles: dict[str, '_ControllableASRHandle'] = {}

    async def start_stream(self, *, track: str) -> '_ControllableASRHandle':
        handle = _ControllableASRHandle(track=track)
        self.handles[track] = handle
        return handle


class _ControllableASRHandle:
    def __init__(self, *, track):
        self.track = track
        self.connected = True
        self._pending: list[ASREvent] = []
        self._final_text = ''

    async def feed_audio(self, payload, *, is_speaking):
        pass

    async def poll_events(self):
        pending, self._pending = self._pending, []
        return pending

    def queue_interim(self, text='hallo'):
        import time
        self._final_text = text  # what finalize() below will return once VAD falls silent
        self._pending.append(ASREvent(kind='interim', track=self.track, text=text, t_monotonic=time.monotonic()))

    async def finalize(self):
        import time
        if not self._final_text:
            return None
        text, self._final_text = self._final_text, ''
        return ASREvent(kind='final', track=self.track, text=text, t_monotonic=time.monotonic())

    async def close(self):
        pass

    def is_connected(self) -> bool:
        return self.connected


async def _make_pipeline(hub, call_id=1, company_id=10, speaker_role_resolver=None):
    provider = _ControllableASRProvider()
    pipeline = await MediaStreamPipeline.create(
        call_id=call_id, company_id=company_id, asr_provider=provider, speaker_role_resolver=speaker_role_resolver,
    )
    ws = _FakeWebSocket()
    hub.register(call_id=call_id, company_id=company_id, user_id=1, websocket=ws)
    return pipeline, provider, ws


def _media_message(track, chunk=1, timestamp_ms=0, payload=b'\x00' * 160):
    return {
        'event': 'media',
        'media': {'track': track, 'chunk': str(chunk), 'timestamp': str(timestamp_ms), 'payload': __import__('base64').b64encode(payload).decode()},
    }


def test_deepgram_disconnect_mid_call_is_pushed_exactly_once_on_the_transition(monkeypatch):
    """item 3/4: consume_media() must detect a connect->disconnect transition
    and push disrupted + suggestion_stale — but only ONCE per transition, not
    once per subsequent chunk while it stays down."""
    hub = LiveSuggestionHub()
    monkeypatch.setattr('app.streaming.pipeline.get_live_suggestion_hub', lambda: hub)

    async def scenario():
        pipeline, provider, ws = await _make_pipeline(hub)
        pipeline.asr_provider_name = 'deepgram'  # only Deepgram-specific pushes are gated on this
        await pipeline.consume_media(_media_message(INBOUND, chunk=1))
        assert {'type': 'pipeline_status', 'status': 'deepgram_ready', 'detail': None} in ws.sent

        provider.handles[INBOUND].connected = False
        ws.sent.clear()
        await pipeline.consume_media(_media_message(INBOUND, chunk=2, timestamp_ms=20))
        assert ws.sent == [
            {'type': 'pipeline_status', 'status': 'disrupted', 'detail': 'deepgram_unavailable'},
            {'type': 'suggestion_stale', 'reason': 'deepgram_unavailable'},
        ]

        # Stays down — must NOT be pushed again on the next chunk (no spam).
        ws.sent.clear()
        await pipeline.consume_media(_media_message(INBOUND, chunk=3, timestamp_ms=40))
        assert ws.sent == []

        # Recovers — pushed again as a fresh, distinct transition.
        provider.handles[INBOUND].connected = True
        ws.sent.clear()
        await pipeline.consume_media(_media_message(INBOUND, chunk=4, timestamp_ms=60))
        assert ws.sent == [{'type': 'pipeline_status', 'status': 'deepgram_ready', 'detail': None}]
    run(scenario())


def test_simulated_provider_never_triggers_deepgram_specific_pushes(monkeypatch):
    """A demo/test run using SimulatedASRProvider (asr_provider_name stays
    'simulated') must never show a synthetic 'Deepgram bereit'/'nicht
    verfügbar' — those are gated on asr_provider_name == 'deepgram'."""
    hub = LiveSuggestionHub()
    monkeypatch.setattr('app.streaming.pipeline.get_live_suggestion_hub', lambda: hub)

    async def scenario():
        pipeline, provider, ws = await _make_pipeline(hub)
        await pipeline.consume_media(_media_message(INBOUND, chunk=1))
        statuses = [m['status'] for m in ws.sent if m['type'] == 'pipeline_status']
        assert 'deepgram_ready' not in statuses
        assert 'audio_received' in statuses
    run(scenario())


def test_audio_received_and_transcript_active_are_each_pushed_exactly_once(monkeypatch):
    hub = LiveSuggestionHub()
    monkeypatch.setattr('app.streaming.pipeline.get_live_suggestion_hub', lambda: hub)

    async def scenario():
        pipeline, provider, ws = await _make_pipeline(hub)
        provider.handles[INBOUND].queue_interim('hallo')
        await pipeline.consume_media(_media_message(INBOUND, chunk=1))
        await pipeline.consume_media(_media_message(INBOUND, chunk=2, timestamp_ms=20))
        statuses = [m['status'] for m in ws.sent if m['type'] == 'pipeline_status']
        assert statuses.count('audio_received') == 1
        assert statuses.count('transcript_active') == 1
    run(scenario())


class _UntrustedResolver:
    """A resolver that never maps to a recognized role — the fail-closed
    branch this exercises is otherwise unreachable in production (see
    pipeline.py's own comment), so it can only be tested by injecting one."""
    def resolve(self, track: str) -> str:
        return track  # neither 'seller' nor 'prospect'


def test_untrusted_speaker_mapping_marks_disrupted_and_stale_but_still_persists_the_turn(client, db_session, monkeypatch):
    """item 4/9: an unrecognized speaker role must never silently produce a
    seemingly-normal suggestion — the pipeline still persists the turn (data
    is never silently dropped) but marks the analysis disrupted and any
    resulting suggestion stale."""
    from app.models import Turn

    hub = LiveSuggestionHub()
    monkeypatch.setattr('app.streaming.pipeline.get_live_suggestion_hub', lambda: hub)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)

    async def scenario():
        pipeline, provider, ws = await _make_pipeline(hub, call_id=call_id, company_id=1, speaker_role_resolver=_UntrustedResolver())
        provider.handles[OUTBOUND].queue_interim('Wir haben bereits einen Anbieter.')
        await pipeline.consume_media(_media_message(OUTBOUND, chunk=1))
        # Silence long enough to trigger VAD hangover -> finalize -> turn end.
        for i in range(20):
            await pipeline.consume_media(_media_message(OUTBOUND, chunk=2 + i, timestamp_ms=20 * (i + 1), payload=b'\xff' * 160))
        statuses = [m for m in ws.sent if m['type'] == 'pipeline_status']
        assert {'type': 'pipeline_status', 'status': 'disrupted', 'detail': 'untrusted_speaker_mapping'} in statuses
        stale = [m for m in ws.sent if m['type'] == 'suggestion_stale']
        assert {'type': 'suggestion_stale', 'reason': 'untrusted_speaker_mapping'} in stale
    run(scenario())

    turns = db_session.query(Turn).filter_by(call_id=call_id).all()
    assert len(turns) == 1  # data still persisted, never silently dropped
    assert turns[0].speaker == OUTBOUND  # the untrusted resolver's own (unrecognized) value, stored as-is


def test_speaker_mapping_instrumentation_is_logged_once_per_call_without_transcript_content(caplog):
    """item 9: after the real call, it must be technically reconstructible
    which Twilio track mapped to which SpeakerRole and which ASR session
    correlates to it — logged once at pipeline creation, never any spoken
    content."""
    hub = LiveSuggestionHub()

    async def scenario():
        with caplog.at_level(logging.INFO, logger='replica.streaming'):
            pipeline, _, _ = await _make_pipeline(hub, call_id=42, company_id=1)
        return pipeline
    pipeline = run(scenario())

    records = [r for r in caplog.records if r.message == 'speaker mapping instrumented for this call']
    assert len(records) == 1
    fields = records[0].fields
    assert fields['call_id'] == 42
    assert fields['track_to_speaker_role'] == {INBOUND: 'seller', OUTBOUND: 'prospect'}
    assert fields['topology'] == 'outbound_sales_flow_v2'
    assert set(fields['asr_session_ids'].keys()) == set(TRACKS)
    assert fields['asr_session_ids'] == pipeline.asr_session_ids
    # No transcript/audio content anywhere in the log record.
    assert 'hallo' not in str(fields)


# --- Full /ws/twilio-media + /ws/live/{call_id} tests (main.py's own fail-closed handling) ---

class _RaisingASRProvider:
    """Stands in for a real ASR provider that refuses to construct/connect at
    all — e.g. Deepgram auth rejected, DNS failure — the failure mode item 3/4
    calls out explicitly: pipeline construction itself failing."""
    async def start_stream(self, *, track: str):
        raise RuntimeError('simulated: ASR provider refused to connect')


def test_pipeline_creation_failure_pushes_disrupted_and_closes_the_media_stream_ws(client, media_stream_client):
    """item 3/4: if the pipeline can't even be constructed (most realistically
    a real ASR provider failing to connect), the seller's live UI must be told
    "Analyse nicht verfügbar" — never left silently believing analysis is
    running just because the phone call itself connected."""
    from app.main import app as main_app

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    live_token = login(client, 'haydar@replica-pilot.example')

    main_app.dependency_overrides[get_asr_provider] = lambda: _RaisingASRProvider()
    try:
        with client.websocket_connect(f'/ws/live/{call_id}') as live_ws:
            live_ws.send_text(json.dumps({'type': 'auth', 'token': live_token}))
            assert live_ws.receive_json()['type'] == 'auth_ok'

            with pytest.raises(Exception):
                with _connect(media_stream_client) as ws:
                    sim = StreamSimulator(ws, call_id=call_id)
                    sim.start()
                    # The server closes the media-stream WS (code 1011) as soon as
                    # pipeline construction fails — the next receive_text() surfaces
                    # that as a client-side disconnect/exception.
                    ws.receive_text()

            msg1 = live_ws.receive_json()
            assert msg1 == {'type': 'pipeline_status', 'status': 'media_stream_connected', 'detail': None}
            # A generically-named failing provider gets the generic detail — see
            # test_deepgram_named_provider_failure_is_labelled_deepgram_unavailable
            # below for the (real-world-realistic) DeepgramASRProvider-specific case.
            msg2 = live_ws.receive_json()
            assert msg2 == {'type': 'pipeline_status', 'status': 'disrupted', 'detail': 'pipeline_error'}
            msg3 = live_ws.receive_json()
            assert msg3 == {'type': 'suggestion_stale', 'reason': 'pipeline_error'}
    finally:
        main_app.dependency_overrides.pop(get_asr_provider, None)


def test_deepgram_named_provider_failure_is_labelled_deepgram_unavailable(client, media_stream_client):
    """The realistic case: REPLICA_ASR_PROVIDER=deepgram configured, and the
    real DeepgramASRProvider itself fails to construct/connect — must be
    labelled specifically ('Deepgram nicht verfügbar'), not the generic
    'Analyse nicht verfügbar', matching the user's own example wording."""
    from app.main import app as main_app

    FakeDeepgramASRProvider = type('DeepgramASRProvider', (), {
        'start_stream': lambda self, *, track: (_ for _ in ()).throw(RuntimeError('simulated: Deepgram auth rejected')),
    })

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    live_token = login(client, 'haydar@replica-pilot.example')

    main_app.dependency_overrides[get_asr_provider] = lambda: FakeDeepgramASRProvider()
    try:
        with client.websocket_connect(f'/ws/live/{call_id}') as live_ws:
            live_ws.send_text(json.dumps({'type': 'auth', 'token': live_token}))
            assert live_ws.receive_json()['type'] == 'auth_ok'

            with pytest.raises(Exception):
                with _connect(media_stream_client) as ws:
                    sim = StreamSimulator(ws, call_id=call_id)
                    sim.start()
                    ws.receive_text()

            assert live_ws.receive_json()['status'] == 'media_stream_connected'
            assert live_ws.receive_json() == {'type': 'pipeline_status', 'status': 'deepgram_connecting', 'detail': None}
            assert live_ws.receive_json() == {'type': 'pipeline_status', 'status': 'disrupted', 'detail': 'deepgram_unavailable'}
    finally:
        main_app.dependency_overrides.pop(get_asr_provider, None)


def test_media_stream_disconnect_without_a_clean_stop_pushes_disrupted(client, media_stream_client):
    """item 4/6: Twilio's WebSocket dropping without ever sending a clean
    'stop' event first (docs/PROVIDER_REFERENCES.md documents 'stop' as the
    normal end-of-stream signal) must not leave a genuinely still-connected
    phone call silently analysis-less."""
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    live_token = login(client, 'haydar@replica-pilot.example')

    with client.websocket_connect(f'/ws/live/{call_id}') as live_ws:
        live_ws.send_text(json.dumps({'type': 'auth', 'token': live_token}))
        assert live_ws.receive_json()['type'] == 'auth_ok'

        with _connect(media_stream_client) as ws:
            sim = StreamSimulator(ws, call_id=call_id)
            sim.start()
            sim.silence('outbound', 0.1)
            # No sim.stop() — the WS is simply closed by exiting this `with`
            # block, exactly like an abrupt transport drop.

        msg1 = live_ws.receive_json()
        assert msg1 == {'type': 'pipeline_status', 'status': 'media_stream_connected', 'detail': None}
        msg2 = live_ws.receive_json()
        assert msg2 == {'type': 'pipeline_status', 'status': 'audio_received', 'detail': None}
        msg3 = live_ws.receive_json()
        assert msg3 == {'type': 'pipeline_status', 'status': 'disrupted', 'detail': 'media_stream_disconnected'}
        msg4 = live_ws.receive_json()
        assert msg4 == {'type': 'suggestion_stale', 'reason': 'media_stream_disconnected'}
