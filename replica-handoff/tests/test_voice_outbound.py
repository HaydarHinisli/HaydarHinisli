"""docs/DECISIONS.md ADR-060: browser-based (Twilio Voice JS SDK) outbound
calling for the first real test without a purchased Twilio number.

Covers the two new endpoints:
- POST /api/voice/access-token — mints a short-lived Twilio Access Token for
  the browser's Device (`app.integrations.twilio_rest.create_voice_access_token`)
  AND, since ADR-063, a short-lived REPLICA-signed `voice_ticket` binding this
  Access Token's use to one specific tenant-owned, consent-checked call_id.
- POST /webhooks/twilio/voice-outbound — the Voice Request URL the browser's
  `device.connect()` call lands on; same signature-verification posture as
  the existing call-status webhook (docs/DECISIONS.md ADR-029/036), plus
  (ADR-063) verification of that `voice_ticket` as the ONLY source of the
  call_id this webhook will ever trust — never a raw browser-supplied value.
"""
from datetime import datetime, timedelta

import jwt as pyjwt
import pytest
from conftest import DEMO_PASSWORD, auth_headers, login
from twilio.request_validator import RequestValidator

from app.auth.security import create_voice_call_ticket, hash_password
from app.db import SessionLocal
from app.models import Call, Company, Seller, User

TOKEN_PATH = '/api/voice/access-token'
VOICE_PATH = '/webhooks/twilio/voice-outbound'
AUTH_TOKEN = 'test-auth-token'
BASE = 'http://127.0.0.1:8000'


def _create_call(client, headers, **overrides):
    payload = {'seller_id': 1, 'prospect_company': 'Acme', 'prospect_type': 'b2b'}
    payload.update(overrides)
    r = client.post('/api/calls', headers=headers, json=payload)
    assert r.status_code == 200, r.text
    call_id = r.json()['id']
    client.post(f'/api/calls/{call_id}/consent', headers=headers, json={'state': 'granted'})
    return call_id


def _make_second_tenant():
    """Mirrors tests/test_live_suggestions_ws.py's own helper of the same
    purpose — a real second Company/Seller/User/Call, entirely independent of
    the demo tenant every other test in this file uses. Unique name/email per
    call (this file's tests share one session-scoped DB) so multiple tests
    creating their own "second tenant" never collide on Company.name's unique
    constraint."""
    import uuid
    suffix = uuid.uuid4().hex[:8]
    db = SessionLocal()
    try:
        company = Company(name=f'Rival Voice Corp {suffix}', country_code='DE', network_learning_opt_in=False)
        db.add(company)
        db.flush()
        now = datetime.utcnow()
        seller = Seller(company_id=company.id, name='Riva', hired_at=now - timedelta(days=10), product_started_at=now - timedelta(days=10))
        db.add(seller)
        db.flush()
        email = f'riva-voice-{suffix}@rival.example'
        user = User(company_id=company.id, email=email, password_hash=hash_password(DEMO_PASSWORD), role='seller')
        db.add(user)
        call = Call(company_id=company.id, seller_id=seller.id, prospect_company='Rival Prospect', jurisdiction_country='DE')
        db.add(call)
        db.flush()
        db.commit()
        return {'company_id': company.id, 'call_id': call.id, 'email': email}
    finally:
        db.close()


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
#
# ADR-063: call_id is now a required query param, tenant-checked and
# consent/policy-checked before anything is minted — every test below that
# expects success first creates a real, consented call via _create_call().

def test_access_token_requires_auth(client):
    r = client.post(TOKEN_PATH, params={'call_id': 1})
    assert r.status_code == 401


def test_access_token_requires_call_id_query_param(client, monkeypatch):
    _configure_voice_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.post(TOKEN_PATH, headers=headers)
    assert r.status_code == 422


def test_access_token_404s_for_a_nonexistent_call(client, monkeypatch):
    _configure_voice_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.post(TOKEN_PATH, headers=headers, params={'call_id': 99999999})
    assert r.status_code == 404


def test_access_token_404s_for_a_cross_tenant_call(client, monkeypatch):
    """Item 7/8: a real call_id, just not this tenant's — must be
    indistinguishable from a nonexistent one, matching _get_call_or_404's
    posture everywhere else in this codebase."""
    _configure_voice_settings(monkeypatch)
    other = _make_second_tenant()
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.post(TOKEN_PATH, headers=headers, params={'call_id': other['call_id']})
    assert r.status_code == 404


def test_access_token_403s_when_consent_has_not_been_granted(client, monkeypatch):
    """Item 7: a real, own-tenant call is not enough by itself — live-assist
    processing must actually be permitted for it right now."""
    _configure_voice_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.post('/api/calls', headers=headers, json={'seller_id': 1, 'prospect_company': 'Acme', 'prospect_type': 'b2b'})
    call_id = r.json()['id']  # deliberately never granting consent
    r = client.post(TOKEN_PATH, headers=headers, params={'call_id': call_id})
    assert r.status_code == 403


def test_access_token_fails_closed_when_not_configured(client, monkeypatch):
    _configure_voice_settings(monkeypatch, api_key_sid='', api_key_secret='', twiml_app_sid='')
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    r = client.post(TOKEN_PATH, headers=headers, params={'call_id': call_id})
    assert r.status_code == 500


def test_access_token_returns_a_valid_voice_grant_jwt(client, monkeypatch):
    _configure_voice_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    r = client.post(TOKEN_PATH, headers=headers, params={'call_id': call_id})
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
    call_id = _create_call(client, headers)
    r = client.post(TOKEN_PATH, headers=headers, params={'call_id': call_id})
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
    call_id = _create_call(client, headers)
    r = client.post(TOKEN_PATH, headers=headers, params={'call_id': call_id})
    assert r.status_code == 500

    _configure_voice_settings(monkeypatch, edge='')
    r = client.post(TOKEN_PATH, headers=headers, params={'call_id': call_id})
    assert r.status_code == 500


def test_access_token_identity_is_scoped_to_the_calling_user(client, monkeypatch):
    _configure_voice_settings(monkeypatch)
    headers_a = auth_headers(client, 'haydar@replica-pilot.example')
    headers_b = auth_headers(client, 'mara@replica-pilot.example')
    call_id = _create_call(client, headers_a)  # same tenant — either seller/manager may fetch a token for it
    identity_a = client.post(TOKEN_PATH, headers=headers_a, params={'call_id': call_id}).json()['identity']
    identity_b = client.post(TOKEN_PATH, headers=headers_b, params={'call_id': call_id}).json()['identity']
    assert identity_a != identity_b


def test_access_token_voice_ticket_is_call_tenant_and_user_bound(client, monkeypatch):
    """ADR-063 item 7/8: the ticket — not a raw call_id — is what the browser
    passes to device.connect(), and what /webhooks/twilio/voice-outbound
    actually trusts. Its claims must exactly match what was authorized."""
    _configure_voice_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    r = client.post(TOKEN_PATH, headers=headers, params={'call_id': call_id})
    body = r.json()
    assert 'voice_ticket' in body
    assert body['voice_ticket'] != body['token']  # never the same artifact as the Twilio Access Token
    ticket_payload = pyjwt.decode(body['voice_ticket'], 'test-only-secret-not-for-production', algorithms=['HS256'])
    assert ticket_payload['purpose'] == 'voice_call_ticket'
    assert ticket_payload['call_id'] == call_id
    assert ticket_payload['company_id'] == 1  # demo tenant's company_id
    assert body['voice_ticket_ttl_seconds'] <= 600  # short-lived by design, distinct from the 1h Twilio token TTL


def test_access_token_voice_ticket_cannot_be_forged_with_a_different_secret(client, monkeypatch):
    _configure_voice_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    forged = pyjwt.encode(
        {'purpose': 'voice_call_ticket', 'call_id': call_id, 'company_id': 1, 'user_id': 1},
        'not-the-real-replica-jwt-secret', algorithm='HS256',
    )
    with pytest.raises(pyjwt.InvalidTokenError):
        pyjwt.decode(forged, 'test-only-secret-not-for-production', algorithms=['HS256'])


# --- /webhooks/twilio/voice-outbound --------------------------------------------------
#
# ADR-063 (item 8): this webhook no longer accepts a raw `replica_call_id` from
# the browser at all — only `replica_voice_ticket`, decoded and verified
# server-side. `_ticket()` below mints one directly (bypassing the HTTP
# endpoint, for speed/precision in most tests); at least one test below still
# goes through the real /api/voice/access-token endpoint end-to-end into this
# webhook, proving the full real flow, not just the two halves in isolation.

def _sig(url, params, token=AUTH_TOKEN):
    return RequestValidator(token).compute_signature(url, params)


def _configure_webhook_settings(monkeypatch, *, auth_token=AUTH_TOKEN, base_url=BASE, caller_id='+491700000000'):
    import app.main as main_module
    monkeypatch.setattr(main_module.settings, 'twilio_auth_token', auth_token)
    monkeypatch.setattr(main_module.settings, 'replica_public_base_url', base_url)
    monkeypatch.setattr(main_module.settings, 'twilio_verified_caller_id', caller_id)


def _ticket(*, call_id, company_id=1, user_id=1, ttl_seconds=300):
    return create_voice_call_ticket(call_id=call_id, company_id=company_id, user_id=user_id, ttl_seconds=ttl_seconds)['ticket']


# ADR-064: every request that reaches the ticket-replay/concurrency-lock
# checks now needs a CallSid — a fresh, unique one per test's own call_id
# keeps ticket_jti/CallSid pairs (and therefore lock acquisitions) from ever
# needing to be coordinated across tests, since call_id itself is already
# unique per test (auto-incrementing, shared session-scoped DB).
_call_sid_counter = iter(range(1, 10_000))


def _fresh_call_sid() -> str:
    return f'CAtest{next(_call_sid_counter):026d}'


def test_voice_outbound_rejects_missing_signature(client, monkeypatch):
    _configure_webhook_settings(monkeypatch)
    r = client.post(VOICE_PATH, data={'To': '+49170123456', 'replica_voice_ticket': 'irrelevant-signature-checked-first'})
    assert r.status_code == 403


def test_voice_outbound_rejects_wrong_signature(client, monkeypatch):
    _configure_webhook_settings(monkeypatch)
    r = client.post(
        VOICE_PATH, data={'To': '+49170123456', 'replica_voice_ticket': 'irrelevant-signature-checked-first'},
        headers={'X-Twilio-Signature': 'totally-wrong=='},
    )
    assert r.status_code == 403


def test_voice_outbound_accepts_valid_signature_and_returns_correct_twiml(client, monkeypatch):
    _configure_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    params = {'To': '+49170123456', 'replica_voice_ticket': _ticket(call_id=call_id), 'CallSid': _fresh_call_sid()}
    sig = _sig(BASE + VOICE_PATH, params)
    r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 200, r.text
    assert r.headers['content-type'].startswith('application/xml')
    body = r.text
    # Stream must come before Dial (Media Stream running before anything is dialed).
    assert body.index('<Start>') < body.index('<Dial')
    assert 'track="both_tracks"' in body
    assert f'<Parameter name="replica_call_id" value="{call_id}" />' in body
    assert 'callerId="+491700000000"' in body
    assert '<Number>+49170123456</Number>' in body
    assert '/ws/twilio-media' in body
    # ADR-065: statusCallback is the ONLY way the concurrency lock is ever
    # released for a call that never reaches /ws/twilio-media at all.
    assert f'statusCallback="https://127.0.0.1:8000/webhooks/twilio/stream-status?replica_call_id={call_id}"' in body
    assert 'statusCallbackMethod="POST"' in body


def test_voice_outbound_full_real_flow_through_the_actual_access_token_endpoint(client, monkeypatch):
    """Not just the two halves tested in isolation elsewhere in this file — the
    REAL /api/voice/access-token response's voice_ticket, fed into the REAL
    webhook, exactly as app/static/live.html's device.connect() call does."""
    _configure_voice_settings(monkeypatch)
    _configure_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    token_resp = client.post(TOKEN_PATH, headers=headers, params={'call_id': call_id})
    assert token_resp.status_code == 200, token_resp.text
    voice_ticket = token_resp.json()['voice_ticket']

    params = {'To': '+49170123456', 'replica_voice_ticket': voice_ticket, 'CallSid': _fresh_call_sid()}
    sig = _sig(BASE + VOICE_PATH, params)
    r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 200, r.text
    assert f'<Parameter name="replica_call_id" value="{call_id}" />' in r.text


def test_voice_outbound_rejects_malformed_to_and_never_logs_it(client, monkeypatch, caplog):
    import logging
    _configure_webhook_settings(monkeypatch)
    params = {'To': 'not-a-real-phone-number', 'replica_voice_ticket': _ticket(call_id=1)}
    sig = _sig(BASE + VOICE_PATH, params)
    with caplog.at_level(logging.WARNING, logger='replica.webhooks'):
        r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 400
    assert 'not-a-real-phone-number' not in caplog.text


def test_voice_outbound_requires_replica_voice_ticket(client, monkeypatch):
    _configure_webhook_settings(monkeypatch)
    params = {'To': '+49170123456', 'replica_voice_ticket': ''}
    sig = _sig(BASE + VOICE_PATH, params)
    r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 400


def test_voice_outbound_rejects_a_ticket_signed_with_the_wrong_secret(client, monkeypatch):
    """Item 8: proves a browser cannot forge its own ticket — it does not, and
    cannot obtain, REPLICA_JWT_SECRET."""
    _configure_webhook_settings(monkeypatch)
    forged = pyjwt.encode(
        {'purpose': 'voice_call_ticket', 'call_id': 1, 'company_id': 1, 'user_id': 1},
        'attacker-guessed-wrong-secret', algorithm='HS256',
    )
    params = {'To': '+49170123456', 'replica_voice_ticket': forged}
    sig = _sig(BASE + VOICE_PATH, params)
    r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 403


def test_voice_outbound_rejects_an_expired_ticket(client, monkeypatch):
    _configure_webhook_settings(monkeypatch)
    expired = _ticket(call_id=1, ttl_seconds=-1)
    params = {'To': '+49170123456', 'replica_voice_ticket': expired}
    sig = _sig(BASE + VOICE_PATH, params)
    r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 403


def test_voice_outbound_rejects_a_ticket_whose_purpose_claim_is_not_voice_call_ticket(client, monkeypatch):
    """A login session token (create_access_token()) must never be usable
    here even if somehow supplied — distinct purpose claims, distinct trust
    boundaries."""
    from app.auth.security import create_access_token
    _configure_webhook_settings(monkeypatch)
    login_token = create_access_token(user_id=1, company_id=1, role='seller')
    params = {'To': '+49170123456', 'replica_voice_ticket': login_token}
    sig = _sig(BASE + VOICE_PATH, params)
    r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 403


def test_voice_outbound_rejects_ticket_whose_company_id_does_not_match_the_real_calls(client, monkeypatch):
    """A ticket's call_id/company_id pair is only ever produced by
    /api/voice/access-token from a real, already-tenant-checked call — this
    proves the webhook re-verifies rather than trusting the pairing blindly
    (defense in depth against, e.g., a ticket somehow minted for a stale/
    reassigned call)."""
    _configure_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)  # real call, but belongs to company_id=1
    mismatched = _ticket(call_id=call_id, company_id=999999)
    params = {'To': '+49170123456', 'replica_voice_ticket': mismatched}
    sig = _sig(BASE + VOICE_PATH, params)
    r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 403


def test_voice_outbound_rejects_ticket_when_consent_has_been_withdrawn_since_minting(client, monkeypatch):
    """Item 7/8's defense-in-depth: even a genuinely, correctly-issued ticket
    is re-checked against the CURRENT call/consent state, not just trusted
    because it was valid the moment it was minted."""
    _configure_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    ticket = _ticket(call_id=call_id)
    client.post(f'/api/calls/{call_id}/consent', headers=headers, json={'state': 'withdrawn'})
    params = {'To': '+49170123456', 'replica_voice_ticket': ticket}
    sig = _sig(BASE + VOICE_PATH, params)
    r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 403


def test_voice_outbound_ignores_a_raw_replica_call_id_and_trusts_only_the_ticket(client, monkeypatch):
    """THE core cross-tenant-manipulation regression test (item 8): simulates a
    compromised/malicious browser that holds a legitimately-issued ticket for
    ITS OWN call, but additionally sends a raw `replica_call_id` pointing at a
    COMPLETELY DIFFERENT tenant's call — proving the webhook never reads that
    raw value for anything; the resulting TwiML (and therefore the Media
    Stream this call will bind to) is always and only the ticket's own,
    already-verified call_id."""
    _configure_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    own_call_id = _create_call(client, headers)
    other = _make_second_tenant()  # a call belonging to an entirely different company
    own_ticket = _ticket(call_id=own_call_id, company_id=1)

    params = {
        'To': '+49170123456', 'replica_voice_ticket': own_ticket,
        'replica_call_id': str(other['call_id']),  # attacker-controlled, must be ignored entirely
        'CallSid': _fresh_call_sid(),
    }
    sig = _sig(BASE + VOICE_PATH, params)
    r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})

    assert r.status_code == 200, r.text
    assert f'<Parameter name="replica_call_id" value="{own_call_id}" />' in r.text
    assert f'value="{other["call_id"]}"' not in r.text


def test_voice_outbound_fails_closed_without_verified_caller_id_configured(client, monkeypatch):
    _configure_webhook_settings(monkeypatch, caller_id=None)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    params = {'To': '+49170123456', 'replica_voice_ticket': _ticket(call_id=call_id)}
    sig = _sig(BASE + VOICE_PATH, params)
    r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 500


def test_voice_outbound_escapes_verified_caller_id_in_the_actual_response(client, monkeypatch):
    # call_id now always comes from a verified ticket's int claim (never free
    # text) and `To` is regex-validated E.164 — neither can carry an XML
    # metacharacter anymore. The one remaining templated value that could
    # (an operator-misconfigured TWILIO_VERIFIED_CALLER_ID) must still be
    # escaped, matching the original ADR-060 finding this guards against.
    _configure_webhook_settings(monkeypatch, caller_id='+4917000"><Evil/>')
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    params = {'To': '+49170123456', 'replica_voice_ticket': _ticket(call_id=call_id), 'CallSid': _fresh_call_sid()}
    sig = _sig(BASE + VOICE_PATH, params)
    r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 200, r.text
    assert '<Evil/>' not in r.text
    assert '+4917000&quot;&gt;&lt;Evil/&gt;' in r.text


# --- ADR-064 (red-team follow-up): voice-ticket replay/idempotency + per-call concurrency lock ---

def test_voice_ticket_replayed_with_the_same_callsid_is_treated_as_an_idempotent_retry(client, monkeypatch):
    """Twilio can legitimately retry the exact same voice-webhook request
    (same CallSid — it hasn't given up on this call-setup attempt) — this
    must succeed identically both times, never be treated as a suspicious
    reuse."""
    _configure_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    ticket = _ticket(call_id=call_id)
    call_sid = _fresh_call_sid()
    params = {'To': '+49170123456', 'replica_voice_ticket': ticket, 'CallSid': call_sid}
    sig = _sig(BASE + VOICE_PATH, params)

    r1 = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    r2 = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r1.text == r2.text  # identical, deterministic TwiML both times


def test_voice_ticket_reused_for_a_different_callsid_is_rejected(client, monkeypatch):
    """The actual replay risk (item 1): the SAME ticket used to place a
    SECOND, independent real call (a different Twilio CallSid) must fail
    closed — Twilio retrying its own attempt is the only legitimate reuse."""
    _configure_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    ticket = _ticket(call_id=call_id)
    params_1 = {'To': '+49170123456', 'replica_voice_ticket': ticket, 'CallSid': _fresh_call_sid()}
    sig_1 = _sig(BASE + VOICE_PATH, params_1)
    r1 = client.post(VOICE_PATH, data=params_1, headers={'X-Twilio-Signature': sig_1})
    assert r1.status_code == 200, r1.text

    params_2 = {'To': '+49170123457', 'replica_voice_ticket': ticket, 'CallSid': _fresh_call_sid()}
    sig_2 = _sig(BASE + VOICE_PATH, params_2)
    r2 = client.post(VOICE_PATH, data=params_2, headers={'X-Twilio-Signature': sig_2})
    assert r2.status_code == 403


def test_voice_outbound_requires_callsid(client, monkeypatch):
    _configure_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    params = {'To': '+49170123456', 'replica_voice_ticket': _ticket(call_id=call_id)}  # no CallSid
    sig = _sig(BASE + VOICE_PATH, params)
    r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 400


def test_voice_ticket_missing_jti_claim_is_rejected(client, monkeypatch):
    """Defense in depth: a ticket somehow lacking the jti claim (should never
    happen — create_voice_call_ticket() always sets one) cannot be safely
    deduplicated, so it must be rejected rather than silently let through."""
    _configure_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    ticket_without_jti = pyjwt.encode(
        {'purpose': 'voice_call_ticket', 'call_id': call_id, 'company_id': 1, 'user_id': 1},
        'test-only-secret-not-for-production', algorithm='HS256',
    )
    params = {'To': '+49170123456', 'replica_voice_ticket': ticket_without_jti, 'CallSid': _fresh_call_sid()}
    sig = _sig(BASE + VOICE_PATH, params)
    r = client.post(VOICE_PATH, data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 403


def test_two_independently_minted_tickets_for_the_same_call_second_is_blocked_while_first_in_progress(client, monkeypatch):
    """item 2: two DIFFERENT, both individually valid tickets for the SAME
    call_id (e.g. two browser tabs, or a race on /api/voice/access-token) —
    the first commits to placing a real call; the second must be refused
    while that call is still in progress, even though its own ticket is
    perfectly legitimate and not a replay of the first's."""
    _configure_voice_settings(monkeypatch)
    _configure_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)

    ticket_a = client.post(TOKEN_PATH, headers=headers, params={'call_id': call_id}).json()['voice_ticket']
    ticket_b = client.post(TOKEN_PATH, headers=headers, params={'call_id': call_id}).json()['voice_ticket']
    assert ticket_a != ticket_b  # two genuinely independent tickets

    params_a = {'To': '+49170123456', 'replica_voice_ticket': ticket_a, 'CallSid': _fresh_call_sid()}
    sig_a = _sig(BASE + VOICE_PATH, params_a)
    r_a = client.post(VOICE_PATH, data=params_a, headers={'X-Twilio-Signature': sig_a})
    assert r_a.status_code == 200, r_a.text

    params_b = {'To': '+49170123457', 'replica_voice_ticket': ticket_b, 'CallSid': _fresh_call_sid()}
    sig_b = _sig(BASE + VOICE_PATH, params_b)
    r_b = client.post(VOICE_PATH, data=params_b, headers={'X-Twilio-Signature': sig_b})
    assert r_b.status_code == 409


def test_a_second_independent_call_attempt_succeeds_once_the_lock_is_released(client, monkeypatch):
    """Proves the 409 above is a real, temporary, per-call_id lock — not a
    permanent one-real-call-ever-for-this-call_id restriction — by releasing
    it directly (mirroring what app/main.py's /ws/twilio-media does on every
    exit path) and confirming a second call is then accepted."""
    from app.services.voice_call_guard import get_voice_call_lock

    _configure_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)

    params_a = {'To': '+49170123456', 'replica_voice_ticket': _ticket(call_id=call_id), 'CallSid': _fresh_call_sid()}
    sig_a = _sig(BASE + VOICE_PATH, params_a)
    assert client.post(VOICE_PATH, data=params_a, headers={'X-Twilio-Signature': sig_a}).status_code == 200

    params_b = {'To': '+49170123457', 'replica_voice_ticket': _ticket(call_id=call_id), 'CallSid': _fresh_call_sid()}
    sig_b = _sig(BASE + VOICE_PATH, params_b)
    assert client.post(VOICE_PATH, data=params_b, headers={'X-Twilio-Signature': sig_b}).status_code == 409

    get_voice_call_lock().release(call_id=call_id)

    params_c = {'To': '+49170123458', 'replica_voice_ticket': _ticket(call_id=call_id), 'CallSid': _fresh_call_sid()}
    sig_c = _sig(BASE + VOICE_PATH, params_c)
    assert client.post(VOICE_PATH, data=params_c, headers={'X-Twilio-Signature': sig_c}).status_code == 200


# --- POST /webhooks/twilio/stream-status (ADR-065) ------------------------------------

STREAM_STATUS_PATH = '/webhooks/twilio/stream-status'


def _stream_status_sig(call_id, extra_params=None):
    url = f'{BASE}{STREAM_STATUS_PATH}?replica_call_id={call_id}'
    params = dict(extra_params or {})
    return url, _sig(url, params)


def test_stream_status_rejects_missing_signature(client, monkeypatch):
    _configure_webhook_settings(monkeypatch)
    r = client.post(f'{STREAM_STATUS_PATH}?replica_call_id=1', data={'StreamEvent': 'stream-stopped'})
    assert r.status_code == 403


def test_stream_status_rejects_wrong_signature(client, monkeypatch):
    _configure_webhook_settings(monkeypatch)
    r = client.post(
        f'{STREAM_STATUS_PATH}?replica_call_id=1', data={'StreamEvent': 'stream-stopped'},
        headers={'X-Twilio-Signature': 'totally-wrong=='},
    )
    assert r.status_code == 403


def test_stream_status_stream_error_releases_the_lock_even_though_media_stream_never_connected(client, monkeypatch):
    """THE core scenario this ADR exists for: a call that never reaches
    /ws/twilio-media at all (busy/no-answer/failed <Stream> handshake) must
    still release the lock — via this callback alone, not the media-stream
    WebSocket's own `finally` block."""
    _configure_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)

    params_a = {'To': '+49170123456', 'replica_voice_ticket': _ticket(call_id=call_id), 'CallSid': _fresh_call_sid()}
    sig_a = _sig(BASE + VOICE_PATH, params_a)
    assert client.post(VOICE_PATH, data=params_a, headers={'X-Twilio-Signature': sig_a}).status_code == 200

    params_b = {'To': '+49170123457', 'replica_voice_ticket': _ticket(call_id=call_id), 'CallSid': _fresh_call_sid()}
    sig_b = _sig(BASE + VOICE_PATH, params_b)
    assert client.post(VOICE_PATH, data=params_b, headers={'X-Twilio-Signature': sig_b}).status_code == 409  # still locked

    url, sig = _stream_status_sig(call_id, {'StreamEvent': 'stream-error', 'StreamError': 'WebSocket - Handshake Error'})
    r = client.post(url, data={'StreamEvent': 'stream-error', 'StreamError': 'WebSocket - Handshake Error'}, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 200, r.text

    params_c = {'To': '+49170123458', 'replica_voice_ticket': _ticket(call_id=call_id), 'CallSid': _fresh_call_sid()}
    sig_c = _sig(BASE + VOICE_PATH, params_c)
    assert client.post(VOICE_PATH, data=params_c, headers={'X-Twilio-Signature': sig_c}).status_code == 200  # lock released


def test_stream_status_stream_stopped_releases_the_lock(client, monkeypatch):
    _configure_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    params_a = {'To': '+49170123456', 'replica_voice_ticket': _ticket(call_id=call_id), 'CallSid': _fresh_call_sid()}
    sig_a = _sig(BASE + VOICE_PATH, params_a)
    assert client.post(VOICE_PATH, data=params_a, headers={'X-Twilio-Signature': sig_a}).status_code == 200

    url, sig = _stream_status_sig(call_id, {'StreamEvent': 'stream-stopped'})
    assert client.post(url, data={'StreamEvent': 'stream-stopped'}, headers={'X-Twilio-Signature': sig}).status_code == 200

    params_b = {'To': '+49170123457', 'replica_voice_ticket': _ticket(call_id=call_id), 'CallSid': _fresh_call_sid()}
    sig_b = _sig(BASE + VOICE_PATH, params_b)
    assert client.post(VOICE_PATH, data=params_b, headers={'X-Twilio-Signature': sig_b}).status_code == 200


def test_stream_status_stream_started_does_not_release_the_lock(client, monkeypatch):
    _configure_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    params_a = {'To': '+49170123456', 'replica_voice_ticket': _ticket(call_id=call_id), 'CallSid': _fresh_call_sid()}
    sig_a = _sig(BASE + VOICE_PATH, params_a)
    assert client.post(VOICE_PATH, data=params_a, headers={'X-Twilio-Signature': sig_a}).status_code == 200

    url, sig = _stream_status_sig(call_id, {'StreamEvent': 'stream-started'})
    assert client.post(url, data={'StreamEvent': 'stream-started'}, headers={'X-Twilio-Signature': sig}).status_code == 200

    params_b = {'To': '+49170123457', 'replica_voice_ticket': _ticket(call_id=call_id), 'CallSid': _fresh_call_sid()}
    sig_b = _sig(BASE + VOICE_PATH, params_b)
    assert client.post(VOICE_PATH, data=params_b, headers={'X-Twilio-Signature': sig_b}).status_code == 409  # still locked


def test_stream_status_is_idempotent_across_repeated_calls(client, monkeypatch):
    """Twilio may retry this callback too — releasing an already-released
    (or never-held) lock must never raise or behave differently."""
    _configure_webhook_settings(monkeypatch)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    params_a = {'To': '+49170123456', 'replica_voice_ticket': _ticket(call_id=call_id), 'CallSid': _fresh_call_sid()}
    sig_a = _sig(BASE + VOICE_PATH, params_a)
    assert client.post(VOICE_PATH, data=params_a, headers={'X-Twilio-Signature': sig_a}).status_code == 200

    url, sig = _stream_status_sig(call_id, {'StreamEvent': 'stream-error'})
    for _ in range(3):
        r = client.post(url, data={'StreamEvent': 'stream-error'}, headers={'X-Twilio-Signature': sig})
        assert r.status_code == 200, r.text


def test_stream_status_missing_replica_call_id_does_not_crash(client, monkeypatch):
    _configure_webhook_settings(monkeypatch)
    url = f'{BASE}{STREAM_STATUS_PATH}'  # no ?replica_call_id=... at all
    sig = _sig(url, {'StreamEvent': 'stream-error'})
    r = client.post(STREAM_STATUS_PATH, data={'StreamEvent': 'stream-error'}, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 200


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
