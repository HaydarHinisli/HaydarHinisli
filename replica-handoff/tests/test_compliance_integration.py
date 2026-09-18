"""DB-backed compliance tests: tenant isolation and policy-override audit trail.

Uses a fresh in-memory SQLite database per test, independent of the app's
configured DATABASE_URL, so these tests never touch a real/dev database.
"""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import AuditEvent, Company
from app.compliance.admin import record_review_signoff, set_feature_flag, set_network_learning_opt_in
from app.compliance.policy_engine import Decision, can_process


@pytest.fixture()
def session():
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


def _make_company(db, name='Tenant', country='DE'):
    company = Company(name=name, country_code=country, network_learning_opt_in=False)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def test_tenant_isolation_review_signoff_does_not_leak(session):
    tenant_a = _make_company(session, 'Tenant A', 'DE')
    tenant_b = _make_company(session, 'Tenant B', 'DE')
    record_review_signoff(session, company_id=tenant_a.id, action='employee_analytics', jurisdiction='DE', acknowledged_by='admin-a', reason='ack')

    decision_a = can_process(session, 'employee_analytics', tenant_id=tenant_a.id, country_code='DE')
    decision_b = can_process(session, 'employee_analytics', tenant_id=tenant_b.id, country_code='DE')

    assert decision_a.result == Decision.ALLOWED
    assert decision_b.result == Decision.REQUIRES_LEGAL_REVIEW


def test_tenant_isolation_feature_flag_does_not_leak(session):
    tenant_a = _make_company(session, 'Tenant A', 'GB')
    tenant_b = _make_company(session, 'Tenant B', 'GB')
    set_feature_flag(session, company_id=tenant_a.id, feature_key='autonomous_call', enabled=True, jurisdiction='GB')

    decision_a = can_process(session, 'autonomous_call', tenant_id=tenant_a.id, country_code='GB')
    decision_b = can_process(session, 'autonomous_call', tenant_id=tenant_b.id, country_code='GB')

    assert decision_a.result == Decision.ALLOWED
    assert decision_b.result == Decision.DENIED


def test_feature_flag_cannot_override_hard_policy_denial(session):
    company = _make_company(session, 'Tenant DE', 'DE')
    # An admin enabling this flag must have no effect: DE's autonomous_marketing_call
    # is a hard "disabled_by_default" floor, not a review/consent tier.
    set_feature_flag(session, company_id=company.id, feature_key='autonomous_call', enabled=True, jurisdiction='DE')
    decision = can_process(session, 'autonomous_call', tenant_id=company.id, country_code='DE')
    assert decision.result == Decision.DENIED


def test_policy_override_is_audited_with_previous_and_new_decision(session):
    company = _make_company(session, 'Tenant DE', 'DE')
    before = can_process(session, 'employee_analytics', tenant_id=company.id, country_code='DE', log=False)
    assert before.result == Decision.REQUIRES_LEGAL_REVIEW

    record_review_signoff(
        session, company_id=company.id, action='employee_analytics', jurisdiction='DE',
        acknowledged_by='ops@tenant.example', reason='Controls documented and acknowledged.', reference='ticket-123',
    )

    after = can_process(session, 'employee_analytics', tenant_id=company.id, country_code='DE', log=False)
    assert after.result == Decision.ALLOWED

    override_events = session.scalars(
        select(AuditEvent).where(AuditEvent.company_id == company.id, AuditEvent.action == 'policy.override')
    ).all()
    assert len(override_events) == 1
    event = override_events[0]
    assert event.actor == 'ops@tenant.example'
    assert event.payload['previous_decision']['result'] == 'requires_legal_review'
    assert event.payload['new_decision']['result'] == 'allowed'
    assert event.payload['reason'] == 'Controls documented and acknowledged.'
    assert event.payload['reference'] == 'ticket-123'
    assert event.created_at is not None


def test_network_learning_opt_in_flow_is_audited(session):
    company = _make_company(session, 'Tenant', 'DE')
    denied = can_process(session, 'network_learning', tenant_id=company.id, country_code='DE', log=False)
    assert denied.result == Decision.REQUIRES_CONSENT

    set_network_learning_opt_in(session, company_id=company.id, opt_in=True, actor='admin@tenant.example', reason='Board approved pilot participation.')
    allowed = can_process(session, 'network_learning', tenant_id=company.id, country_code='DE', log=False)
    assert allowed.result == Decision.ALLOWED

    opt_in_events = session.scalars(
        select(AuditEvent).where(AuditEvent.company_id == company.id, AuditEvent.action == 'network_learning.opt_in')
    ).all()
    assert len(opt_in_events) == 1
    assert opt_in_events[0].actor == 'admin@tenant.example'

    set_network_learning_opt_in(session, company_id=company.id, opt_in=False, actor='admin@tenant.example', reason='Withdrawn by tenant.')
    withdrawn = can_process(session, 'network_learning', tenant_id=company.id, country_code='DE', log=False)
    assert withdrawn.result == Decision.REQUIRES_CONSENT
