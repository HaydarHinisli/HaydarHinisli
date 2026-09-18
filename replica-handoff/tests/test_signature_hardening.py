"""Provider-Ready Gate hardening (Punkt 3): Twilio signature validation via the
official `twilio.request_validator.RequestValidator`, with REPLICA responsible for
secret selection, public-URL construction (including query string), and fail-closed
error handling. See docs/DECISIONS.md ADR-036.
"""
from twilio.request_validator import RequestValidator

from app.secrets import get_secrets_provider
from app.webhooks.security import compute_twilio_signature, verify_twilio_signature

TOKEN = 'test-auth-token'
BASE = 'http://127.0.0.1:8000'
PATH = '/webhooks/twilio/call-status'


def _sig(url, params, token=TOKEN):
    return RequestValidator(token).compute_signature(url, params)


# --- delegation sanity: our wrapper matches the official validator exactly ----------

def test_compute_and_verify_delegate_to_official_validator():
    params = {'CallSid': 'CA1', 'CallStatus': 'completed'}
    url = BASE + PATH
    sig = compute_twilio_signature(url, params, TOKEN)
    assert sig == RequestValidator(TOKEN).compute_signature(url, params)
    assert verify_twilio_signature(url, params, sig, TOKEN)


def test_missing_signature_fails_closed():
    params = {'CallSid': 'CA1', 'CallStatus': 'completed'}
    assert not verify_twilio_signature(BASE + PATH, params, None, TOKEN)


def test_wrong_signature_fails_closed():
    params = {'CallSid': 'CA1', 'CallStatus': 'completed'}
    assert not verify_twilio_signature(BASE + PATH, params, 'clearly-not-a-real-signature==', TOKEN)


# --- endpoint-level: the full acceptance matrix --------------------------------------

def _post(client, monkeypatch, *, params, signature, request_path=PATH, base_url=BASE, auth_token=TOKEN):
    """Posts to `request_path` (what Twilio's request line actually was) after
    configuring the settings our OWN layer is responsible for (secret, public base
    URL). `signature` is whatever the caller computed against whichever URL it wants
    to test — the two are deliberately independent so a test can make them agree or
    disagree on purpose."""
    monkeypatch.setattr('app.main.settings.twilio_auth_token', auth_token)
    monkeypatch.setattr('app.main.settings.replica_public_base_url', base_url)
    headers = {'X-Twilio-Signature': signature} if signature else {}
    return client.post(request_path, data=params, headers=headers)


def test_endpoint_accepts_valid_signature(client, monkeypatch):
    params = {'CallSid': 'CAsig1', 'CallStatus': 'completed'}
    sig = _sig(BASE + PATH, params)
    r = _post(client, monkeypatch, params=params, signature=sig)
    assert r.status_code == 200, r.text


def test_endpoint_rejects_missing_signature(client, monkeypatch):
    params = {'CallSid': 'CAsig2', 'CallStatus': 'completed'}
    monkeypatch.setattr('app.main.settings.twilio_auth_token', TOKEN)
    r = client.post(PATH, data=params)  # no X-Twilio-Signature header at all
    assert r.status_code == 403


def test_endpoint_rejects_wrong_signature(client, monkeypatch):
    params = {'CallSid': 'CAsig3', 'CallStatus': 'completed'}
    r = _post(client, monkeypatch, params=params, signature='totally-wrong-signature==')
    assert r.status_code == 403


def test_endpoint_requires_query_string_to_be_part_of_signed_url(client, monkeypatch):
    params = {'CallSid': 'CAsig4', 'CallStatus': 'completed'}
    path_with_query = PATH + '?foo=bar&test=1'
    monkeypatch.setattr('app.main.settings.twilio_auth_token', TOKEN)
    monkeypatch.setattr('app.main.settings.replica_public_base_url', BASE)

    # signature computed WITHOUT the query string must be rejected...
    sig_without_query = _sig(BASE + PATH, params)
    r_wrong = client.post(path_with_query, data=params, headers={'X-Twilio-Signature': sig_without_query})
    assert r_wrong.status_code == 403

    # ...while a signature computed WITH the exact query string is accepted.
    sig_with_query = _sig(BASE + path_with_query, params)
    r_right = client.post(path_with_query, data=params, headers={'X-Twilio-Signature': sig_with_query})
    assert r_right.status_code == 200, r_right.text


def test_endpoint_handles_url_encoded_post_values(client, monkeypatch):
    # values with characters that MUST be form-urlencoded on the wire: space, '&',
    # '=', and non-ASCII — httpx encodes these automatically when posting `data=`.
    params = {'CallSid': 'CAsig5', 'CallStatus': 'completed', 'From': '+49 170 123&456=x', 'Caller': 'Müller & Söhne'}
    sig = _sig(BASE + PATH, params)
    r = _post(client, monkeypatch, params=params, signature=sig)
    assert r.status_code == 200, r.text


def test_endpoint_signs_over_extra_unknown_post_parameters_too(client, monkeypatch):
    params = {'CallSid': 'CAsig6', 'CallStatus': 'completed', 'SomeFutureTwilioField': 'unexpected-value'}
    sig = _sig(BASE + PATH, params)
    r = _post(client, monkeypatch, params=params, signature=sig)
    assert r.status_code == 200, r.text

    # a signature computed WITHOUT the extra param must not validate against a
    # request that actually included it (proves all params are covered, not a subset)
    sig_missing_extra = _sig(BASE + PATH, {'CallSid': 'CAsig6b', 'CallStatus': 'completed'})
    r_tampered = _post(
        client, monkeypatch,
        params={'CallSid': 'CAsig6b', 'CallStatus': 'completed', 'SomeFutureTwilioField': 'injected-after-signing'},
        signature=sig_missing_extra,
    )
    assert r_tampered.status_code == 403


def test_endpoint_ignores_request_url_scheme_and_host_behind_a_reverse_proxy(client, monkeypatch):
    # Simulate a TLS-terminating reverse proxy: Twilio actually called
    # https://replica.example.com/..., but whatever ASGI transport TestClient uses
    # internally reports its own scheme/host on request.url. Signing against the
    # PUBLIC url (not TestClient's internal one) must still validate, proving the
    # verification never falls back to request.url's own scheme/host.
    public_base = 'https://replica.example.com'
    params = {'CallSid': 'CAsig7', 'CallStatus': 'completed'}
    sig = _sig(public_base + PATH, params)
    r = _post(client, monkeypatch, params=params, signature=sig, base_url=public_base)
    assert r.status_code == 200, r.text


def test_endpoint_rejects_when_configured_public_base_url_is_wrong(client, monkeypatch):
    # Twilio actually signed against the REAL public URL...
    real_public_base = 'https://replica.example.com'
    params = {'CallSid': 'CAsig8', 'CallStatus': 'completed'}
    sig = _sig(real_public_base + PATH, params)
    # ...but REPLICA is misconfigured with a DIFFERENT base URL. There must be no
    # silent fallback (e.g. to request.url) that accidentally makes this pass anyway.
    wrong_public_base = 'https://wrong-host.example.com'
    r = _post(client, monkeypatch, params=params, signature=sig, base_url=wrong_public_base)
    assert r.status_code == 403


def test_endpoint_fails_closed_when_auth_token_is_none(client, monkeypatch):
    params = {'CallSid': 'CAsig9', 'CallStatus': 'completed'}
    sig = _sig(BASE + PATH, params, token='irrelevant')
    r = _post(client, monkeypatch, params=params, signature=sig, auth_token=None)
    assert r.status_code == 403


def test_endpoint_fails_closed_when_secrets_backend_cannot_resolve_token(client, monkeypatch):
    params = {'CallSid': 'CAsig10', 'CallStatus': 'completed'}
    sig = _sig(BASE + PATH, params)
    monkeypatch.setattr('app.main.settings.replica_public_base_url', BASE)
    monkeypatch.setenv('REPLICA_SECRETS_BACKEND', 'vault')
    get_secrets_provider.cache_clear()
    try:
        r = client.post(PATH, data=params, headers={'X-Twilio-Signature': sig})
        assert r.status_code == 403
    finally:
        monkeypatch.delenv('REPLICA_SECRETS_BACKEND', raising=False)
        get_secrets_provider.cache_clear()
