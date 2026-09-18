"""Webhook delivery idempotency: a provider retry of the same event must not be
reprocessed (see docs/DECISIONS.md ADR-029). Uses the DB's unique constraint as the
race-safe claim mechanism — two concurrent deliveries of the same event can only ever
have one winner, regardless of request timing.
"""
from __future__ import annotations
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import WebhookDelivery


def claim_webhook_delivery(
    db: Session, *, provider: str, event_type: str, external_id: str,
    company_id: int | None = None, payload_summary: dict | None = None,
) -> bool:
    """Returns True if this is the first delivery of this event (caller should
    process it), False if it's a retry/duplicate (caller should skip processing and
    still return a 2xx so the provider stops retrying)."""
    row = WebhookDelivery(
        provider=provider, event_type=event_type, external_id=external_id,
        company_id=company_id, payload_summary=payload_summary or {},
    )
    db.add(row)
    try:
        db.flush()
        return True
    except IntegrityError:
        db.rollback()
        return False
