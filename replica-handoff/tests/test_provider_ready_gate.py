"""Provider-Ready Gate: unified apply_turn() dispatcher, the append-only
ConversationStateEvent history, and end-to-end trace_id propagation.
"""
from conftest import auth_headers

from app.models import ConversationStateEvent
from app.services.conversation_state import apply_turn, initial_state
from app.services.language_sync import analyze_language


def _create_call(client, headers, **overrides):
    payload = {'seller_id': 1, 'prospect_company': 'Acme', 'prospect_type': 'b2b'}
    payload.update(overrides)
    r = client.post('/api/calls', headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return r.json()['id']


# --- apply_turn() unified dispatcher (pure) ------------------------------------------

def test_apply_turn_prospect_returns_state_transition_and_decision():
    state = initial_state(call_id=1)
    new_state, transition, decision = apply_turn(state, 'prospect', 'Guten Tag.', analyze_language('Guten Tag.'))
    assert new_state.turn_index == 1
    assert decision is not None
    assert 'transition' not in decision  # popped out into its own return value
    assert transition['from_phase'] == 'greeting'
    assert set(transition) == {'from_phase', 'to_phase', 'event_type', 'objection_type', 'sales_action', 'trigger'}


def test_apply_turn_seller_returns_state_transition_and_no_decision():
    state = initial_state(call_id=1)
    new_state, transition, decision = apply_turn(state, 'seller', 'Guten Tag, hier ist Ihr Ansprechpartner.')
    assert decision is None
    assert transition['event_type'] == 'seller_action'
    assert transition['sales_action'] == 'greeting'
    assert transition['from_phase'] == transition['to_phase'] == 'greeting'  # bookkeeping only, no phase change
    assert new_state.last_seller_action == 'greeting'


# --- ConversationStateEvent history: one row per processed turn ---------------------

def test_prospect_turn_via_copilot_writes_history_row(client, db_session):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    client.post(f'/api/calls/{call_id}/consent', headers=headers, json={'state': 'granted'})

    client.post('/api/copilot/suggest', headers=headers, json={'call_id': call_id, 'utterance': 'Guten Tag.'})

    rows = db_session.query(ConversationStateEvent).filter_by(call_id=call_id).all()
    assert len(rows) == 1
    assert rows[0].speaker == 'prospect'
    assert rows[0].from_phase == 'greeting'


def test_seller_turn_via_turns_endpoint_writes_history_row(client, db_session):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    client.post(f'/api/calls/{call_id}/consent', headers=headers, json={'state': 'granted'})

    client.post(f'/api/calls/{call_id}/turns', headers=headers, json={'speaker': 'seller', 'text': 'Guten Tag, mein Name ist Anna.'})

    rows = db_session.query(ConversationStateEvent).filter_by(call_id=call_id).all()
    assert len(rows) == 1
    assert rows[0].speaker == 'seller'
    assert rows[0].event_type == 'seller_action'
    assert rows[0].sales_action == 'greeting'


def test_history_accumulates_across_multiple_turns_in_order(client, db_session):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    client.post(f'/api/calls/{call_id}/consent', headers=headers, json={'state': 'granted'})

    client.post(f'/api/calls/{call_id}/turns', headers=headers, json={'speaker': 'seller', 'text': 'Guten Tag.'})
    client.post('/api/copilot/suggest', headers=headers, json={'call_id': call_id, 'utterance': 'Guten Tag, wer spricht da?'})
    client.post('/api/copilot/suggest', headers=headers, json={'call_id': call_id, 'utterance': 'Ja, worum geht es?'})

    rows = db_session.query(ConversationStateEvent).filter_by(call_id=call_id).order_by(ConversationStateEvent.id).all()
    assert [r.speaker for r in rows] == ['seller', 'prospect', 'prospect']
    # a duplicate delivery of the same turn_id must not add a second history row —
    # covered explicitly by the dedup tests in test_turn_identity.py.


# --- trace_id propagation -------------------------------------------------------------

def test_response_carries_trace_id_header(client):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.get('/api/auth/me', headers=headers)
    assert 'x-trace-id' in {k.lower() for k in r.headers.keys()}


def test_caller_supplied_trace_id_is_echoed_back(client):
    headers = {**auth_headers(client, 'haydar@replica-pilot.example'), 'X-Trace-Id': 'my-fixed-trace-id'}
    r = client.get('/api/auth/me', headers=headers)
    assert r.headers['x-trace-id'] == 'my-fixed-trace-id'


def test_suggestion_records_trace_id_from_request_body(client, db_session):
    from app.models import Suggestion

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.post('/api/copilot/suggest', headers=headers, json={'utterance': 'Guten Tag.', 'trace_id': 'trace-from-caller'})
    assert r.status_code == 200
    assert r.json()['trace_id'] == 'trace-from-caller'

    row = db_session.get(Suggestion, r.json()['suggestion_id'])
    assert row.trace_id == 'trace-from-caller'


def test_suggestion_falls_back_to_middleware_trace_id_when_caller_supplies_none(client, db_session):
    from app.models import Suggestion

    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.post('/api/copilot/suggest', headers=headers, json={'utterance': 'Guten Tag.'})
    assert r.status_code == 200
    assert r.json()['trace_id']  # non-empty: middleware-generated fallback
    assert r.json()['trace_id'] == r.headers['x-trace-id']

    row = db_session.get(Suggestion, r.json()['suggestion_id'])
    assert row.trace_id == r.json()['trace_id']
