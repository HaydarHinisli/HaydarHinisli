"""End-to-end live-copilot flow through the central Processing Permission Resolver
(no legacy bypass — see docs/DECISIONS.md ADR-020), plus a suggestion-latency
performance baseline against the PRODUCT_SPEC.md targets (P50<=500ms, P95<=800ms).
"""
import statistics
import time

from conftest import auth_headers


def _create_call(client, headers, **overrides):
    payload = {'seller_id': 1, 'prospect_company': 'Acme', 'prospect_type': 'b2b'}
    payload.update(overrides)
    r = client.post('/api/calls', headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return r.json()['id']


def test_sandbox_suggest_without_call_id_needs_no_consent(client):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.post('/api/copilot/suggest', headers=headers, json={'utterance': 'Wir haben bereits einen Anbieter.'})
    assert r.status_code == 200
    assert 'policy_decision' not in r.json()  # sandbox mode: no per-call policy gate


def test_live_copilot_blocked_without_consent(client):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    r = client.post('/api/copilot/suggest', headers=headers, json={'call_id': call_id, 'utterance': 'Wir haben bereits einen Anbieter.'})
    assert r.status_code == 403
    assert r.json()['detail']['result'] == 'requires_consent'


def test_live_copilot_allowed_after_consent(client):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    consent = client.post(f'/api/calls/{call_id}/consent', headers=headers, json={'state': 'granted'})
    assert consent.status_code == 200
    r = client.post('/api/copilot/suggest', headers=headers, json={'call_id': call_id, 'utterance': 'Wir haben bereits einen Anbieter.'})
    assert r.status_code == 200
    assert r.json()['policy_decision']['result'] == 'allowed'


def test_turns_blocked_then_allowed_matches_copilot_gate(client):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    blocked = client.post(f'/api/calls/{call_id}/turns', headers=headers, json={'speaker': 'prospect', 'text': 'Hallo'})
    assert blocked.status_code == 403

    client.post(f'/api/calls/{call_id}/consent', headers=headers, json={'state': 'granted'})
    allowed = client.post(f'/api/calls/{call_id}/turns', headers=headers, json={'speaker': 'prospect', 'text': 'Hallo'})
    assert allowed.status_code == 200
    assert allowed.json()['policy_decision']['result'] == 'allowed'


def test_call_without_jurisdiction_context_fails_closed(client):
    # No jurisdiction_country override and a company without country_code would fall
    # back to the conservative DEFAULT bucket; here we simulate "insufficient context"
    # for the most consumer-protection-sensitive action directly via the resolver API.
    headers = auth_headers(client, 'admin@replica-pilot.example')
    r = client.post(
        '/api/policy/resolve', headers=headers,
        json={'action': 'record_audio', 'country_code': None, 'prospect_type': 'unknown'},
    )
    assert r.status_code == 200
    body = r.json()
    assert body['result'] in ('requires_legal_review', 'denied')


def test_withdrawing_consent_blocks_further_live_assist(client):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    client.post(f'/api/calls/{call_id}/consent', headers=headers, json={'state': 'granted'})
    ok = client.post('/api/copilot/suggest', headers=headers, json={'call_id': call_id, 'utterance': 'Testfrage?'})
    assert ok.status_code == 200

    withdraw = client.post(f'/api/calls/{call_id}/consents/live_copilot_processing/withdraw', headers=headers)
    assert withdraw.status_code == 200

    blocked = client.post('/api/copilot/suggest', headers=headers, json={'call_id': call_id, 'utterance': 'Noch eine Frage?'})
    assert blocked.status_code == 403
    assert blocked.json()['detail']['result'] == 'denied'


def test_suggestion_latency_baseline(client):
    """Informational performance baseline for the deterministic Fast Path (see
    docs/PRODUCT_SPEC.md §8 and docs/ARCHITECTURE.md §8: RSL P50<=500ms, P95<=800ms
    end-of-turn-to-UI targets under real telephony conditions). This measures only
    the in-process engine + HTTP round trip through TestClient (no network, no ASR),
    so it is a floor/sanity check, not the real RSL measurement Sprint 2/3 must add
    once streaming ASR and UI push exist.
    """
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    utterances = [
        'Wir haben bereits einen Anbieter.',
        'Ich habe wenig Zeit.',
        'Schicken Sie mir eine Mail.',
        'Das ist uns zu teuer.',
        'Wer ist bei Ihnen zuständig?',
    ]
    samples = []
    for _ in range(20):
        for utterance in utterances:
            started = time.perf_counter()
            r = client.post('/api/copilot/suggest', headers=headers, json={'utterance': utterance})
            elapsed_ms = (time.perf_counter() - started) * 1000
            assert r.status_code == 200
            samples.append(elapsed_ms)

    samples.sort()
    p50 = statistics.median(samples)
    p95 = samples[int(len(samples) * 0.95) - 1]
    print(f'\n[perf baseline] suggestion round-trip via TestClient: P50={p50:.2f}ms P95={p95:.2f}ms n={len(samples)}')
    # Generous ceiling: this is an in-process TestClient call (no real network/ASR),
    # so it should be far under the PRODUCT_SPEC targets; a regression this large
    # would indicate something is now doing real I/O per suggestion.
    assert p50 < 100
    assert p95 < 200
