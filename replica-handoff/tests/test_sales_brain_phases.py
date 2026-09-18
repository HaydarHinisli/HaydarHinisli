"""Conversation-phase detection and smalltalk-appropriateness in SalesBrain.

Covers the phases named in the product brief (greeting, rapport/smalltalk,
transition, discovery, pitch, objection, negotiation, closing, wrap_up — 'opening'
is documented as not auto-detected from prospect text alone, see sales_brain.py) and
the five specific smalltalk questions: is smalltalk appropriate, does the prospect
want to skip to business, brief reaction vs follow-up question, and transition timing.
"""
from app.services.copilot import suggest
from app.services.sales_brain import analyze_smalltalk, decide
from app.services.language_sync import analyze_language


def _decide(text, *, turn_index=0):
    return decide(text, analyze_language(text), turn_index=turn_index)


# --- the two worked examples from the product brief -------------------------------

def test_prospect_smalltalk_gets_brief_reaction_not_forced_transition():
    r = _decide('Ich komme gerade aus einem Meeting.', turn_index=0)
    assert r['phase'] == 'rapport_smalltalk'
    assert r['smalltalk']['smalltalk_appropriate'] is True
    assert r['smalltalk']['prospect_wants_business'] is False
    assert r['smalltalk']['suggest_brief_reaction'] is True
    assert r['smalltalk']['suggest_follow_up_question'] is True
    assert r['smalltalk']['suggest_transition_now'] is False


def test_prospect_wants_business_skips_smalltalk_entirely():
    r = _decide('Ja, worum geht es?', turn_index=0)
    assert r['phase'] == 'transition'
    assert r['smalltalk']['prospect_wants_business'] is True
    assert r['smalltalk']['smalltalk_appropriate'] is False
    assert r['smalltalk']['suggest_brief_reaction'] is False
    assert r['smalltalk']['suggest_transition_now'] is True
    assert r['strategy'] == 'transition_to_business'


# --- remaining phases ---------------------------------------------------------------

def test_greeting_phase_at_call_start():
    r = _decide('Guten Tag.', turn_index=0)
    assert r['phase'] == 'greeting'
    assert r['strategy'] == 'greeting_and_permission'


def test_negotiation_phase():
    r = _decide('Welche Konditionen und welchen Rabatt können Sie uns anbieten?', turn_index=5)
    assert r['phase'] == 'negotiation'
    assert r['strategy'] == 'trade_concessions_for_commitment'


def test_closing_phase():
    r = _decide('Wie geht es jetzt weiter, was sind die nächsten Schritte?', turn_index=6)
    assert r['phase'] == 'closing'
    assert r['strategy'] == 'confirm_concrete_next_step'


def test_wrap_up_phase():
    r = _decide('Vielen Dank für Ihre Zeit, auf Wiederhören.', turn_index=8)
    assert r['phase'] == 'wrap_up'
    assert r['strategy'] == 'confirm_and_close_politely'


def test_generic_question_maps_to_pitch_phase():
    r = _decide('Wie funktioniert das genau?', turn_index=3)
    assert r['phase'] == 'pitch'
    assert r['event'] == 'question'


def test_generic_discovery_stays_discovery_phase():
    r = _decide('Wir schauen uns aktuell verschiedene Optionen an.', turn_index=2)
    assert r['phase'] == 'discovery'
    assert r['event'] == 'discovery'


# --- smalltalk must not be artificially prolonged ------------------------------------

def test_smalltalk_follow_up_not_suggested_after_first_exchange():
    early = analyze_smalltalk('Ich komme gerade aus einem Meeting.', turn_index=0)
    later = analyze_smalltalk('Wir hatten heute schon drei Meetings.', turn_index=2)
    assert early['suggest_follow_up_question'] is True
    assert later['suggest_follow_up_question'] is False
    assert later['suggest_transition_now'] is True  # push toward business once smalltalk has run its course


def test_smalltalk_never_invented_without_a_prospect_anchor():
    # No smalltalk markers at all -> never claim smalltalk is appropriate.
    r = analyze_smalltalk('Wir haben aktuell keinen Bedarf.', turn_index=0)
    assert r['smalltalk_appropriate'] is False
    assert r['suggest_brief_reaction'] is False


# --- regression: existing objection handling must be byte-for-byte unchanged --------

def test_existing_supplier_objection_unaffected_by_phase_feature():
    r = _decide('Wir haben bereits einen Anbieter und sind zufrieden.')
    assert r['phase'] == 'objection'
    assert r['strategy'] == 'discover_buying_criteria'
    assert 'aktuellen' in r['suggestion'].lower()


def test_time_pressure_objection_unaffected_by_phase_feature():
    r = _decide('Ich habe wenig Zeit. Sagen Sie kurz, worum es geht.')
    assert r['phase'] == 'objection'
    assert r['strategy'] == 'permission_and_relevance'


def test_price_objection_unaffected_by_phase_feature():
    r = _decide('Das ist uns deutlich zu teuer.')
    assert r['phase'] == 'objection'
    assert r['strategy'] == 'reestablish_value_before_price'


# --- suggest() threads turn_index through end-to-end ---------------------------------

def test_suggest_infers_turn_index_from_recent_context_length():
    r = suggest('Vielen Dank für Ihre Zeit, auf Wiederhören.', recent_context=['a'] * 8)
    assert r['phase'] == 'wrap_up'


def test_suggest_explicit_turn_index_overrides_recent_context_length():
    r = suggest('Guten Tag.', recent_context=['a'] * 5, turn_index=0)
    assert r['phase'] == 'greeting'


def test_suggest_fast_path_still_fast_with_phase_detection():
    r = suggest('Ich komme gerade aus einem Meeting.')
    assert r['latency_ms'] < 100


# --- end-to-end through the API -------------------------------------------------------

def test_copilot_suggest_endpoint_returns_phase_and_smalltalk(client):
    from conftest import auth_headers
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.post('/api/copilot/suggest', headers=headers, json={'utterance': 'Ich komme gerade aus einem Meeting.'})
    assert r.status_code == 200
    body = r.json()
    assert body['phase'] == 'rapport_smalltalk'
    assert body['smalltalk']['smalltalk_appropriate'] is True
