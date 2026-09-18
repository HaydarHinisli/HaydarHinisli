"""Sprint 3A (docs/DECISIONS.md ADR-048): /ws/live/{call_id} auth-via-first-message
handshake, tenant isolation, and POST /api/suggestions/{id}/render-ack.
"""
import json
import time
from datetime import datetime, timedelta

import pytest
from conftest import DEMO_PASSWORD, auth_headers, login

from app.auth.security import hash_password
from app.db import SessionLocal
from app.models import Call, Company, Seller, Suggestion, TurnLatencyTrace, User


def _create_call(client, headers, **overrides):
    payload = {'seller_id': 1, 'prospect_company': 'Acme', 'prospect_type': 'b2b'}
    payload.update(overrides)
    r = client.post('/api/calls', headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return r.json()['id']


def _make_second_tenant():
    db = SessionLocal()
    try:
        company = Company(name='Rival Live Corp', country_code='DE', network_learning_opt_in=False)
        db.add(company)
        db.flush()
        now = datetime.utcnow()
        seller = Seller(company_id=company.id, name='Riva', hired_at=now - timedelta(days=10), product_started_at=now - timedelta(days=10))
        db.add(seller)
        db.flush()
        user = User(company_id=company.id, email='riva-live@rival.example', password_hash=hash_password(DEMO_PASSWORD), role='seller')
        db.add(user)
        call = Call(company_id=company.id, seller_id=seller.id, prospect_company='Rival Prospect', jurisdiction_country='DE')
        db.add(call)
        db.flush()
        db.commit()
        return {'company_id': company.id, 'call_id': call.id}
    finally:
        db.close()


@pytest.fixture(scope='module')
def other_tenant(client):
    return _make_second_tenant()


# --- WS auth-via-first-message handshake ---------------------------------------------

def test_ws_closes_when_first_message_is_not_an_auth_frame(client):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    with pytest.raises(Exception):
        with client.websocket_connect(f'/ws/live/{call_id}') as ws:
            ws.send_text(json.dumps({'type': 'not-auth'}))
            ws.receive_text()  # connection should already be closed by the server


def test_ws_closes_on_invalid_token(client):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    with pytest.raises(Exception):
        with client.websocket_connect(f'/ws/live/{call_id}') as ws:
            ws.send_text(json.dumps({'type': 'auth', 'token': 'not-a-real-jwt'}))
            ws.receive_text()


def test_ws_closes_for_nonexistent_call(client):
    token = login(client, 'haydar@replica-pilot.example')
    with pytest.raises(Exception):
        with client.websocket_connect('/ws/live/99999999') as ws:
            ws.send_text(json.dumps({'type': 'auth', 'token': token}))
            ws.receive_text()


def test_ws_closes_for_cross_tenant_call(client, other_tenant):
    """Tenant A's valid token must not be usable to open a live-push connection
    for tenant B's call_id — same fail-closed, non-distinguishing posture as
    _get_call_or_404() over HTTP."""
    token = login(client, 'haydar@replica-pilot.example')
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/live/{other_tenant['call_id']}") as ws:
            ws.send_text(json.dumps({'type': 'auth', 'token': token}))
            ws.receive_text()


def test_ws_accepts_valid_auth_and_call_ownership(client):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    token = login(client, 'haydar@replica-pilot.example')
    with client.websocket_connect(f'/ws/live/{call_id}') as ws:
        ws.send_text(json.dumps({'type': 'auth', 'token': token}))
        # No suggestion has been pushed for this brand-new call yet, so there is
        # no sync message — closing cleanly (no exception) is enough to prove the
        # handshake succeeded.


def test_ws_auth_timeout_closes_the_connection(client, monkeypatch):
    import app.main as main_module
    monkeypatch.setattr(main_module, '_LIVE_AUTH_TIMEOUT_S', 0.05)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    with pytest.raises(Exception):
        with client.websocket_connect(f'/ws/live/{call_id}') as ws:
            time.sleep(0.2)  # let the server-side timeout fire before we send anything
            ws.send_text(json.dumps({'type': 'auth', 'token': 'irrelevant'}))
            ws.receive_text()


# --- Origin allowlist (Fix-Sprint, docs/DECISIONS.md ADR-051) ------------------------

def test_ws_rejects_any_origin_in_production_without_an_allowlist_configured(client, monkeypatch):
    import app.main as main_module
    monkeypatch.setattr(main_module.settings, 'replica_env', 'production')
    monkeypatch.setattr(main_module.settings, 'replica_allowed_ws_origins', None)
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    with pytest.raises(Exception):
        with client.websocket_connect(f'/ws/live/{call_id}', headers={'origin': 'https://app.replica.example'}) as ws:
            ws.receive_text()


def test_ws_rejects_disallowed_origin_in_production(client, monkeypatch):
    import app.main as main_module
    monkeypatch.setattr(main_module.settings, 'replica_env', 'production')
    monkeypatch.setattr(main_module.settings, 'replica_allowed_ws_origins', 'https://app.replica.example')
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    with pytest.raises(Exception):
        with client.websocket_connect(f'/ws/live/{call_id}', headers={'origin': 'https://evil.example'}) as ws:
            ws.receive_text()


def test_ws_rejects_missing_origin_header_in_production(client, monkeypatch):
    import app.main as main_module
    monkeypatch.setattr(main_module.settings, 'replica_env', 'production')
    monkeypatch.setattr(main_module.settings, 'replica_allowed_ws_origins', 'https://app.replica.example')
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    with pytest.raises(Exception):
        with client.websocket_connect(f'/ws/live/{call_id}') as ws:  # no Origin header at all
            ws.receive_text()


def test_ws_accepts_allowlisted_origin_in_production(client, monkeypatch):
    import app.main as main_module
    monkeypatch.setattr(main_module.settings, 'replica_env', 'production')
    monkeypatch.setattr(main_module.settings, 'replica_allowed_ws_origins', 'https://app.replica.example')
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    token = login(client, 'haydar@replica-pilot.example')
    with client.websocket_connect(f'/ws/live/{call_id}', headers={'origin': 'https://app.replica.example'}) as ws:
        ws.send_text(json.dumps({'type': 'auth', 'token': token}))
        # closing cleanly (no exception) proves the origin check passed and auth succeeded


def test_ws_local_env_allows_missing_origin(client):
    """Default test env is 'local' — the Origin check must not break existing
    local/dev/test usage that never sets an Origin header."""
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    token = login(client, 'haydar@replica-pilot.example')
    with client.websocket_connect(f'/ws/live/{call_id}') as ws:
        ws.send_text(json.dumps({'type': 'auth', 'token': token}))


# --- Clock-sync ping/pong (Fix-Sprint, ADR-051) --------------------------------------

def test_ws_ping_gets_a_pong_with_server_timestamps(client):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    token = login(client, 'haydar@replica-pilot.example')
    with client.websocket_connect(f'/ws/live/{call_id}') as ws:
        ws.send_text(json.dumps({'type': 'auth', 'token': token}))
        ws.send_text(json.dumps({'type': 'ping', 'seq': 1, 't1_client_send_ms': 12345.0}))
        pong = ws.receive_json()
        assert pong['type'] == 'pong'
        assert pong['seq'] == 1
        assert pong['t1_client_send_ms'] == 12345.0
        assert isinstance(pong['t2_server_recv_ms'], (int, float))
        assert isinstance(pong['t3_server_send_ms'], (int, float))
        assert pong['t3_server_send_ms'] >= pong['t2_server_recv_ms']


# --- Render-ACK --------------------------------------------------------------------

def _ack_payload(**overrides):
    now_ms = time.time() * 1000
    payload = {
        'trace_id': None, 'call_id': None,
        'client_received_epoch_ms': now_ms,
        'client_rendered_epoch_ms': now_ms + 50,
        'client_received_perf_ms': 120.0,
        'client_rendered_perf_ms': 137.0,
    }
    payload.update(overrides)
    return payload


def test_render_ack_updates_the_matching_trace_and_computes_wallclock_rsl_estimate(client, db_session):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    trace_id = 'test-trace-abc'
    trace = TurnLatencyTrace(
        company_id=1, call_id=call_id, turn_id='t1', trace_id=trace_id, speaker='prospect',
        asr_provider='simulated', is_synthetic=True, t_turn_end_detected_at=datetime.utcnow(),
        t_turn_end_detected_monotonic=time.monotonic(),
    )
    db_session.add(trace)
    suggestion = Suggestion(
        company_id=1, call_id=call_id, trace_id=trace_id, prospect_text='x', suggestion='y',
        strategy='discover_buying_criteria', latency_ms=1.0,
    )
    db_session.add(suggestion)
    db_session.commit()
    db_session.refresh(suggestion)

    r = client.post(
        f'/api/suggestions/{suggestion.id}/render-ack', headers=headers,
        json=_ack_payload(trace_id=trace_id, call_id=call_id),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['wallclock_rsl_estimate_ms'] is not None
    assert body['wallclock_rsl_estimate_ms'] >= 0
    assert body['server_render_ack_latency_ms'] is not None
    assert body['server_render_ack_latency_ms'] >= 0
    assert body['client_render_latency_ms'] == 17.0
    assert body['is_synthetic'] is True
    assert body['asr_provider'] == 'simulated'

    db_session.refresh(trace)
    assert trace.t_browser_received_at is not None
    assert trace.t_ui_rendered_at is not None
    assert trace.t_render_ack_received_at is not None
    assert trace.wallclock_rsl_estimate_ms == body['wallclock_rsl_estimate_ms']
    assert trace.server_render_ack_latency_ms == body['server_render_ack_latency_ms']
    assert trace.client_render_latency_ms == 17.0


def test_render_ack_without_turn_end_monotonic_leaves_server_upper_bound_null(client, db_session):
    """A trace row that never captured t_turn_end_detected_monotonic (e.g. an
    older row from before ADR-051, or one built by hand like this test) must not
    get a fabricated server_render_ack_latency_ms — it stays None rather than
    being computed from a missing anchor."""
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    trace_id = 'test-trace-no-monotonic'
    trace = TurnLatencyTrace(
        company_id=1, call_id=call_id, turn_id='t2', trace_id=trace_id, speaker='prospect',
        asr_provider='simulated', is_synthetic=True, t_turn_end_detected_at=datetime.utcnow(),
    )
    db_session.add(trace)
    suggestion = Suggestion(
        company_id=1, call_id=call_id, trace_id=trace_id, prospect_text='x', suggestion='y',
        strategy='discover_buying_criteria', latency_ms=1.0,
    )
    db_session.add(suggestion)
    db_session.commit()
    db_session.refresh(suggestion)

    r = client.post(
        f'/api/suggestions/{suggestion.id}/render-ack', headers=headers,
        json=_ack_payload(trace_id=trace_id, call_id=call_id),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['wallclock_rsl_estimate_ms'] is not None  # still computed, wall-clock only needs t_turn_end_detected_at
    assert body['server_render_ack_latency_ms'] is None


def test_render_ack_is_tenant_scoped(client, other_tenant):
    headers_a = auth_headers(client, 'haydar@replica-pilot.example')
    call_id_b = other_tenant['call_id']
    suggestion = Suggestion(
        company_id=other_tenant['company_id'], call_id=call_id_b, trace_id='rival-trace',
        prospect_text='x', suggestion='y', strategy='discover_buying_criteria', latency_ms=1.0,
    )
    db = SessionLocal()
    try:
        db.add(suggestion)
        db.commit()
        db.refresh(suggestion)
        suggestion_id = suggestion.id
    finally:
        db.close()

    r = client.post(f'/api/suggestions/{suggestion_id}/render-ack', headers=headers_a, json=_ack_payload())
    assert r.status_code == 404


def test_render_ack_without_a_matching_trace_is_a_safe_no_op(client):
    headers = auth_headers(client, 'haydar@replica-pilot.example')
    call_id = _create_call(client, headers)
    suggestion = Suggestion(
        company_id=1, call_id=call_id, trace_id='no-such-trace-anywhere',
        prospect_text='x', suggestion='y', strategy='discover_buying_criteria', latency_ms=1.0,
    )
    db = SessionLocal()
    try:
        db.add(suggestion)
        db.commit()
        db.refresh(suggestion)
        suggestion_id = suggestion.id
    finally:
        db.close()

    r = client.post(f'/api/suggestions/{suggestion_id}/render-ack', headers=headers, json=_ack_payload())
    assert r.status_code == 200, r.text
    assert r.json()['wallclock_rsl_estimate_ms'] is None
