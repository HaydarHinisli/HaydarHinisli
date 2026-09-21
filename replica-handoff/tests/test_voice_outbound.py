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


def _configure_voice_settings(monkeypatch, *, account_sid='ACtest', api_key_sid='SKtest', api_key_secret='supersecretsupersecretsupersecret', twiml_app_sid='APtest', region='ie1', edge='dublin'):
    import app.config as config_module
    monkeypatch.setenv('TWILIO_ACCOUNT_SID', account_sid or '')
    monkeypatch.setenv('TWILIO_API_KEY_SID', api_key_sid or '')
    monkeypatch.setenv('TWILIO_API_KEY_SECRET', api_key_secret or '')
    monkeypatch.setenv('TWILIO_TWIML_APP_SID', twiml_app_sid or '')
    monkeypatch.setenv('TWILIO_REGION', region or '')
    monkeypatch.setenv('TWILIO_EDGE', edge or '')
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


def test_access_token_sets_the_twr_region_header_and_response_edge(client, monkeypatch):
    """ADR-061: confirmed directly against the installed Twilio SDK's source
    that `region=` on AccessToken sets the JWT's `twr` header claim — Twilio's
    signaling infrastructure uses this to route the client to the configured
    region (IE1). The initial ADR-060 implementation omitted this entirely.
    `edge` isn't a JWT claim at all (the Voice SDK's Device takes it as a
    constructor option) so it must come back in the response body instead."""
    _configure_voice_settings(monkeypatch, region='ie1', edge='dublin')
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.post(TOKEN_PATH, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['region'] == 'ie1'
    assert body['edge'] == 'dublin'
    header = pyjwt.get_unverified_header(body['token'])
    assert header['twr'] == 'ie1'


def test_access_token_fails_closed_without_region_or_edge_configured(client, monkeypatch):
    """Matches get_twilio_rest_client()'s existing EU-residency posture
    (ADR-049) — a Voice Access Token issued with no region preference at all
    would silently defeat that same guarantee for the browser-calling path."""
    _configure_voice_settings(monkeypatch, region='')
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.post(TOKEN_PATH, headers=headers)
    assert r.status_code == 500

    _configure_voice_settings(monkeypatch, edge='')
    r = client.post(TOKEN_PATH, headers=headers)
    assert r.status_code == 500


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


# --- GET /api/voice/preflight (ADR-062) -----------------------------------------------
#
# voice_preflight() reads app.main's module-level `settings` directly (no fresh
# get_settings() call), so — unlike create_voice_access_token() — patching
# attributes on `app.main.settings` is sufficient and correct here; no
# env-var/cache_clear dance needed.

PREFLIGHT_PATH = '/api/voice/preflight'

_REAL_LOOKING_SECRETS = {
    'twilio_account_sid': 'ACabcdefabcdefabcdefabcdefabcdef01',
    'twilio_api_key_sid': 'SKabcdefabcdefabcdefabcdefabcdef01',
    'twilio_api_key_secret': 'sooper-sekrit-api-key-value-xyz987',
    'twilio_twiml_app_sid': 'APabcdefabcdefabcdefabcdefabcdef01',
    'twilio_verified_caller_id': '+491701234567',
    'deepgram_api_key': 'dg-sooper-sekrit-deepgram-key-abc123',
}


def _configure_preflight_settings(monkeypatch, **overrides):
    import app.main as main_module
    values = dict(
        _REAL_LOOKING_SECRETS,
        twilio_region='ie1', twilio_edge='dublin',
        replica_public_base_url='http://127.0.0.1:8000',
        replica_env='local', replica_allowed_ws_origins=None,
    )
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setattr(main_module.settings, key, value)


def test_preflight_requires_auth(client):
    r = client.get(PREFLIGHT_PATH)
    assert r.status_code == 401


def test_preflight_reports_ready_when_everything_is_configured_correctly(client, monkeypatch):
    _configure_preflight_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.get(PREFLIGHT_PATH, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['ready'] is True
    assert all(c['ok'] for c in body['checks'])


def test_preflight_never_leaks_any_secret_value_in_the_response(client, monkeypatch):
    """The whole point of this endpoint: status only, never the underlying
    value — checked here against every configured secret-shaped value at
    once, not just spot-checked one field."""
    _configure_preflight_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.get(PREFLIGHT_PATH, headers=headers)
    assert r.status_code == 200, r.text
    raw_body = r.text
    for secret_value in _REAL_LOOKING_SECRETS.values():
        assert secret_value not in raw_body, f'secret-shaped value leaked into preflight response: {secret_value!r}'


def test_preflight_reports_missing_items_by_label_when_unconfigured(client, monkeypatch):
    _configure_preflight_settings(
        monkeypatch, twilio_api_key_secret=None, twilio_verified_caller_id=None, deepgram_api_key=None,
    )
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.get(PREFLIGHT_PATH, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['ready'] is False
    by_key = {c['key']: c for c in body['checks']}
    assert by_key['twilio_api_key_secret']['ok'] is False
    assert by_key['twilio_verified_caller_id']['ok'] is False
    assert by_key['deepgram_api_key']['ok'] is False
    # unaffected fields still report ok
    assert by_key['twilio_account_sid']['ok'] is True
    assert by_key['twilio_region']['ok'] is True


def test_preflight_flags_wrong_region_or_edge_and_still_shows_the_actual_value(client, monkeypatch):
    """Region/edge are not secrets — showing the actual (wrong) value is the
    point, so the operator can see exactly what's misconfigured."""
    _configure_preflight_settings(monkeypatch, twilio_region='us1', twilio_edge='ashburn')
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.get(PREFLIGHT_PATH, headers=headers)
    body = r.json()
    assert body['ready'] is False
    by_key = {c['key']: c for c in body['checks']}
    assert by_key['twilio_region'] == {'key': 'twilio_region', 'label': 'TWILIO_REGION', 'ok': False, 'value': 'us1'}
    assert by_key['twilio_edge'] == {'key': 'twilio_edge', 'label': 'TWILIO_EDGE', 'ok': False, 'value': 'ashburn'}


def test_preflight_ws_origin_check_is_satisfied_in_local_env_regardless_of_allowlist(client, monkeypatch):
    _configure_preflight_settings(monkeypatch, replica_env='local', replica_allowed_ws_origins=None)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.get(PREFLIGHT_PATH, headers=headers)
    body = r.json()
    origin_check = next(c for c in body['checks'] if c['key'] == 'ws_origin_allowlist')
    assert origin_check['ok'] is True
    assert body['ready'] is True


def test_preflight_ws_origin_check_matches_against_replica_public_base_url_outside_local(client, monkeypatch):
    _configure_preflight_settings(
        monkeypatch, replica_env='production',
        replica_public_base_url='https://replica-test.example.com',
        replica_allowed_ws_origins='https://replica-test.example.com',
    )
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.get(PREFLIGHT_PATH, headers=headers)
    body = r.json()
    origin_check = next(c for c in body['checks'] if c['key'] == 'ws_origin_allowlist')
    assert origin_check['ok'] is True
    assert body['ready'] is True


def test_preflight_ws_origin_check_fails_when_allowlist_does_not_match_outside_local(client, monkeypatch):
    _configure_preflight_settings(
        monkeypatch, replica_env='production',
        replica_public_base_url='https://replica-test.example.com',
        replica_allowed_ws_origins='https://some-other-host.example.com',
    )
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.get(PREFLIGHT_PATH, headers=headers)
    body = r.json()
    origin_check = next(c for c in body['checks'] if c['key'] == 'ws_origin_allowlist')
    assert origin_check['ok'] is False
    assert body['ready'] is False
