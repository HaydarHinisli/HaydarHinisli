"""Provider-Ready Gate hardening (Punkt 1): crash-safety of turn processing.

Terminology (docs/DECISIONS.md ADR-034): this is **idempotent, effectively-once**
processing — not "exactly-once delivery" (a provider may call REPLICA more than once
for the same real turn) but the persisted *effect* is applied exactly once per
successful attempt, and a failed attempt leaves zero trace, because claim + every
side effect (ConversationState update, ConversationStateEvent, Turn/Suggestion) share
one DB transaction with exactly one commit at the very end of the request. A crash or
exception before that commit rolls EVERYTHING back together, including the claim
itself — so a retry reprocesses the turn from scratch rather than being wrongly
treated as already-handled.

These tests simulate "the process/request fails partway through" by monkeypatching a
function called partway through the endpoint to raise. FastAPI's TestClient
re-raises unhandled exceptions by default (matching real ASGI server behavior close
enough for this purpose): app/db.py's get_db() still runs its `finally: db.close()`
during stack unwinding, which rolls back any uncommitted transaction — exactly the
crash scenario being tested.
"""
import threading

import pytest

from conftest import auth_headers

from app.models import Call, ConversationStateEvent, ProcessedTurnEvent, Suggestion, Turn


def _create_call(client, headers, **overrides):
    payload = {'seller_id': 1, 'prospect_company': 'Acme', 'prospect_type': 'b2b'}
    payload.update(overrides)
    r = client.post('/api/calls', headers=headers, json=payload)
    assert r.status_code == 200, r.text
    call_id = r.json()['id']
    client.post(f'/api/calls/{call_id}/consent', headers=headers, json={'state': 'granted'})
    return call_id


def _counts(db_session, call_id):
    return {
        'turns': db_session.query(Turn).filter_by(call_id=call_id).count(),
        'suggestions': db_session.query(Suggestion).filter_by(call_id=call_id).count(),
        'state_events': db_session.query(ConversationStateEvent).filter_by(call_id=call_id).count(),
        'processed_turn_events': db_session.query(ProcessedTurnEvent).filter_by(call_id=call_id).count(),
    }


# --- normal successful processing (reference case) -----------------------------------

def test_normal_successful_processing_persists_everything_together(client, db_session):
    import app.main as main_module

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)

    r = client.post('/api/copilot/suggest', headers=headers, json={'call_id': call_id, 'utterance': 'Guten Tag.', 'turn_id': 'atomic-ok-1'})
    assert r.status_code == 200

    counts = _counts(db_session, call_id)
    assert counts['suggestions'] == 1
    assert counts['state_events'] == 1
    assert counts['processed_turn_events'] == 1


# --- copilot(): crash right after claim, before any side effect ----------------------

def test_copilot_crash_right_after_claim_leaves_no_trace_and_retry_succeeds(client, db_session, monkeypatch):
    import app.main as main_module

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    payload = {'call_id': call_id, 'utterance': 'Wir haben bereits einen Anbieter.', 'turn_id': 'atomic-crash-1'}

    def boom(*a, **k):
        raise RuntimeError('simulated crash right after claim')

    with monkeypatch.context() as m:
        m.setattr(main_module, 'suggest_with_state', boom)
        with pytest.raises(RuntimeError):
            client.post('/api/copilot/suggest', headers=headers, json=payload)

    counts = _counts(db_session, call_id)
    assert counts == {'turns': 0, 'suggestions': 0, 'state_events': 0, 'processed_turn_events': 0}

    retry = client.post('/api/copilot/suggest', headers=headers, json=payload)
    assert retry.status_code == 200
    assert retry.json().get('duplicate') is not True
    assert _counts(db_session, call_id)['suggestions'] == 1


# --- copilot(): crash after state update, before the Suggestion/commit ---------------

def test_copilot_crash_after_state_update_before_completion_rolls_back_state_too(client, db_session, monkeypatch):
    import app.main as main_module

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    payload = {'call_id': call_id, 'utterance': 'Wir haben bereits einen Anbieter.', 'turn_id': 'atomic-crash-2'}

    def boom(*a, **k):
        raise RuntimeError('simulated crash after state update')

    with monkeypatch.context() as m:
        # Suggestion() is constructed AFTER _apply_state_to_row()/_record_state_event()
        # have already mutated the (uncommitted) session — the state change must not
        # survive if everything after it fails.
        m.setattr(main_module, 'Suggestion', boom)
        with pytest.raises(RuntimeError):
            client.post('/api/copilot/suggest', headers=headers, json=payload)

    counts = _counts(db_session, call_id)
    assert counts == {'turns': 0, 'suggestions': 0, 'state_events': 0, 'processed_turn_events': 0}

    state = client.get(f'/api/calls/{call_id}/conversation-state', headers=headers).json()
    assert state['turn_index'] == 0  # never advanced

    retry = client.post('/api/copilot/suggest', headers=headers, json=payload)
    assert retry.status_code == 200
    assert retry.json().get('duplicate') is not True
    counts_after = _counts(db_session, call_id)
    assert counts_after == {'turns': 0, 'suggestions': 1, 'state_events': 1, 'processed_turn_events': 1}


# --- add_turn(): crash right after claim (Turn never even gets created) --------------

def test_add_turn_crash_right_after_claim_leaves_no_trace_and_retry_succeeds(client, db_session, monkeypatch):
    import app.main as main_module

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    payload = {'speaker': 'seller', 'text': 'Guten Tag, hier spricht Anna.', 'turn_id': 'atomic-crash-3'}

    def boom(*a, **k):
        raise RuntimeError('simulated crash right after claim')

    with monkeypatch.context() as m:
        m.setattr(main_module, 'Turn', boom)
        with pytest.raises(RuntimeError):
            client.post(f'/api/calls/{call_id}/turns', headers=headers, json=payload)

    counts = _counts(db_session, call_id)
    assert counts == {'turns': 0, 'suggestions': 0, 'state_events': 0, 'processed_turn_events': 0}

    retry = client.post(f'/api/calls/{call_id}/turns', headers=headers, json=payload)
    assert retry.status_code == 200
    assert retry.json().get('duplicate') is not True
    assert _counts(db_session, call_id)['turns'] == 1


# --- add_turn(): crash after the seller-turn state update, before commit -------------

def test_add_turn_crash_after_state_update_before_completion_rolls_back_state_too(client, db_session, monkeypatch):
    import app.main as main_module

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    payload = {'speaker': 'seller', 'text': 'Guten Tag, hier spricht Anna.', 'turn_id': 'atomic-crash-4'}

    def boom(*a, **k):
        raise RuntimeError('simulated crash after state update, before final commit')

    with monkeypatch.context() as m:
        # record_result() is the last thing called before db.commit() — by this point
        # the Turn row and the seller-turn ConversationState/ConversationStateEvent
        # updates are already queued (uncommitted) on the session.
        m.setattr(main_module, 'record_result', boom)
        with pytest.raises(RuntimeError):
            client.post(f'/api/calls/{call_id}/turns', headers=headers, json=payload)

    counts = _counts(db_session, call_id)
    assert counts == {'turns': 0, 'suggestions': 0, 'state_events': 0, 'processed_turn_events': 0}

    state = client.get(f'/api/calls/{call_id}/conversation-state', headers=headers).json()
    assert state['last_seller_action'] is None  # never persisted

    retry = client.post(f'/api/calls/{call_id}/turns', headers=headers, json=payload)
    assert retry.status_code == 200
    counts_after = _counts(db_session, call_id)
    assert counts_after == {'turns': 1, 'suggestions': 0, 'state_events': 1, 'processed_turn_events': 1}
    state_after = client.get(f'/api/calls/{call_id}/conversation-state', headers=headers).json()
    assert state_after['last_seller_action'] == 'greeting'


# --- redelivery of an already-completed turn: cached, never reprocessed --------------

def test_redelivery_of_completed_turn_returns_cached_result_without_reprocessing(client, db_session):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    payload = {'call_id': call_id, 'utterance': 'Guten Tag.', 'turn_id': 'atomic-redelivery-1'}

    first = client.post('/api/copilot/suggest', headers=headers, json=payload)
    assert first.status_code == 200
    first_id = first.json()['suggestion_id']

    for _ in range(3):
        retry = client.post('/api/copilot/suggest', headers=headers, json=payload)
        assert retry.status_code == 200
        assert retry.json()['duplicate'] is True
        assert retry.json()['suggestion_id'] == first_id

    assert _counts(db_session, call_id)['suggestions'] == 1


# --- parallel claim of the same turn (real thread concurrency) -----------------------

def test_parallel_claim_of_same_turn_on_copilot_suggest_processes_exactly_once(client, db_session):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    payload = {'call_id': call_id, 'utterance': 'Guten Tag, worum geht es?', 'turn_id': 'atomic-parallel-1'}

    results = []

    def _fire():
        results.append(client.post('/api/copilot/suggest', headers=headers, json=payload))

    threads = [threading.Thread(target=_fire) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(r.status_code == 200 for r in results)
    non_duplicates = [r for r in results if r.json().get('duplicate') is not True]
    duplicates = [r for r in results if r.json().get('duplicate') is True]
    assert len(non_duplicates) == 1
    assert len(duplicates) == 5
    # every duplicate points back at the SAME suggestion the winner created
    winner_id = non_duplicates[0].json()['suggestion_id']
    assert all(r.json()['suggestion_id'] == winner_id for r in duplicates)
    assert _counts(db_session, call_id)['suggestions'] == 1


def test_parallel_claim_of_same_turn_on_add_turns_processes_exactly_once(client, db_session):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    payload = {'speaker': 'prospect', 'text': 'Wir haben bereits einen Anbieter.', 'turn_id': 'atomic-parallel-2'}

    results = []

    def _fire():
        results.append(client.post(f'/api/calls/{call_id}/turns', headers=headers, json=payload))

    threads = [threading.Thread(target=_fire) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(r.status_code == 200 for r in results)
    non_duplicates = [r for r in results if r.json().get('duplicate') is not True]
    assert len(non_duplicates) == 1
    assert _counts(db_session, call_id)['turns'] == 1
