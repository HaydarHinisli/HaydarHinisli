"""docs/DECISIONS.md ADR-060: browser-based (Twilio Voice JS SDK) outbound
calling for the first real test without a purchased Twilio number.

Covers the two new endpoints:
- POST /api/voice/access-token — mints a short-lived Twilio Access Token for
  the browser's Device (`app.integrations.twilio_rest.create_voice_access_token`).
- POST /webhooks/twilio/voice-outbound — the Voice Request URL the browser's
  `device.connect()` call lands on; same signature-verification posture as
  the existing call-status webhook (docs/DECISIONS.md ADR-029/036).
"""
import jwt as pyjwt
import pytest
from conftest import auth_headers, login
from twilio.request_validator import RequestValidator

TOKEN_PATH = '/api/voice/access-token'
VOICE_PATH = '/webhooks/twilio/voice-outbound'
AUTH_TOKEN = 'test-auth-token'
BASE = 'http://127.0.0.1:8000'


@pytest.fixture(autouse=True)
def _settings_cache_reset():
    """create_voice_access_token() calls get_settings() FRESH on every call
    (unlike app/main.py's module-level `settings`, bound once at import time)
    — env vars + cache_clear() is the pattern this repo already uses for
    exactly this (tests/test_twilio_rest_region.py). Autouse + a `finally`-
    style cache_clear() on the way out matters here specifically: this file
    sorts alphabetically AFTER test_twilio_rest_region.py, which already
    leaves the lru_cache cleared in its own teardown — without re-clearing it
    ourselves afterward, a later test file would inherit a Settings instance
    still carrying this file's fake TWILIO_API_KEY_SID/SECRET/TWILIO_APP_SID
    env values for as long as monkeypatch.setenv's own revert hasn't yet
    forced a rebuild."""
    import app.config as config_module
    yield
    config_module.get_settings.cache_clear()


def _configure_voice_settings(monkeypatch, *, account_sid='ACtest', api_key_sid='SKtest', api_key_secret='supersecretsupersecretsupersecret', twiml_app_sid='APtest'):
    import app.config as config_module
    monkeypatch.setenv('TWILIO_ACCOUNT_SID', account_sid or '')
    monkeypatch.setenv('TWILIO_API_KEY_SID', api_key_sid or '')
    monkeypatch.setenv('TWILIO_API_KEY_SECRET', api_key_secret or '')
    monkeypatch.setenv('TWILIO_TWIML_APP_SID', twiml_app_sid or '')
    config_module.get_settings.cache_clear()


# --- /api/voice/access-token ---------------------------------------------------------

def test_access_token_requires_auth(client):
    r = client.post(TOKEN_PATH)
    assert r.status_code == 401


def test_access_token_fails_closed_when_not_configured(client, monkeypatch):
    _configure_voice_settings(monkeypatch, api_key_sid='', api_key_secret='', twiml_app_sid='')
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.post(TOKEN_PATH, headers=headers)
    assert r.status_code == 500


def test_access_token_returns_a_valid_voice_grant_jwt(client, monkeypatch):
    _configure_voice_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.post(TOKEN_PATH, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['identity'].startswith('user-')
    decoded = pyjwt.decode(body['token'], 'supersecretsupersecretsupersecret', algorithms=['HS256'])
    assert decoded['grants']['voice']['outgoing']['application_sid'] == 'APtest'
    assert decoded['grants']['identity'] == body['identity']
    assert decoded['sub'] == 'ACtest'


def test_access_token_identity_is_scoped_to_the_calling_user(client, monkeypatch):
    _configure_voice_settings(monkeypatch)
    headers_a = auth_headers(client, 'haydar@replica-pilot.example')
    headers_b = auth_headers(client, 'mara@replica-pilot.example')
    identity_a = client.post(TOKEN_PATH, headers=headers_a).json()['identity']
    identity_b = client.post(TOKEN_PATH, headers=headers_b).json()['identity']
    assert identity_a != identity_b


# --- /webhooks/twilio/voice-outbound --------------------------------------------------

def _sig(url, params, token=AUTH_TOKEN):
    return RequestValidator(token).compute_signature(url, params)


def _configure_webhook_settings(monkeypatch, *, auth_token=AUTH_TOKEN, base_url=BASE, caller_id='+491700000000'):
    import app.main as main_module
    monkeypatch.setattr(main_module.settings, 'twilio_auth_token', auth_token)
    monkeypatch.setattr(main_module.settings, 'replica_public_base_url', base_url)
    monkeypatch.setattr(main_module.settings, 'twilio_verified_caller_id', caller_id)


def test_voice_outbound_rejects_missing_signature(client, monkeypatch):
    _configure_webhook_settings(monkeypatch)
    r = client.post(VOICE_PATH, data={'To': '+49170123456', 'replica_call_id': '1'})
    assert r.status_code == 403


def test_voice_outbound_rejects_wrong_signature(client, monkeypatch):
    _configure_webhook_settings(monkeypatch)
    r = client.post(
        VOICE_PATH, data={'To': '+49170123456', 'replica_call_id': '1'},
        headers={'X-Twilio-Signature': 'totally-wrong=='},
    )
    assert r.status_code == 403


def test_voice_outbound_accepts_valid_signature_and_returns_correct_twiml(client, monkeypatch):
    _configure_webhook_settings(monkeypatch)
    params = {'To': '+49170123456', 'replica_call_id': '42'}
    sig = _sig(BASE + VOICE_PATH, params)
    r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 200, r.text
    assert r.headers['content-type'].startswith('application/xml')
    body = r.text
    # Stream must come before Dial (Media Stream running before anything is dialed).
    assert body.index('<Start>') < body.index('<Dial')
    assert 'track="both_tracks"' in body
    assert '<Parameter name="replica_call_id" value="42" />' in body
    assert 'callerId="+491700000000"' in body
    assert '<Number>+49170123456</Number>' in body
    assert '/ws/twilio-media' in body


def test_voice_outbound_rejects_malformed_to_and_never_logs_it(client, monkeypatch, caplog):
    import logging
    _configure_webhook_settings(monkeypatch)
    params = {'To': 'not-a-real-phone-number', 'replica_call_id': '42'}
    sig = _sig(BASE + VOICE_PATH, params)
    with caplog.at_level(logging.WARNING, logger='replica.webhooks'):
        r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 400
    assert 'not-a-real-phone-number' not in caplog.text


def test_voice_outbound_requires_replica_call_id(client, monkeypatch):
    _configure_webhook_settings(monkeypatch)
    params = {'To': '+49170123456', 'replica_call_id': ''}
    sig = _sig(BASE + VOICE_PATH, params)
    r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 400


def test_voice_outbound_fails_closed_without_verified_caller_id_configured(client, monkeypatch):
    _configure_webhook_settings(monkeypatch, caller_id=None)
    params = {'To': '+49170123456', 'replica_call_id': '42'}
    sig = _sig(BASE + VOICE_PATH, params)
    r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 500


def test_voice_outbound_xml_escapes_replica_call_id_in_the_actual_response(client, monkeypatch):
    # replica_call_id always comes from the browser's own JS (String(currentCallId),
    # a numeric DB id) rather than free text, but the embedding still must not
    # break — or inject markup — if it ever contained XML-special characters.
    _configure_webhook_settings(monkeypatch)
    params = {'To': '+49170123456', 'replica_call_id': '42"><Evil/>'}
    sig = _sig(BASE + VOICE_PATH, params)
    r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 200, r.text
    assert '<Evil/>' not in r.text
    assert '42&quot;&gt;&lt;Evil/&gt;' in r.text
