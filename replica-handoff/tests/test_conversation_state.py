"""Sprint 1.5 — call-bound Conversation State: phase transitions understood across the
whole running call, not just per-utterance reclassification.
"""
from app.services.conversation_state import apply_prospect_turn, apply_seller_turn, initial_state
from app.services.language_sync import analyze_language

from conftest import auth_headers


def _advance(state, text):
    return apply_prospect_turn(state, text, analyze_language(text))


# --- the transition chain the product brief calls out explicitly -------------------

def test_full_progression_greeting_to_discovery_to_objection_to_negotiation_to_closing():
    state = initial_state(call_id=1)
    state, d1 = _advance(state, 'Guten Tag.')
    assert d1['phase'] == 'greeting'

    state, d2 = _advance(state, 'Ich komme gerade aus einem Meeting, aber gerne.')
    assert d2['phase'] == 'rapport_smalltalk'
    assert state.smalltalk_turns == 1

    state, d3 = _advance(state, 'Ja, worum geht es?')
    assert d3['phase'] == 'transition'
    assert state.business_transition_started is True

    state, d4 = _advance(state, 'Wir schauen uns aktuell verschiedene Optionen an.')
    assert d4['phase'] == 'discovery'
    assert state.discovery_started is True
    assert state.opening_completed is True

    state, d5 = _advance(state, 'Das ist uns deutlich zu teuer.')
    assert d5['phase'] == 'objection'
    assert state.active_objection == 'price'
    assert state.price_discussed is True

    state, d6 = _advance(state, 'Welche Konditionen und welchen Rabatt können Sie anbieten?')
    assert d6['phase'] == 'negotiation'
    assert state.active_objection is None
    assert state.resolved_objections == ['price']

    state, d7 = _advance(state, 'Wie geht es jetzt weiter, was sind die nächsten Schritte?')
    assert d7['phase'] == 'closing'
    assert state.turn_index == 7
    assert state.previous_phase == 'negotiation'


# --- business anchors inside smalltalk must not be flattened into generic rapport ---

def test_business_anchor_in_smalltalk_becomes_discovery_opportunity():
    state = initial_state(call_id=2)
    state, _ = _advance(state, 'Guten Tag.')
    text = 'Ich komme gerade aus einem Meeting zu unserem neuen Standort, das war ein echtes Problem.'
    state, decision = _advance(state, text)
    assert decision['phase'] == 'discovery'
    assert state.discovery_started is True
    assert state.smalltalk_turns == 0  # never counted as plain smalltalk


def test_plain_smalltalk_without_anchor_still_follows_mvp_default():
    # No business anchor -> the MVP default (push toward transition after the first
    # exchange) still applies; this is a default, not a hard rule (see the anchor test).
    state = initial_state(call_id=3)
    state, d1 = _advance(state, 'Ich komme gerade aus einem Meeting.')
    assert d1['phase'] == 'rapport_smalltalk'
    state, d2 = _advance(state, 'Wir hatten heute schon drei Meetings.')
    assert d2['phase'] == 'transition'
    assert state.smalltalk_turns == 2


# --- once real progress is made, a stray aside must not reset the call -------------

def test_front_phase_regression_guard_during_discovery():
    state = initial_state(call_id=4)
    for text in ('Guten Tag.', 'Ja, worum geht es?', 'Wir schauen uns Optionen an.'):
        state, _ = _advance(state, text)
    assert state.current_phase == 'discovery'

    state, decision = _advance(state, 'Wir hatten übrigens noch ein Meeting dazu.')
    assert decision['phase'] == 'discovery'
    assert state.current_phase == 'discovery'


def test_front_phase_regression_guard_resumes_opening_before_discovery_started():
    # business_transition_started but not yet discovery_started -> resume at 'opening'
    state = initial_state(call_id=5)
    state, d1 = _advance(state, 'Ja, worum geht es?')
    assert d1['phase'] == 'transition'
    assert state.discovery_started is False
    assert state.business_transition_started is True

    state, d2 = _advance(state, 'Ich hatte gerade ein Meeting dazu.')
    # a smalltalk-flavored aside right after transition must not go backward to
    # rapport_smalltalk/greeting; it resumes at 'opening' per _resume_phase().
    assert d2['phase'] == 'opening'


# --- objection lifecycle -------------------------------------------------------------

def test_switching_between_different_objections_resolves_the_first():
    state = initial_state(call_id=6)
    state, d1 = _advance(state, 'Das ist uns deutlich zu teuer.')
    assert d1['phase'] == 'objection'
    assert state.active_objection == 'price'

    state, d2 = _advance(state, 'Wir haben bereits einen Anbieter und sind zufrieden.')
    assert d2['phase'] == 'objection'
    assert state.active_objection == 'existing_supplier'
    assert state.resolved_objections == ['price']

    state, d3 = _advance(state, 'Ok, verstanden, das klingt spannend.')
    assert d3['phase'] != 'objection'
    assert state.active_objection is None
    assert state.resolved_objections == ['price', 'existing_supplier']


def test_repeating_the_same_objection_does_not_duplicate_resolved_list():
    state = initial_state(call_id=7)
    state, _ = _advance(state, 'Das ist uns deutlich zu teuer.')
    state, _ = _advance(state, 'Der Preis ist wirklich zu hoch für uns, kein Budget.')
    assert state.active_objection == 'price'
    assert state.resolved_objections == []


def test_price_discussed_persists_after_objection_resolved():
    state = initial_state(call_id=8)
    state, _ = _advance(state, 'Das ist uns deutlich zu teuer.')
    state, _ = _advance(state, 'Ok, verstanden, das klingt gut.')
    assert state.price_discussed is True
    assert state.active_objection is None


# --- negotiation/closing imply prior progress even if not independently observed ----

def test_negotiation_implies_discovery_and_opening_flags():
    state = initial_state(call_id=9)
    state, decision = _advance(state, 'Welche Konditionen und welchen Rabatt können Sie anbieten?')
    assert decision['phase'] == 'negotiation'
    assert state.discovery_started is True
    assert state.opening_completed is True
    assert state.business_transition_started is True


# --- seller-turn bookkeeping never drives the phase machine -------------------------

def test_seller_turn_updates_bookkeeping_not_phase():
    state = initial_state(call_id=10)
    state, _ = _advance(state, 'Guten Tag.')
    before_phase = state.current_phase
    state = apply_seller_turn(state, 'Guten Tag, hier ist Ihr Ansprechpartner von REPLICA.')
    assert state.current_phase == before_phase  # unchanged — sellers don't drive phase
    assert state.last_seller_action == 'greeting'

    state = apply_seller_turn(state, 'Was ist Ihnen bei Ihrer aktuellen Lösung wichtig?')
    assert state.last_seller_action == 'discovery_question'


def test_seller_pitch_action_sets_pitch_delivered():
    state = initial_state(call_id=11)
    state = apply_seller_turn(state, 'Wir helfen Vertriebsteams, mehr qualifizierte Termine zu erzielen und Umsatz zu steigern.')
    assert state.last_seller_action == 'pitch'
    assert state.pitch_delivered is True


# --- HTTP-level: state actually persists across multiple API calls for one call_id --

def test_conversation_state_persists_across_suggest_calls_via_api(client):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = client.post('/api/calls', headers=headers, json={'seller_id': 1, 'prospect_type': 'b2b'}).json()['id']
    client.post(f'/api/calls/{call_id}/consent', headers=headers, json={'state': 'granted'})

    r1 = client.post('/api/copilot/suggest', headers=headers, json={'call_id': call_id, 'utterance': 'Guten Tag.'})
    assert r1.json()['phase'] == 'greeting'
    assert r1.json()['conversation_state']['turn_index'] == 1

    r2 = client.post('/api/copilot/suggest', headers=headers, json={'call_id': call_id, 'utterance': 'Ja, worum geht es?'})
    assert r2.json()['phase'] == 'transition'
    assert r2.json()['conversation_state']['turn_index'] == 2
    assert r2.json()['conversation_state']['previous_phase'] == 'greeting'

    state = client.get(f'/api/calls/{call_id}/conversation-state', headers=headers).json()
    assert state['current_phase'] == 'transition'
    assert state['turn_index'] == 2


def test_sandbox_suggest_never_creates_conversation_state(client):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.post('/api/copilot/suggest', headers=headers, json={'utterance': 'Guten Tag.'})
    assert r.status_code == 200
    assert 'conversation_state' not in r.json()


def test_conversation_state_endpoint_is_tenant_scoped(client):
    from datetime import datetime, timedelta
    from app.auth.security import hash_password
    from app.db import SessionLocal
    from app.models import Call, Company, Seller, User

    db = SessionLocal()
    try:
        company = Company(name='Rival Corp State Test', country_code='DE', network_learning_opt_in=False)
        db.add(company)
        db.flush()
        now = datetime.utcnow()
        seller = Seller(company_id=company.id, name='Riva2', hired_at=now - timedelta(days=10), product_started_at=now - timedelta(days=10))
        db.add(seller)
        db.flush()
        db.add(User(company_id=company.id, email='riva2@rival.example', password_hash=hash_password('replica-demo-2026'), role='seller'))
        call = Call(company_id=company.id, seller_id=seller.id, jurisdiction_country='DE')
        db.add(call)
        db.flush()
        other_call_id = call.id
        db.commit()
    finally:
        db.close()

    headers_a = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.get(f'/api/calls/{other_call_id}/conversation-state', headers=headers_a)
    assert r.status_code == 404
