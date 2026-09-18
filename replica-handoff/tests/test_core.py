from app.services.copilot import suggest
from app.services.experiments import assign_variant
from app.services.language_sync import analyze_language
from app.services.reward import call_reward
from app.services.sales_brain import classify_sales_event


def test_existing_supplier():
    r = suggest('Wir haben bereits einen Anbieter und sind zufrieden.')
    assert r['strategy'] == 'discover_buying_criteria'
    assert 'aktuellen' in r['suggestion'].lower()


def test_time_pressure():
    r = suggest('Ich habe wenig Zeit. Sagen Sie kurz, worum es geht.')
    assert r['strategy'] == 'permission_and_relevance'
    assert r['language_policy']['directness'] == 'high'


def test_advanced_language():
    p = analyze_language('Wie unterscheidet sich Ihre Implementierung konkret von regelbasierter Sales-Automation und bestehender Infrastruktur?')
    assert p['complexity'] == 'high'


def test_fast_path_is_locally_fast():
    r = suggest('Schicken Sie mir das per Mail.')
    assert r['latency_ms'] < 100


def test_price_event():
    assert classify_sales_event('Das ist uns deutlich zu teuer.') == 'price'


def test_reward_prefers_held_opportunity():
    basic = call_reward(meeting_booked=True, meeting_held=False, qualified_opportunity=False)
    better = call_reward(meeting_booked=True, meeting_held=True, qualified_opportunity=True)
    assert better > basic


def test_experiment_assignment_is_deterministic():
    a = assign_variant(42, 'opener_v1', ['a','b'])
    b = assign_variant(42, 'opener_v1', ['a','b'])
    assert a == b
