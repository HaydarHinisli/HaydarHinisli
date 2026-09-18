"""Provider-Ready Gate: Event/Turn Identity & Deduplication (app/services/turn_identity.py),
wired into POST /calls/{id}/turns and POST /copilot/suggest so a webhook retry,
reconnect, or duplicate final transcript can never process the same real turn twice.
"""
from conftest import auth_headers

from app.services.turn_identity import claim_turn, record_result, synthesize_turn_id


def _create_call(client, headers, **overrides):
    payload = {'seller_id': 1, 'prospect_company': 'Acme', 'prospect_type': 'b2b'}
    payload.update(overrides)
    r = client.post('/api/calls', headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return r.json()['id']


# --- pure claim_turn() ---------------------------------------------------------------

def test_synthesize_turn_id_is_deterministic_per_call_action_index():
    assert synthesize_turn_id(1, 'transcribe', 0) == synthesize_turn_id(1, 'transcribe', 0)
    assert synthesize_turn_id(1, 'transcribe', 0) != synthesize_turn_id(1, 'transcribe', 1)
    assert synthesize_turn_id(1, 'transcribe', 0) != synthesize_turn_id(1, 'live_assist', 0)


def test_claim_turn_is_exactly_once_per_call_action_turn_id(db_session):
    claimed1, row1 = claim_turn(db_session, company_id=1, call_id=1, action='transcribe', turn_id='t-1')
    db_session.commit()
    assert claimed1 is True

    claimed2, row2 = claim_turn(db_session, company_id=1, call_id=1, action='transcribe', turn_id='t-1')
    assert claimed2 is False
    assert row2.id == row1.id


def test_claim_turn_scopes_uniqueness_to_call_and_action(db_session):
    # Same turn_id, different action -> legitimately claimed twice (today's two-endpoint
    # MVP split: 'transcribe' via /turns and 'live_assist' via /copilot/suggest both
    # process the same utterance, see docs/DECISIONS.md ADR-031/032).
    claimed_a, _ = claim_turn(db_session, company_id=1, call_id=2, action='transcribe', turn_id='shared')
    claimed_b, _ = claim_turn(db_session, company_id=1, call_id=2, action='live_assist', turn_id='shared')
    db_session.commit()
    assert claimed_a is True
    assert claimed_b is True


def test_record_result_stores_cached_payload_for_duplicates(db_session):
    claimed, row = claim_turn(db_session, company_id=1, call_id=3, action='transcribe', turn_id='t-cache')
    assert claimed is True
    record_result(row, {'id': 42})
    db_session.commit()

    claimed_again, row_again = claim_turn(db_session, company_id=1, call_id=3, action='transcribe', turn_id='t-cache')
    assert claimed_again is False
    assert row_again.result_ref == {'id': 42}


# --- endpoint-level: POST /calls/{id}/turns -------------------------------------------

def test_add_turn_with_repeated_turn_id_is_not_stored_twice(client):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    client.post(f'/api/calls/{call_id}/consent', headers=headers, json={'state': 'granted'})

    payload = {'speaker': 'prospect', 'text': 'Wir haben bereits einen Anbieter.', 'turn_id': 'provider-turn-abc'}
    first = client.post(f'/api/calls/{call_id}/turns', headers=headers, json=payload)
    assert first.status_code == 200, first.text
    assert 'duplicate' not in first.json()

    retry = client.post(f'/api/calls/{call_id}/turns', headers=headers, json=payload)
    assert retry.status_code == 200
    assert retry.json()['duplicate'] is True
    assert retry.json()['id'] == first.json()['id']

    review = client.get(f'/api/calls/{call_id}/review', headers=headers)
    assert review.status_code == 200


def test_add_turn_without_turn_id_still_works_via_synthesized_default(client):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    client.post(f'/api/calls/{call_id}/consent', headers=headers, json={'state': 'granted'})

    r1 = client.post(f'/api/calls/{call_id}/turns', headers=headers, json={'speaker': 'seller', 'text': 'Guten Tag.'})
    r2 = client.post(f'/api/calls/{call_id}/turns', headers=headers, json={'speaker': 'seller', 'text': 'Wie geht es Ihnen?'})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()['id'] != r2.json()['id']  # distinct synthesized turn_ids, both stored


# --- endpoint-level: POST /copilot/suggest --------------------------------------------

def test_copilot_suggest_with_repeated_turn_id_does_not_reprocess(client):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    client.post(f'/api/calls/{call_id}/consent', headers=headers, json={'state': 'granted'})

    payload = {'call_id': call_id, 'utterance': 'Wir haben bereits einen Anbieter.', 'turn_id': 'provider-live-1'}
    first = client.post('/api/copilot/suggest', headers=headers, json=payload)
    assert first.status_code == 200, first.text
    first_suggestion_id = first.json()['suggestion_id']

    retry = client.post('/api/copilot/suggest', headers=headers, json=payload)
    assert retry.status_code == 200
    assert retry.json()['duplicate'] is True
    assert retry.json()['suggestion_id'] == first_suggestion_id

    # A genuinely duplicate delivery must not advance the conversation state a second
    # time — turn_index should still reflect exactly one processed prospect turn.
    state = client.get(f'/api/calls/{call_id}/conversation-state', headers=headers).json()
    assert state['turn_index'] == 1
