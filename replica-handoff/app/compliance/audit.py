"""Thin, single-choke-point audit logging helper.

Every compliance-relevant write in this package goes through log_audit() so there
is exactly one place to later add write-once/hash-chaining guarantees (Sprint 1+).
This does not commit; callers commit as part of their own transaction, matching the
existing pattern in app/main.py.
"""
from __future__ import annotations
from ..models import AuditEvent


def log_audit(db, company_id: int, *, actor: str, action: str, entity_type: str = '', entity_id: str = '', payload: dict | None = None) -> AuditEvent:
    event = AuditEvent(
        company_id=company_id,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        payload=payload or {},
    )
    db.add(event)
    return event
