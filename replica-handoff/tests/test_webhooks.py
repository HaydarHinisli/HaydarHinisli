"""Provider-Ready Gate: webhook signature verification + delivery idempotency."""
from app.webhooks.security import compute_twilio_signature, verify_twilio_signature
from app.webhooks.idempotency import claim_webhook_delivery
from app.models import WebhookDelivery

URL = 'http://127.0.0.1:8000/webhooks/twilio/call-status'
PARAMS = {'CallSid': 'CA123', 'CallStatus': 'completed', 'To': '+491701234567'}
TOKEN = 'test-auth-token'


# --- pure signature functions -------------------------------------------------------

def test_verify_twilio_signature_accepts_correctly_computed_signature():
    sig = compute_twilio_signature(URL, PARAMS, TOKEN)
    assert verify_twilio_signature(URL, PARAMS, sig, TOKEN)


def test_verify_twilio_signature_rejects_wrong_token():
    sig = compute_twilio_signature(URL, PARAMS, TOKEN)
    assert not verify_twilio_signature(URL, PARAMS, sig, 'wrong-token')


def test_verify_twilio_signature_rejects_tampered_params():
    sig = compute_twilio_signature(URL, PARAMS, TOKEN)
    tampered = {**PARAMS, 'CallStatus': 'failed'}
    assert not verify_twilio_signature(URL, tampered, sig, TOKEN)


def test_verify_twilio_signature_fails_closed_on_missing_signature():
    assert not verify_twilio_signature(URL, PARAMS, None, TOKEN)


def test_verify_twilio_signature_fails_closed_on_missing_auth_token():
    sig = compute_twilio_signature(URL, PARAMS, TOKEN)
    assert not verify_twilio_signature(URL, PARAMS, sig, None)


# --- delivery idempotency (pure DB-level) -------------------------------------------

def test_claim_webhook_delivery_is_true_once_then_false(db_session):
    first = claim_webhook_delivery(db_session, provider='twilio', event_type='call-status', external_id='CA1:completed')
    db_session.commit()
    assert first is True

    second = claim_webhook_delivery(db_session, provider='twilio', event_type='call-status', external_id='CA1:completed')
    assert second is False
    assert db_session.query(WebhookDelivery).filter_by(external_id='CA1:completed').count() == 1


def test_claim_webhook_delivery_distinguishes_by_full_key(db_session):
    a = claim_webhook_delivery(db_session, provider='twilio', event_type='call-status', external_id='CA2:ringing')
    b = claim_webhook_delivery(db_session, provider='twilio', event_type='call-status', external_id='CA2:completed')
    db_session.commit()
    assert a is True
    assert b is True  # different CallStatus -> different external_id -> not a duplicate


# --- endpoint-level: POST /webhooks/twilio/call-status ------------------------------

def test_twilio_webhook_accepts_valid_signature(client, monkeypatch):
    import app.main as main_module
    monkeypatch.setattr(main_module.settings, 'twilio_auth_token', TOKEN)
    params = {'CallSid': 'CAendpoint1', 'CallStatus': 'completed'}
    sig = compute_twilio_signature(URL, params, TOKEN)
    r = client.post('/webhooks/twilio/call-status', data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 200, r.text
    assert r.json() == {'ok': True, 'applied': True}


def test_twilio_webhook_rejects_invalid_signature(client, monkeypatch):
    import app.main as main_module
    monkeypatch.setattr(main_module.settings, 'twilio_auth_token', TOKEN)
    params = {'CallSid': 'CAendpoint2', 'CallStatus': 'completed'}
    r = client.post('/webhooks/twilio/call-status', data=params, headers={'X-Twilio-Signature': 'not-a-real-signature'})
    assert r.status_code == 403


def test_twilio_webhook_fails_closed_when_no_auth_token_configured(client, monkeypatch):
    import app.main as main_module
    monkeypatch.setattr(main_module.settings, 'twilio_auth_token', None)
    params = {'CallSid': 'CAendpoint3', 'CallStatus': 'completed'}
    sig = compute_twilio_signature(URL, params, 'irrelevant-because-no-token-configured')
    r = client.post('/webhooks/twilio/call-status', data=params, headers={'X-Twilio-Signature': sig})
    assert r.status_code == 403


def test_twilio_webhook_retry_is_idempotent(client, monkeypatch):
    import app.main as main_module
    monkeypatch.setattr(main_module.settings, 'twilio_auth_token', TOKEN)
    params = {'CallSid': 'CAendpoint4', 'CallStatus': 'completed'}
    sig = compute_twilio_signature(URL, params, TOKEN)

    first = client.post('/webhooks/twilio/call-status', data=params, headers={'X-Twilio-Signature': sig})
    assert first.status_code == 200
    assert first.json().get('duplicate') is not True

    retry = client.post('/webhooks/twilio/call-status', data=params, headers={'X-Twilio-Signature': sig})
    assert retry.status_code == 200
    assert retry.json()['duplicate'] is True
