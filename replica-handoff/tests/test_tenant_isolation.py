"""Cross-tenant isolation over HTTP: a second tenant is created directly against the
app's own DB session (there is no public "create tenant" endpoint in Sprint 1), then
we prove tenant B can never read, modify, or ID-guess into tenant A's data.
"""
from datetime import datetime, timedelta

import pytest
from conftest import DEMO_PASSWORD, auth_headers

from app.auth.security import hash_password
from app.db import SessionLocal
from app.models import Call, Company, Seller, User


def _make_second_tenant():
    db = SessionLocal()
    try:
        company = Company(name='Rival Corp', country_code='DE', network_learning_opt_in=False)
        db.add(company)
        db.flush()
        now = datetime.utcnow()
        seller = Seller(company_id=company.id, name='Riva', hired_at=now - timedelta(days=10), product_started_at=now - timedelta(days=10))
        db.add(seller)
        db.flush()
        user = User(company_id=company.id, email='riva@rival.example', password_hash=hash_password(DEMO_PASSWORD), role='seller')
        db.add(user)
        call = Call(company_id=company.id, seller_id=seller.id, prospect_company='Rival Prospect', jurisdiction_country='DE')
        db.add(call)
        db.flush()
        db.commit()
        return {'company_id': company.id, 'seller_id': seller.id, 'call_id': call.id}
    finally:
        db.close()


@pytest.fixture(scope='module')
def other(client):
    return _make_second_tenant()


def test_tenant_b_cannot_read_tenant_a_call_by_id(client, other):
    headers_a = auth_headers(client, 'haydar@replica-pilot.example')  # tenant A (REPLICA Pilot GmbH)

    # tenant A's user probing tenant B's call id must get 404, not 403 or 200 —
    # existence must not be distinguishable from ownership.
    r = client.get(f"/api/calls/{other['call_id']}/review", headers=headers_a)
    assert r.status_code == 404

    r = client.post(f"/api/calls/{other['call_id']}/turns", headers=headers_a, json={'speaker': 'prospect', 'text': 'hallo'})
    assert r.status_code == 404

    r = client.post(f"/api/calls/{other['call_id']}/consent", headers=headers_a, json={'state': 'granted'})
    assert r.status_code == 404


def test_seller_id_from_other_tenant_is_rejected(client, other):
    headers_a = auth_headers(client, 'haydar@replica-pilot.example')
    r = client.post('/api/calls', headers=headers_a, json={'seller_id': other['seller_id']})
    assert r.status_code == 404


def test_suggestion_feedback_cannot_cross_tenant(client, other):
    headers_a = auth_headers(client, 'haydar@replica-pilot.example')
    created = client.post('/api/copilot/suggest', headers=headers_a, json={'utterance': 'Ich habe keine Zeit.'})
    assert created.status_code == 200
    suggestion_id = created.json()['suggestion_id']

    headers_b = auth_headers(client, 'riva@rival.example')
    r = client.post(f'/api/suggestions/{suggestion_id}/feedback', headers=headers_b, json={'rating': 'bad'})
    assert r.status_code == 404


def test_non_system_admin_cannot_act_on_a_different_company_id(client, other):
    headers_a = auth_headers(client, 'admin@replica-pilot.example')  # tenant_admin of tenant A
    r = client.post(
        '/api/admin/feature-flags', headers=headers_a,
        json={'feature_key': 'autonomous_call', 'enabled': True, 'company_id': other['company_id']},
    )
    assert r.status_code == 403


def test_system_admin_must_specify_company_id_explicitly(client):
    headers_sys = auth_headers(client, 'sysadmin@replica.example')
    r = client.get('/api/admin/feature-flags', headers=headers_sys)
    assert r.status_code == 400


def test_system_admin_can_act_cross_tenant_when_specified(client, other):
    headers_sys = auth_headers(client, 'sysadmin@replica.example')
    r = client.get('/api/admin/feature-flags', headers=headers_sys, params={'company_id': other['company_id']})
    assert r.status_code == 200


def test_compliance_admin_plus_rbac_combined(client):
    # compliance_admin may record a signoff (compliance action) but may not touch
    # seller-only live-call endpoints — RBAC and the compliance role are enforced together.
    headers_compliance = auth_headers(client, 'compliance@replica-pilot.example')
    r = client.post(
        '/api/admin/compliance-signoffs', headers=headers_compliance,
        json={'action': 'employee_analytics', 'jurisdiction': 'DE', 'reason': 'periodic re-ack'},
    )
    assert r.status_code == 200

    r = client.post('/api/calls', headers=headers_compliance, json={'seller_id': 1})
    assert r.status_code == 403
