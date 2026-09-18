"""Provider-Ready Gate hardening (Punkt 2): Twilio status-callback duplicates AND
out-of-order/stale event handling. See docs/DECISIONS.md ADR-035.
"""
import threading

from app.webhooks.call_status import get_or_create_provider_status, is_newer_event, parse_sequence_number
from app.webhooks.security import compute_twilio_signature
from app.models import AuditEvent, CallProviderStatus

TOKEN = 'test-auth-token'
URL = 'http://127.0.0.1:8000/webhooks/twilio/call-status'


def _sig(params):
    return compute_twilio_signature(URL, params, TOKEN)


def _post(client, **params):
    return client.post('/webhooks/twilio/call-status', data=params, headers={'X-Twilio-Signature': _sig(params)})


# --- parse_sequence_number() ---------------------------------------------------------

def test_parse_sequence_number_valid_and_missing_and_garbage():
    assert parse_sequence_number('0') == 0
    assert parse_sequence_number('7') == 7
    assert parse_sequence_number(None) is None
    assert parse_sequence_number('not-a-number') is None


# --- is_newer_event() pure ordering logic --------------------------------------------

def test_first_event_for_a_call_is_always_newer():
    assert is_newer_event(incoming_status='ringing', incoming_sequence=0, last_status=None, last_sequence=None)


def test_sequence_number_is_authoritative_when_both_sides_have_one():
    # a later-arriving event with a LOWER sequence number is stale, even if its
    # status string would otherwise look like forward progress
    assert not is_newer_event(incoming_status='in-progress', incoming_sequence=1, last_status='completed', last_sequence=2)
    assert is_newer_event(incoming_status='completed', incoming_sequence=2, last_status='ringing', last_sequence=1)


def test_terminal_status_is_a_one_way_door_without_sequence_numbers():
    assert not is_newer_event(incoming_status='in-progress', incoming_sequence=None, last_status='completed', last_sequence=None)
    assert not is_newer_event(incoming_status='ringing', incoming_sequence=None, last_status='failed', last_sequence=None)


def test_status_rank_fallback_without_sequence_numbers():
    assert is_newer_event(incoming_status='in-progress', incoming_sequence=None, last_status='ringing', last_sequence=None)
    assert not is_newer_event(incoming_status='ringing', incoming_sequence=None, last_status='in-progress', last_sequence=None)


# --- get_or_create_provider_status() ---------------------------------------------------

def test_get_or_create_provider_status_is_idempotent_and_correlates_call_id(db_session):
    row1 = get_or_create_provider_status(db_session, provider='twilio', external_call_id='CAxyz', call_id=None)
    db_session.commit()
    assert row1.last_status is None

    row2 = get_or_create_provider_status(db_session, provider='twilio', external_call_id='CAxyz', call_id=42)
    db_session.commit()
    assert row2.id == row1.id
    assert row2.call_id == 42  # correlated once known, without creating a second row
    assert db_session.query(CallProviderStatus).filter_by(external_call_id='CAxyz').count() == 1


# --- endpoint-level: ordering + duplicates -------------------------------------------

def test_multiple_legitimate_events_same_call_sid_are_all_applied_in_order(client, monkeypatch):
    monkeypatch.setattr('app.main.settings.twilio_auth_token', TOKEN)
    call_sid = 'CAorder1'

    r1 = _post(client, CallSid=call_sid, CallStatus='ringing', SequenceNumber='0')
    r2 = _post(client, CallSid=call_sid, CallStatus='in-progress', SequenceNumber='1')
    r3 = _post(client, CallSid=call_sid, CallStatus='completed', SequenceNumber='2')

    assert [r.json()['applied'] for r in (r1, r2, r3)] == [True, True, True]


def test_identical_event_delivered_twice_is_a_duplicate_not_reprocessed(client, monkeypatch):
    monkeypatch.setattr('app.main.settings.twilio_auth_token', TOKEN)
    params = dict(CallSid='CAorder2', CallStatus='completed', SequenceNumber='5')

    first = _post(client, **params)
    assert first.status_code == 200
    assert first.json() == {'ok': True, 'applied': True}

    retry = _post(client, **params)
    assert retry.status_code == 200
    assert retry.json() == {'ok': True, 'duplicate': True}


def test_out_of_order_delivery_does_not_regress_call_state(client, monkeypatch, db_session):
    monkeypatch.setattr('app.main.settings.twilio_auth_token', TOKEN)
    call_sid = 'CAorder3'

    completed = _post(client, CallSid=call_sid, CallStatus='completed', SequenceNumber='2')
    assert completed.json()['applied'] is True

    # a genuinely NEW event (different SequenceNumber -> not a duplicate delivery)
    # describing an OLDER point in time arrives late
    late_in_progress = _post(client, CallSid=call_sid, CallStatus='in-progress', SequenceNumber='1')
    assert late_in_progress.status_code == 200
    assert late_in_progress.json() == {'ok': True, 'applied': False}

    status = db_session.query(CallProviderStatus).filter_by(provider='twilio', external_call_id=call_sid).one()
    assert status.last_status == 'completed'  # NOT regressed to 'in-progress'
    assert status.last_sequence_number == 2


def test_stale_event_is_still_durably_recorded_not_silently_dropped(client, monkeypatch, db_session):
    monkeypatch.setattr('app.main.settings.twilio_auth_token', TOKEN)
    from app.models import Call, Company, Seller
    from datetime import datetime

    company = Company(name='Stale Event Test Co', country_code='DE', network_learning_opt_in=False)
    db_session.add(company)
    db_session.flush()
    seller = Seller(company_id=company.id, name='Stale Tester', hired_at=datetime.utcnow(), product_started_at=datetime.utcnow())
    db_session.add(seller)
    db_session.flush()
    call = Call(company_id=company.id, seller_id=seller.id, jurisdiction_country='DE', external_call_id='CAorder4')
    db_session.add(call)
    db_session.commit()

    _post(client, CallSid='CAorder4', CallStatus='completed', SequenceNumber='9')
    stale = _post(client, CallSid='CAorder4', CallStatus='ringing', SequenceNumber='3')
    assert stale.json()['applied'] is False

    from app.webhooks.idempotency import claim_webhook_delivery
    # the stale event's delivery is durably claimed (recorded), so re-delivering the
    # exact same stale event again is recognized as a duplicate, not reprocessed twice
    reclaimed = claim_webhook_delivery(db_session, provider='twilio', event_type='call-status', external_id='CAorder4:3')
    assert reclaimed is False  # already recorded by the webhook call above

    stale_audit = db_session.query(AuditEvent).filter_by(entity_type='call', entity_id=str(call.id), action='call.status.ringing.stale').all()
    assert len(stale_audit) == 1
    assert stale_audit[0].payload['applied'] is False


def test_newest_after_older_is_the_normal_forward_progress_case(client, monkeypatch, db_session):
    monkeypatch.setattr('app.main.settings.twilio_auth_token', TOKEN)
    call_sid = 'CAorder5'
    older = _post(client, CallSid=call_sid, CallStatus='ringing', SequenceNumber='0')
    newer = _post(client, CallSid=call_sid, CallStatus='completed', SequenceNumber='1')
    assert older.json()['applied'] is True
    assert newer.json()['applied'] is True
    status = db_session.query(CallProviderStatus).filter_by(external_call_id=call_sid).one()
    assert status.last_status == 'completed'


def test_ordering_fallback_without_sequence_numbers_still_protects_terminal_state(client, monkeypatch, db_session):
    monkeypatch.setattr('app.main.settings.twilio_auth_token', TOKEN)
    call_sid = 'CAorder6'
    _post(client, CallSid=call_sid, CallStatus='completed')  # no SequenceNumber at all
    late = _post(client, CallSid=call_sid, CallStatus='ringing')  # different CallStatus -> not a duplicate
    assert late.json()['applied'] is False
    status = db_session.query(CallProviderStatus).filter_by(external_call_id=call_sid).one()
    assert status.last_status == 'completed'


def test_parallel_identical_delivery_results_in_exactly_one_applied_event(client, monkeypatch):
    monkeypatch.setattr('app.main.settings.twilio_auth_token', TOKEN)
    params = dict(CallSid='CAorder7', CallStatus='completed', SequenceNumber='1')

    results = []

    def _fire():
        results.append(_post(client, **params))

    threads = [threading.Thread(target=_fire) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(r.status_code == 200 for r in results)
    applied_count = sum(1 for r in results if r.json().get('applied') is True)
    duplicate_count = sum(1 for r in results if r.json().get('duplicate') is True)
    assert applied_count == 1
    assert duplicate_count == 4
