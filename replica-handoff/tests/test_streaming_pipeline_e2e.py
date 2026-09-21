"""Sprint 2 proof harness: Twilio call -> separated live audio channels ->
streaming ASR -> interim transcripts -> reliable turn detection -> exactly one
final turn -> ConversationState -> SalesBrain -> Suggestion, driven through the
REAL `/ws/twilio-media` endpoint (handshake security, MediaStreamSession,
VoiceActivityDetector, SimulatedASRProvider, TurnDetector,
process_final_turn — no shortcuts, no internal function called directly except to
set up fixtures/assert on results).

Honesty, stated once here and in the final report: audio content and ASR transcript
text are simulated (real mu-law-encoded synthetic tone standing in for "speech",
real silence for "silence", a pre-registered script standing in for what a real ASR
vendor would have transcribed — see app/streaming/asr.py's SimulatedASRProvider
docstring for why). Everything downstream of that boundary — signal energy (VAD),
sequence/identity diagnostics, turn detection, the central turn-processing path,
policy gating, and every latency measurement — is the REAL production code path,
and every latency number these tests assert on is a REAL measurement of that real
code running, not a mock. What is NOT proven here: a live Twilio account, a live ASR
vendor, or real network conditions.
"""
import base64
import json
import math
import time

import pytest

from conftest import auth_headers, login

from app.streaming import mulaw
from app.streaming.asr import SimulatedASRProvider, get_asr_provider
from app.webhooks.security import compute_twilio_signature

TOKEN = 'test-media-stream-token'
WS_PATH = '/ws/twilio-media'


def _silence(n=160):
    return bytes([mulaw.SILENCE_BYTE]) * n


def _tone(amplitude=9000, freq=200, n=160, phase0=0, sr=8000):
    samples = [int(amplitude * math.sin(2 * math.pi * freq * (phase0 + i) / sr)) for i in range(n)]
    return mulaw.encode(samples)


def _b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode()


def _media_msg(track, chunk, timestamp_ms, seq, payload):
    return json.dumps({
        'event': 'media', 'sequenceNumber': str(seq),
        'media': {'track': track, 'chunk': str(chunk), 'timestamp': str(timestamp_ms), 'payload': _b64(payload)},
    })


class StreamSimulator:
    """Drives the real WS endpoint with a realistic Twilio Media Streams message
    sequence: connected -> start -> media (N chunks, both tracks, real mu-law bytes)
    -> stop. `speak(track, seconds)` appends `seconds` worth of tone chunks (20ms
    each) for that track; `silence(track, seconds)` appends silence chunks — used to
    open natural gaps between utterances and to trigger VAD hangover / turn-end.
    """
    def __init__(self, ws, *, call_id: int, call_sid: str = 'CASIM1'):
        self.ws = ws
        self.call_id = call_id
        self.call_sid = call_sid
        self._seq = 1
        self._chunk = {'inbound': 0, 'outbound': 0}
        self._timestamp_ms = {'inbound': 0, 'outbound': 0}

    def start(self, custom_parameters=None):
        params = custom_parameters if custom_parameters is not None else {'replica_call_id': str(self.call_id)}
        self.ws.send_text(json.dumps({
            'event': 'start', 'sequenceNumber': str(self._seq),
            'start': {'streamSid': 'MZSIM1', 'callSid': self.call_sid, 'customParameters': params},
        }))
        self._seq += 1

    def _send_chunk(self, track, payload):
        self._chunk[track] += 1
        self.ws.send_text(_media_msg(track, self._chunk[track], self._timestamp_ms[track], self._seq, payload))
        self._timestamp_ms[track] += 20
        self._seq += 1

    def speak(self, track, seconds=0.5, phase_offset=0):
        n_chunks = int(seconds / 0.02)
        for i in range(n_chunks):
            self._send_chunk(track, _tone(phase0=(phase_offset + i) * 160))

    def silence(self, track, seconds=0.5):
        n_chunks = int(seconds / 0.02)
        for _ in range(n_chunks):
            self._send_chunk(track, _silence())

    def stop(self):
        self.ws.send_text(json.dumps({'event': 'stop', 'sequenceNumber': str(self._seq), 'streamSid': 'MZSIM1'}))
        self._seq += 1

    def raw_media(self, track, chunk, timestamp_ms, payload=None):
        self.ws.send_text(_media_msg(track, chunk, timestamp_ms, self._seq, payload or _silence()))
        self._seq += 1


@pytest.fixture()
def media_stream_client(client):
    """The shared `client` fixture's app, with settings.twilio_auth_token patched
    for the duration of one test."""
    import app.main as main_module
    original = main_module.settings.twilio_auth_token
    main_module.settings.twilio_auth_token = TOKEN
    yield client
    main_module.settings.twilio_auth_token = original


def _connect(media_stream_client, *, signature=None, path=WS_PATH):
    import app.main as main_module
    base_url = main_module.settings.replica_public_base_url
    sig = signature if signature is not None else compute_twilio_signature(f'{base_url}{WS_PATH}', {}, TOKEN)
    return media_stream_client.websocket_connect(path, headers={'X-Twilio-Signature': sig})


def _create_call(client, headers, **overrides):
    payload = {'seller_id': 1, 'prospect_company': 'Acme', 'prospect_type': 'b2b'}
    payload.update(overrides)
    r = client.post('/api/calls', headers=headers, json=payload)
    assert r.status_code == 200, r.text
    call_id = r.json()['id']
    client.post(f'/api/calls/{call_id}/consent', headers=headers, json={'state': 'granted'})
    return call_id


def _use_script(app, script):
    from app.main import app as main_app
    main_app.dependency_overrides[get_asr_provider] = lambda: SimulatedASRProvider(script=script)


def _clear_script(app):
    from app.main import app as main_app
    main_app.dependency_overrides.pop(get_asr_provider, None)


# --- handshake security (requirement 1) ----------------------------------------------

def test_handshake_rejects_missing_signature(media_stream_client):
    with pytest.raises(Exception):
        with _connect(media_stream_client, signature=''):
            pass


def test_handshake_rejects_wrong_signature(media_stream_client):
    with pytest.raises(Exception):
        with _connect(media_stream_client, signature='not-a-real-signature=='):
            pass


def test_handshake_accepts_valid_signature(media_stream_client):
    with _connect(media_stream_client) as ws:
        pass  # connection accepted; closing cleanly is enough to prove the handshake passed


def test_production_env_rejects_plain_ws_connection(media_stream_client, monkeypatch):
    import app.main as main_module
    monkeypatch.setattr(main_module.settings, 'replica_env', 'production')
    with pytest.raises(Exception):
        with _connect(media_stream_client):
            pass  # TestClient's ws:// transport has no X-Forwarded-Proto -> insecure in production


def test_non_production_env_still_allows_plain_ws_connection(media_stream_client, monkeypatch):
    import app.main as main_module
    monkeypatch.setattr(main_module.settings, 'replica_env', 'local')
    with _connect(media_stream_client):
        pass  # local/dev must not be locked out of ws:// testing


# --- full golden path: call -> separated channels -> ASR -> turn -> suggestion ------

def test_golden_path_produces_exactly_one_turn_and_one_suggestion(client, media_stream_client, db_session):
    from app.models import Call, ConversationStateEvent, Suggestion, Turn, TurnLatencyTrace

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    # ADR-053: outbound is the prospect track for the confirmed test topology
    # (seller calls in on inbound; TwiML <Dial>s the prospect out to outbound).
    _use_script(client.app, {'outbound': ['Wir haben bereits einen Anbieter.']})
    try:
        with _connect(media_stream_client) as ws:
            sim = StreamSimulator(ws, call_id=call_id)
            sim.start()
            sim.silence('outbound', 0.1)
            sim.speak('outbound', 0.4)
            sim.silence('outbound', 0.4)  # > 300ms hangover -> triggers finalize/turn-end
            sim.stop()
    finally:
        _clear_script(client.app)

    turns = db_session.query(Turn).filter_by(call_id=call_id).all()
    suggestions = db_session.query(Suggestion).filter_by(call_id=call_id).all()
    state_events = db_session.query(ConversationStateEvent).filter_by(call_id=call_id).all()
    traces = db_session.query(TurnLatencyTrace).filter_by(call_id=call_id).all()

    assert len(turns) == 1
    assert turns[0].speaker == 'prospect'
    assert turns[0].text == 'Wir haben bereits einen Anbieter.'
    assert len(suggestions) == 1
    assert len(state_events) == 1
    assert len(traces) == 1

    call = db_session.get(Call, call_id)
    assert call.external_call_id == ''  # correlation used customParameters, not external_call_id — unaffected


def test_golden_path_uses_call_sid_correlation_when_no_custom_parameters(client, media_stream_client, db_session):
    from app.models import Call, Turn

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    call = db_session.get(Call, call_id)
    call.external_call_id = 'CASIDCORR1'
    db_session.commit()

    _use_script(client.app, {'inbound': ['Ja, worum geht es denn?']})
    try:
        with _connect(media_stream_client) as ws:
            sim = StreamSimulator(ws, call_id=call_id, call_sid='CASIDCORR1')
            sim.start(custom_parameters={})  # no replica_call_id -> must fall back to CallSid match
            sim.silence('inbound', 0.1)
            sim.speak('inbound', 0.3)
            sim.silence('inbound', 0.4)
            sim.stop()
    finally:
        _clear_script(client.app)

    turns = db_session.query(Turn).filter_by(call_id=call_id).all()
    assert len(turns) == 1


def test_unresolvable_call_closes_the_connection(media_stream_client):
    with _connect(media_stream_client) as ws:
        sim = StreamSimulator(ws, call_id=999999, call_sid='CANONEXISTENT')
        sim.start(custom_parameters={})  # no matching Call anywhere -> must be rejected
        message = ws.receive()
        assert message['type'] == 'websocket.close'


# --- seller and prospect tracked and processed separately (requirement 2) -----------

def test_both_tracks_produce_independent_turns_for_the_correct_speaker(client, media_stream_client, db_session):
    from app.models import Turn

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    # ADR-053: inbound = seller (caller-in), outbound = prospect (<Dial>-ed out).
    _use_script(client.app, {
        'inbound': ['Guten Tag hier ist Anna von Replica.'],
        'outbound': ['Wir haben bereits einen Anbieter.'],
    })
    try:
        with _connect(media_stream_client) as ws:
            sim = StreamSimulator(ws, call_id=call_id)
            sim.start()
            sim.speak('inbound', 0.4)    # seller greets first
            sim.silence('inbound', 0.4)
            sim.speak('outbound', 0.4)   # then prospect responds
            sim.silence('outbound', 0.4)
            sim.stop()
    finally:
        _clear_script(client.app)

    turns = db_session.query(Turn).filter_by(call_id=call_id).order_by(Turn.id).all()
    assert [t.speaker for t in turns] == ['seller', 'prospect']
    assert turns[0].text == 'Guten Tag hier ist Anna von Replica.'
    assert turns[1].text == 'Wir haben bereits einen Anbieter.'


# --- interim transcripts never trigger state/suggestion side effects (requirement 5) -

def test_interim_transcripts_create_no_side_effects_before_turn_end(client, media_stream_client, db_session):
    from app.models import ConversationStateEvent, Suggestion, Turn

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    # ADR-053: outbound is the prospect track — a Suggestion only ever comes
    # from a prospect turn, and this test needs one to appear after turn-end.
    _use_script(client.app, {'outbound': ['Wir haben bereits einen Anbieter und sind zufrieden']})
    try:
        with _connect(media_stream_client) as ws:
            sim = StreamSimulator(ws, call_id=call_id)
            sim.start()
            # Speak long enough to generate MANY interim events (one per 20ms chunk)
            # but never let the track fall silent — no turn-end should occur yet.
            sim.speak('outbound', 1.0)
            assert db_session.query(Turn).filter_by(call_id=call_id).count() == 0
            assert db_session.query(Suggestion).filter_by(call_id=call_id).count() == 0
            assert db_session.query(ConversationStateEvent).filter_by(call_id=call_id).count() == 0
            # NOW let it fall silent -> exactly one final turn should appear.
            sim.silence('outbound', 0.4)
            sim.stop()
    finally:
        _clear_script(client.app)

    assert db_session.query(Turn).filter_by(call_id=call_id).count() == 1
    assert db_session.query(Suggestion).filter_by(call_id=call_id).count() == 1


# --- media stream identity/sequence diagnostics surfaced end-to-end (requirement 3) -

def test_out_of_order_and_duplicate_raw_chunks_do_not_crash_or_duplicate_the_turn(client, media_stream_client, db_session):
    from app.models import Turn

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    _use_script(client.app, {'inbound': ['Wir haben bereits einen Anbieter.']})
    try:
        with _connect(media_stream_client) as ws:
            sim = StreamSimulator(ws, call_id=call_id)
            sim.start()
            sim.speak('inbound', 0.3)
            # manually inject a duplicate of an already-sent chunk number, and an
            # out-of-order (lower, never-seen) chunk number, interleaved with normal
            # traffic — must not crash the connection or corrupt turn detection.
            sim.raw_media('inbound', chunk=3, timestamp_ms=9999)   # duplicate chunk number
            sim.raw_media('inbound', chunk=1, timestamp_ms=9999)   # out-of-order (already passed)
            sim.silence('inbound', 0.4)
            sim.stop()
    finally:
        _clear_script(client.app)

    turns = db_session.query(Turn).filter_by(call_id=call_id).all()
    assert len(turns) == 1  # exactly one turn despite the transport anomalies


def test_reconnect_mid_call_does_not_duplicate_or_lose_the_turn(client, media_stream_client, db_session):
    from app.models import Turn

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    _use_script(client.app, {'inbound': ['Wir haben bereits einen Anbieter.']})
    try:
        with _connect(media_stream_client) as ws:
            sim = StreamSimulator(ws, call_id=call_id)
            sim.start()
            sim.speak('inbound', 0.1)
            # Simulate a Twilio reconnect: a fresh `start` with a different
            # streamSid for the same call, mid-connection.
            ws.send_text(json.dumps({
                'event': 'start', 'sequenceNumber': '1',
                'start': {'streamSid': 'MZSIM2-RECONNECT', 'callSid': sim.call_sid, 'customParameters': {'replica_call_id': str(call_id)}},
            }))
            sim._chunk['inbound'] = 0
            sim._timestamp_ms['inbound'] = 0
            sim.speak('inbound', 0.3)
            sim.silence('inbound', 0.4)
            sim.stop()
    finally:
        _clear_script(client.app)

    turns = db_session.query(Turn).filter_by(call_id=call_id).all()
    assert len(turns) == 1


# --- end-to-end latency instrumentation (requirement 4) ------------------------------

def test_latency_trace_stages_are_recorded_in_correct_monotonic_order(client, media_stream_client, db_session):
    from app.models import TurnLatencyTrace

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    # ADR-053: outbound is the prospect track — push_enqueued/ws_send_completed
    # are only marked for a prospect turn that produces a Suggestion.
    _use_script(client.app, {'outbound': ['Wir haben bereits einen Anbieter.']})
    try:
        with _connect(media_stream_client) as ws:
            sim = StreamSimulator(ws, call_id=call_id)
            sim.start()
            sim.speak('outbound', 0.3)
            sim.silence('outbound', 0.4)
            sim.stop()
    finally:
        _clear_script(client.app)

    trace = db_session.query(TurnLatencyTrace).filter_by(call_id=call_id).one()
    assert trace.t_audio_received_at is not None
    assert trace.t_asr_interim_at is not None
    assert trace.t_asr_final_at is not None
    assert trace.t_turn_end_detected_at is not None
    assert trace.t_salesbrain_started_at is not None
    assert trace.t_salesbrain_finished_at is not None
    assert trace.t_suggestion_persisted_at is not None
    # Sprint 3A/ADR-051: the suggestion is now actually handed to the
    # live-delivery layer, so t_push_enqueued_at/t_ws_send_completed_at ARE set —
    # but t_ui_rendered/wallclock_rsl_estimate_ms/server_render_ack_latency_ms only
    # ever come from a real browser Render-ACK (POST /api/suggestions/{id}/render-ack),
    # which never happens in this test.
    assert trace.t_push_enqueued_at is not None
    assert trace.t_ws_send_completed_at is not None
    assert trace.t_ui_rendered_at is None
    assert trace.wallclock_rsl_estimate_ms is None  # never approximated — see ADR-041/048/051
    assert trace.server_render_ack_latency_ms is None

    # wall-clock ordering (audit/tracing correlation)
    assert trace.t_audio_received_at <= trace.t_asr_interim_at <= trace.t_asr_final_at
    assert trace.t_asr_final_at <= trace.t_turn_end_detected_at
    assert trace.t_salesbrain_started_at <= trace.t_salesbrain_finished_at
    assert trace.t_salesbrain_finished_at <= trace.t_suggestion_persisted_at

    # derived monotonic latency deltas: real measurements, all non-negative
    assert trace.audio_to_interim_ms is not None and trace.audio_to_interim_ms >= 0
    assert trace.audio_to_final_ms is not None and trace.audio_to_final_ms >= 0
    assert trace.turn_detection_latency_ms is not None and trace.turn_detection_latency_ms >= 0
    assert trace.salesbrain_latency_ms is not None and trace.salesbrain_latency_ms >= 0
    assert trace.suggestion_persist_latency_ms is not None and trace.suggestion_persist_latency_ms >= 0
    assert trace.ws_send_latency_ms is not None and trace.ws_send_latency_ms >= 0
    # internal engine latency must never be reported as RSL
    assert trace.wallclock_rsl_estimate_ms is None

    # Sprint 2B (ADR-045): every trace must be honestly labelled as synthetic while
    # SimulatedASRProvider is in use — never silently look like a real measurement.
    assert trace.asr_provider == 'simulated'
    assert trace.is_synthetic is True


# --- unidirectional media stream (Sprint 2B requirement 2) ---------------------------

def test_media_stream_never_sends_audio_back_to_twilio(client, media_stream_client, monkeypatch, db_session):
    """REPLICA's assist MVP only listens (Sprint 2B, ADR-047) — the required TwiML
    is <Start><Stream>, a listen-only side-channel; there must be no code path that
    sends anything back over this WebSocket. Enforced here by making any outgoing
    send raise, then running a full golden-path call through the real endpoint."""
    from starlette.websockets import WebSocket

    def _forbidden(*args, **kwargs):
        raise AssertionError('media stream handler attempted to send data back to Twilio — must stay listen-only (ADR-047)')

    monkeypatch.setattr(WebSocket, 'send_text', _forbidden)
    monkeypatch.setattr(WebSocket, 'send_bytes', _forbidden)
    monkeypatch.setattr(WebSocket, 'send_json', _forbidden)

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    _use_script(client.app, {'inbound': ['Wir haben bereits einen Anbieter.']})
    try:
        with _connect(media_stream_client) as ws:
            sim = StreamSimulator(ws, call_id=call_id)
            sim.start()
            sim.speak('inbound', 0.3)
            sim.silence('inbound', 0.4)
            sim.stop()
    finally:
        _clear_script(client.app)

    from app.models import Turn
    assert db_session.query(Turn).filter_by(call_id=call_id).count() == 1  # the call still completed normally


# --- Sprint 3A Definition of Done: simulated stream -> ... -> live push -> real browser client -> Render-ACK -> full trace ---

def test_sprint_3a_full_synthetic_path_through_live_push_and_render_ack(client, media_stream_client, db_session):
    """Sprint 3A's own Definition of Done, run against the existing simulator since
    no real Twilio/Deepgram credentials exist yet: simulated Twilio stream -> ASR ->
    final turn -> ConversationState -> SalesBrain -> Suggestion -> Live Push -> a
    REAL browser client connected over /ws/live/{call_id} -> a REAL Render-ACK HTTP
    call (with genuine, if synthetic-timed, performance.now()/Date.now()-shaped
    values) -> a complete TurnLatencyTrace row including a computed
    wallclock_rsl_estimate_ms and server_render_ack_latency_ms.

    Honesty, restated (see this file's module docstring and the Sprint 3A report):
    the audio/ASR content is still simulated, so this row's `is_synthetic` MUST stay
    True and `asr_provider` MUST stay 'simulated' — the MECHANISM being proven here
    (live push, WS auth, Render-ACK, RSL computation, clock-sync sample handling)
    is real production code; the call audio and transcript are not.
    """
    from app.models import TurnLatencyTrace

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    live_token = login(client, 'haydar@replica-pilot.example')

    # ADR-053: outbound is the prospect track for the confirmed test topology —
    # only a prospect turn produces a Suggestion/live push at all.
    _use_script(client.app, {'outbound': ['Wir haben bereits einen Anbieter.']})
    try:
        with client.websocket_connect(f'/ws/live/{call_id}') as live_ws:
            live_ws.send_text(json.dumps({'type': 'auth', 'token': live_token}))
            auth_ok = live_ws.receive_json()
            assert auth_ok['type'] == 'auth_ok'  # ADR-058: explicit ack before the receive loop starts
            with _connect(media_stream_client) as ws:
                sim = StreamSimulator(ws, call_id=call_id)
                sim.start()
                sim.silence('outbound', 0.1)
                sim.speak('outbound', 0.4)
                sim.silence('outbound', 0.4)  # > 300ms hangover -> finalize/turn-end
                sim.stop()
            # ADR-063 (item 3): the Media Stream side now also pushes its own
            # pipeline_status milestones over this exact same /ws/live/{call_id}
            # connection, interleaved ahead of the eventual suggestion — drain
            # those first rather than assuming the very next message is it.
            pipeline_statuses = []
            pushed = live_ws.receive_json()
            while pushed['type'] == 'pipeline_status':
                pipeline_statuses.append(pushed['status'])
                pushed = live_ws.receive_json()
    finally:
        _clear_script(client.app)

    # --- ADR-063 (item 3): the analysis pipeline reported real, sequential
    # progress independently of the phone call itself — never something the
    # seller has to take on faith. ---
    assert pipeline_statuses == [
        'media_stream_connected', 'audio_received', 'transcript_active', 'suggestion_pipeline_ready',
    ]

    # --- Live Suggestion Push (requirement 1) ---
    assert pushed['type'] == 'suggestion'
    assert pushed['call_id'] == call_id
    assert pushed['suggestion_id'] is not None
    assert pushed['trace_id'] is not None
    assert pushed['suggestion']  # non-empty "SAG JETZT" text

    # --- Minimal UI payload shape (requirement 2): a guidance hint derived from
    # the EXISTING strategy, plus separately-tagged debug info, never blended. ---
    assert pushed['guidance_hint'] == 'weiterfragen'  # strategy: discover_buying_criteria
    assert pushed['conversation_phase']
    assert pushed['debug']['is_synthetic'] is True
    assert pushed['debug']['asr_provider'] == 'simulated'
    assert pushed['debug']['latencies_ms']['salesbrain'] is not None  # internal only, never real RSL

    suggestion_id = pushed['suggestion_id']
    trace_id = pushed['trace_id']

    # --- Real UI-render acknowledgement (requirement 3): the browser's own
    # monotonic (performance.now()-shaped) and wall-clock (Date.now()-shaped) pairs,
    # plus a couple of clock-sync ping/pong samples (ADR-051). ---
    now_ms = time.time() * 1000
    ack = client.post(
        f'/api/suggestions/{suggestion_id}/render-ack', headers=headers,
        json={
            'trace_id': trace_id, 'call_id': call_id,
            'client_received_epoch_ms': now_ms, 'client_rendered_epoch_ms': now_ms + 40,
            'client_received_perf_ms': 500.0, 'client_rendered_perf_ms': 517.5,
            'clock_sync_samples': [
                {'t1_client_send_ms': 0, 't2_server_recv_ms': 10, 't3_server_send_ms': 10, 't4_client_recv_ms': 20},
            ],
        },
    )
    assert ack.status_code == 200, ack.text
    ack_body = ack.json()
    assert ack_body['client_render_latency_ms'] == pytest.approx(17.5)
    assert ack_body['clock_offset_estimate_ms'] == 0
    assert ack_body['clock_rtt_estimate_ms'] == 20
    assert ack_body['server_render_ack_latency_ms'] is not None
    assert ack_body['server_render_ack_latency_ms'] >= 0

    # --- ADR-051: wallclock_rsl_estimate_ms and server_render_ack_latency_ms are
    # now both computed (a real Render-ACK happened), the former a cross-machine
    # wall-clock ESTIMATE, the latter a monotonic server-side UPPER BOUND — while
    # everything stays honestly labelled as a synthetic measurement (requirement 7). ---
    trace = db_session.query(TurnLatencyTrace).filter_by(call_id=call_id, trace_id=trace_id).one()
    assert trace.t_push_enqueued_at is not None  # handed to the live-delivery layer
    assert trace.t_ws_send_completed_at is not None
    assert trace.t_browser_received_at is not None
    assert trace.t_ui_rendered_at is not None
    assert trace.t_render_ack_received_at is not None
    assert trace.wallclock_rsl_estimate_ms is not None
    assert trace.wallclock_rsl_estimate_ms >= 0
    assert trace.server_render_ack_latency_ms is not None
    assert trace.server_render_ack_latency_ms >= 0
    assert trace.client_render_latency_ms == pytest.approx(17.5)
    assert trace.clock_offset_estimate_ms == 0
    assert trace.clock_rtt_estimate_ms == 20
    assert trace.clock_uncertainty_ms == 10
    assert trace.is_synthetic is True
    assert trace.asr_provider == 'simulated'
    # salesbrain_latency_ms is internal engine latency and must never be conflated
    # with any RSL figure, even though both are non-null on this row now.
    assert trace.salesbrain_latency_ms is not None
    assert trace.salesbrain_latency_ms != trace.wallclock_rsl_estimate_ms
    assert trace.salesbrain_latency_ms != trace.server_render_ack_latency_ms
