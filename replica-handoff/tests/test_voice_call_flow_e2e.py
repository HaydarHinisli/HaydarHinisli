"""docs/DECISIONS.md ADR-062: end-to-end rehearsal of the entire browser-based
voice-call flow (ADR-060/061) — as automated as this codebase can make it
without a real Twilio account, a real Deepgram account, or a real phone
ringing.

Ties together, in one continuous test, everything ADR-060/061 covered only
separately before: a real Voice Access Token carrying the confirmed IE1
`twr` claim and `dublin` edge → the real `/webhooks/twilio/voice-outbound`
response (proving `replica_call_id` travels from that webhook intact) → that
SAME `call_id` driven through the REAL Media Stream pipeline
(`SimulatedASRProvider`, both tracks) → real Turn Detection → real
Conversation State → real SalesBrain → a real Suggestion pushed to a real
`/ws/live/{call_id}` client → a real Render-ACK with a computed RSL estimate.
Also confirms the speaker mapping this whole topology depends on: the
`outbound` (`<Dial>`-ed-out) track resolves to `prospect`, matching
`OutboundSalesFlowResolver` (ADR-053/058/060).

Honesty, as in `tests/test_streaming_pipeline_e2e.py` (whose fixtures this
file reuses rather than duplicating): audio content and the ASR transcript
are still simulated. Everything else exercised here — the access-token
minting, the webhook's signature verification and TwiML generation, the
Media Stream handshake, VAD/turn detection, SalesBrain, the live push, and
the Render-ACK/RSL computation — is real, unmocked REPLICA code. What this
file does NOT and cannot prove: a real Twilio account, a real phone ringing,
or real audio/Deepgram transcription — that is exactly what the first real
call itself is for.
"""
import json

import jwt as pyjwt
import pytest
from conftest import auth_headers, login
from twilio.request_validator import RequestValidator

from test_streaming_pipeline_e2e import TOKEN as MEDIA_STREAM_TOKEN
from test_streaming_pipeline_e2e import StreamSimulator, _connect, _create_call, _use_script, _clear_script, media_stream_client  # noqa: F401

TOKEN_PATH = '/api/voice/access-token'
VOICE_PATH = '/webhooks/twilio/voice-outbound'
BASE = 'http://127.0.0.1:8000'


@pytest.fixture(autouse=True)
def _settings_cache_reset():
    """See tests/test_voice_outbound.py's identical fixture for why this is
    necessary (create_voice_access_token() calls get_settings() fresh)."""
    import app.config as config_module
    yield
    config_module.get_settings.cache_clear()


def _configure_voice_settings(monkeypatch):
    import app.config as config_module
    monkeypatch.setenv('TWILIO_ACCOUNT_SID', 'ACtest')
    monkeypatch.setenv('TWILIO_API_KEY_SID', 'SKtest')
    monkeypatch.setenv('TWILIO_API_KEY_SECRET', 'supersecretsupersecretsupersecret')
    monkeypatch.setenv('TWILIO_TWIML_APP_SID', 'APtest')
    monkeypatch.setenv('TWILIO_REGION', 'ie1')
    monkeypatch.setenv('TWILIO_EDGE', 'dublin')
    config_module.get_settings.cache_clear()


def _sig(url, params, token):
    return RequestValidator(token).compute_signature(url, params)


def test_full_browser_call_flow_without_a_real_pstn_call(client, media_stream_client, db_session, monkeypatch):
    import app.main as main_module
    from app.models import Turn

    _configure_voice_settings(monkeypatch)
    # media_stream_client already pinned settings.twilio_auth_token to
    # MEDIA_STREAM_TOKEN for this test's duration — reuse that SAME value for
    # the voice-outbound webhook's signature too, rather than introducing a
    # second auth-token value that would fight over the same settings field.
    monkeypatch.setattr(main_module.settings, 'twilio_verified_caller_id', '+491700000000')

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    live_token = login(client, 'haydar@replica-pilot.example')

    # --- 1) Voice Access Token -> IE1, tenant/consent-checked, ticket minted (ADR-063) --
    token_resp = client.post(TOKEN_PATH, headers=headers, params={'call_id': call_id})
    assert token_resp.status_code == 200, token_resp.text
    token_body = token_resp.json()
    assert token_body['region'] == 'ie1'
    assert token_body['edge'] == 'dublin'
    jwt_header = pyjwt.get_unverified_header(token_body['token'])
    assert jwt_header['twr'] == 'ie1'  # the actual signal Twilio's signaling infra reads
    assert token_body['voice_ticket']  # ADR-063: what the browser actually sends to device.connect()

    # --- 2) device.connect() -> POST /webhooks/twilio/voice-outbound -> TwiML --------
    # ADR-063: only the ticket travels from the browser — never a raw call_id.
    voice_params = {'To': '+491701234567', 'replica_voice_ticket': token_body['voice_ticket']}
    sig = _sig(BASE + VOICE_PATH, voice_params, MEDIA_STREAM_TOKEN)
    voice_resp = client.post(VOICE_PATH, data=voice_params, headers={'X-Twilio-Signature': sig})
    assert voice_resp.status_code == 200, voice_resp.text
    twiml = voice_resp.text
    assert twiml.index('<Start>') < twiml.index('<Dial')  # Media Stream running before anything is dialed
    assert 'track="both_tracks"' in twiml
    assert f'<Parameter name="replica_call_id" value="{call_id}" />' in twiml
    assert 'callerId="+491700000000"' in twiml
    assert '<Number>+491701234567</Number>' in twiml

    # --- 3) That exact replica_call_id drives the REAL Media Stream pipeline ---------
    _use_script(client.app, {'outbound': ['Wir haben bereits einen Anbieter.']})
    try:
        with client.websocket_connect(f'/ws/live/{call_id}') as live_ws:
            live_ws.send_text(json.dumps({'type': 'auth', 'token': live_token}))
            auth_ok = live_ws.receive_json()
            assert auth_ok['type'] == 'auth_ok'
            with _connect(media_stream_client) as ws:
                sim = StreamSimulator(ws, call_id=call_id)
                # start() defaults to {'replica_call_id': str(call_id)} — exactly the
                # value the voice-outbound webhook embedded in step 2 above.
                sim.start()
                sim.silence('outbound', 0.1)
                sim.speak('outbound', 0.4)
                sim.silence('outbound', 0.4)  # > 300ms hangover -> finalize/turn-end
                sim.stop()
            # ADR-063 (item 3): drain the interleaved pipeline_status milestones
            # (media_stream_connected/audio_received/transcript_active/
            # suggestion_pipeline_ready) pushed over this same connection ahead
            # of the eventual suggestion — see test_streaming_pipeline_e2e.py's
            # identical fix for the same reason.
            pushed = live_ws.receive_json()
            while pushed['type'] == 'pipeline_status':
                pushed = live_ws.receive_json()
    finally:
        _clear_script(client.app)

    # --- 4) Live Suggestion -----------------------------------------------------------
    assert pushed['type'] == 'suggestion'
    assert pushed['call_id'] == call_id
    assert pushed['suggestion_id'] is not None
    assert pushed['trace_id'] is not None

    # --- 5) Speaker Mapping: outbound (the <Dial>-ed-out child leg) = prospect --------
    turns = db_session.query(Turn).filter_by(call_id=call_id).order_by(Turn.id).all()
    assert [t.speaker for t in turns] == ['prospect']

    # --- 6) Render-ACK -> real computed RSL estimate ----------------------------------
    ack_resp = client.post(
        f"/api/suggestions/{pushed['suggestion_id']}/render-ack", headers=headers,
        json={
            'trace_id': pushed['trace_id'], 'call_id': call_id,
            'client_received_epoch_ms': 1000.0, 'client_rendered_epoch_ms': 1050.0,
            'client_received_perf_ms': 10.0, 'client_rendered_perf_ms': 60.0,
        },
    )
    assert ack_resp.status_code == 200, ack_resp.text
    assert ack_resp.json()['wallclock_rsl_estimate_ms'] is not None
