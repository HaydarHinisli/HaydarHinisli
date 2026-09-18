"""Admin-facing compliance write paths: tenant feature flags, compliance review
signoffs, and network-learning opt-in/withdraw. Every mutation here is audited with
enough detail to reconstruct who changed what, when, and why (see docs item: Audit Log).
"""
from __future__ import annotations
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Company, ComplianceReviewSignoff, ConsentEvent, TenantFeatureFlag
from .audit import log_audit
from .policy_engine import can_process


def set_feature_flag(
    db: Session, *, company_id: int, feature_key: str, enabled: bool,
    jurisdiction: str | None = None, campaign_type: str | None = None,
    actor: str = 'admin', reason: str = '',
) -> TenantFeatureFlag:
    row = db.scalars(
        select(TenantFeatureFlag).where(
            TenantFeatureFlag.company_id == company_id,
            TenantFeatureFlag.feature_key == feature_key,
            TenantFeatureFlag.jurisdiction == jurisdiction,
            TenantFeatureFlag.campaign_type == campaign_type,
        )
    ).first()
    previous_enabled = row.enabled if row else None
    if row is None:
        row = TenantFeatureFlag(
            company_id=company_id, feature_key=feature_key, jurisdiction=jurisdiction,
            campaign_type=campaign_type, enabled=enabled, updated_by=actor, reason=reason,
        )
        db.add(row)
    else:
        row.enabled = enabled
        row.updated_by = actor
        row.reason = reason
        row.updated_at = datetime.utcnow()
    log_audit(
        db, company_id, actor=actor, action='feature_flag.updated',
        entity_type='tenant_feature_flag', entity_id=feature_key,
        payload={
            'feature_key': feature_key, 'jurisdiction': jurisdiction, 'campaign_type': campaign_type,
            'previous_enabled': previous_enabled, 'new_enabled': enabled, 'reason': reason,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def record_review_signoff(
    db: Session, *, company_id: int, action: str, jurisdiction: str,
    acknowledged_by: str, reason: str = '', reference: str = '',
) -> ComplianceReviewSignoff:
    jurisdiction = jurisdiction.upper().strip()
    previous = can_process(db, action, tenant_id=company_id, country_code=jurisdiction, log=False)
    row = ComplianceReviewSignoff(
        company_id=company_id, action=action, jurisdiction=jurisdiction,
        acknowledged_by=acknowledged_by, reason=reason, reference=reference,
    )
    db.add(row)
    db.flush()
    new = can_process(db, action, tenant_id=company_id, country_code=jurisdiction, log=False)
    log_audit(
        db, company_id, actor=acknowledged_by, action='policy.override',
        entity_type='compliance_review_signoff', entity_id=action,
        payload={
            'action': action, 'jurisdiction': jurisdiction, 'reason': reason, 'reference': reference,
            'previous_decision': previous.as_dict(), 'new_decision': new.as_dict(),
        },
    )
    db.commit()
    db.refresh(row)
    return row


def set_network_learning_opt_in(
    db: Session, *, company_id: int, opt_in: bool, actor: str = 'admin',
    reason: str = '', evidence_ref: str = '',
) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise ValueError('Company not found')
    previous = company.network_learning_opt_in
    company.network_learning_opt_in = opt_in
    db.add(ConsentEvent(
        company_id=company_id, call_id=None,
        consent_type='cross_customer_network_learning',
        purpose=reason or 'Network Intelligence contribution',
        status='granted' if opt_in else 'withdrawn',
        collection_method='api', evidence_ref=evidence_ref,
        withdrawn_at=datetime.utcnow() if not opt_in else None,
    ))
    log_audit(
        db, company_id, actor=actor,
        action='network_learning.opt_in' if opt_in else 'network_learning.withdraw',
        entity_type='company', entity_id=str(company_id),
        payload={'previous': previous, 'new': opt_in, 'reason': reason},
    )
    db.commit()
    db.refresh(company)
    return company
