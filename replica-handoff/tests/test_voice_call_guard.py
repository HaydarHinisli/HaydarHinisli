"""docs/DECISIONS.md ADR-064: end-to-end proof that the per-call_id
concurrency lock (app/services/voice_call_guard.VoiceCallConcurrencyLock),
acquired by `POST /webhooks/twilio/voice-outbound` the moment it commits to
placing a real call, is actually released by every real exit path of
`/ws/twilio-media` — a clean 'stop', an unclean disconnect, and a pipeline
construction failure — proving the 409 a second concurrent attempt gets is a
real, temporary lock tied to that call's own lifecycle, not a permanent
block or one that needs a server restart to clear (docs/DECISIONS.md
ADR-064, item 2: "sauberer Reset nach Ended/Failed").

Reuses test_voice_outbound.py's webhook helpers and test_streaming_pipeline_
e2e.py's real Media Stream fixtures rather than duplicating either — this
file's only job is proving the two sides (webhook acquire, media-stream
release) actually connect correctly end-to-end.
"""
import pytest
from conftest import auth_headers

from app.streaming.asr import get_asr_provider

from test_streaming_pipeline_e2e import TOKEN as MEDIA_STREAM_TOKEN
from test_streaming_pipeline_e2e import StreamSimulator, _connect, media_stream_client  # noqa: F401
from test_voice_outbound import BASE, VOICE_PATH, _create_call, _fresh_call_sid, _sig, _ticket


def _configure_shared_webhook_settings(monkeypatch, *, caller_id='+491700000000'):
    """Unlike test_voice_outbound.py's own `_configure_webhook_settings()`,
    this reuses the `media_stream_client` fixture's OWN auth-token value
    (rather than introducing a second, conflicting one) — both the voice-
    outbound webhook AND the media-stream WS handshake in these tests must
    verify against the exact same X-Twilio-Signature secret, since both are
    exercised in the same test (see test_voice_call_flow_e2e.py's identical
    fix for the same reason)."""
    import app.main as main_module
    monkeypatch.setattr(main_module.settings, 'twilio_auth_token', MEDIA_STREAM_TOKEN)
    monkeypatch.setattr(main_module.settings, 'replica_public_base_url', BASE)
    monkeypatch.setattr(main_module.settings, 'twilio_verified_caller_id', caller_id)


def _place_call(client, *, call_id, to='+49170123456'):
    params = {'To': to, 'replica_voice_ticket': _ticket(call_id=call_id), 'CallSid': _fresh_call_sid()}
    sig = _sig(BASE + VOICE_PATH, params, MEDIA_STREAM_TOKEN)
    return client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})


def test_lock_is_released_after_a_clean_media_stream_stop(client, media_stream_client, monkeypatch):
    _configure_shared_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)

    assert _place_call(client, call_id=call_id).status_code == 200
    assert _place_call(client, call_id=call_id, to='+49170123457').status_code == 409  # still locked

    with _connect(media_stream_client) as ws:
        sim = StreamSimulator(ws, call_id=call_id)
        sim.start()
        sim.silence('outbound', 0.05)
        sim.stop()  # clean end-of-stream

    r = _place_call(client, call_id=call_id, to='+49170123458')
    assert r.status_code == 200, r.text  # lock released — a new real test call is allowed again


def test_lock_is_released_after_an_unclean_media_stream_disconnect(client, media_stream_client, monkeypatch):
    _configure_shared_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)

    assert _place_call(client, call_id=call_id).status_code == 200

    with _connect(media_stream_client) as ws:
        sim = StreamSimulator(ws, call_id=call_id)
        sim.start()
        sim.silence('outbound', 0.05)
        # No sim.stop() — the WS just closes when this `with` block exits,
        # exactly like an abrupt transport drop (see docs/DECISIONS.md
        # ADR-063 item 4/6's identical scenario).

    r = _place_call(client, call_id=call_id, to='+49170123459')
    assert r.status_code == 200, r.text


def test_lock_is_released_after_pipeline_construction_failure(client, media_stream_client, monkeypatch):
    """The one exit path with no `pipeline` object at all (construction
    itself failed) — proving the lock's release does not depend on a
    pipeline having ever existed."""
    from app.main import app as main_app

    class _RaisingASRProvider:
        async def start_stream(self, *, track: str):
            raise RuntimeError('simulated: ASR provider refused to connect')

    _configure_shared_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)

    assert _place_call(client, call_id=call_id).status_code == 200

    main_app.dependency_overrides[get_asr_provider] = lambda: _RaisingASRProvider()
    try:
        with pytest.raises(Exception):
            with _connect(media_stream_client) as ws:
                sim = StreamSimulator(ws, call_id=call_id)
                sim.start()
                ws.receive_text()  # server closes (code 1011) once pipeline construction fails
    finally:
        main_app.dependency_overrides.pop(get_asr_provider, None)

    r = _place_call(client, call_id=call_id, to='+49170123460')
    assert r.status_code == 200, r.text
