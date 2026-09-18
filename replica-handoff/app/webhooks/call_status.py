"""Ordering-aware application of provider call-status events (Provider-Ready Gate
hardening, see docs/DECISIONS.md ADR-035).

Twilio's webhook delivery is at-least-once and NOT guaranteed in order: a retry, a
network re-route, or simple scheduling jitter can deliver an older event after a
newer one already arrived and was applied. A materialized call state must never
regress because of that — once `completed` has been applied, a late `in-progress`
must not "un-finish" the call.

This module is pure/DB-light by design (mirrors app/services/conversation_state.py's
split): `is_newer_event()` and `parse_sequence_number()` are pure functions, unit
tested in isolation; `get_or_create_provider_status()` is the one DB-touching helper,
using the same insert-then-savepoint claim pattern as claim_turn()/
claim_webhook_delivery() for the (rare) race where two deliveries for a call neither
of us has seen before arrive concurrently.
"""
from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import CallProviderStatus

# Twilio's own documented call-status progression. Every status in the same set is
# considered equally "final" for ordering purposes — once any of them has been
# applied, nothing else can move the call backward, regardless of which specific
# terminal status arrives next (first terminal status wins).
TERMINAL_CALL_STATUSES = frozenset({'completed', 'busy', 'failed', 'no-answer', 'canceled'})

# Coarse fallback ranking, used ONLY when neither the incoming event nor the
# previously-applied one carries a SequenceNumber. Deliberately coarse: it exists to
# stop a stale non-terminal event from re-opening an already-terminal call, not to
# finely order every intermediate status against every other.
_STATUS_RANK = {
    'queued': 0, 'initiated': 0,
    'ringing': 1,
    'in-progress': 2, 'answered': 2,
    'completed': 3, 'busy': 3, 'failed': 3, 'no-answer': 3, 'canceled': 3,
}


def parse_sequence_number(raw: str | None) -> int | None:
    """Twilio's `SequenceNumber` form field, when present, is the authoritative
    provider-assigned order for a call's status events. Returns None if absent or
    not a valid integer (some status-callback configurations don't include it)."""
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def is_newer_event(
    *, incoming_status: str, incoming_sequence: int | None,
    last_status: str | None, last_sequence: int | None,
) -> bool:
    """True if the incoming event should be APPLIED to the materialized call state;
    False if it is stale/out-of-order and must be recorded (the caller still has a
    permanent WebhookDelivery row for it) but not applied.

    Ordering priority:
    1. No prior event at all for this call -> always apply (nothing to regress).
    2. Both events carry a SequenceNumber -> compare numerically; this is Twilio's
       own authoritative order and overrides everything else, including the status
       values themselves (a provider-confirmed reordering is trusted as-is).
    3. Otherwise, a terminal status is a one-way door: once applied, no further event
       (of any kind) is ever considered newer.
    4. Otherwise, fall back to the coarse status-progression rank.
    """
    if last_status is None:
        return True
    if incoming_sequence is not None and last_sequence is not None:
        return incoming_sequence > last_sequence
    if last_status in TERMINAL_CALL_STATUSES:
        return False
    return _STATUS_RANK.get(incoming_status, 0) >= _STATUS_RANK.get(last_status, 0)


def get_or_create_provider_status(
    db: Session, *, provider: str, external_call_id: str, call_id: int | None,
) -> CallProviderStatus:
    """Fetches (or creates, race-safely) the one CallProviderStatus row for this
    provider call. A freshly created row has `last_status=None`, so the very first
    event processed against it is always treated as newer (see is_newer_event())."""
    row = db.scalar(
        select(CallProviderStatus).where(
            CallProviderStatus.provider == provider, CallProviderStatus.external_call_id == external_call_id,
        )
    )
    if row is not None:
        if call_id is not None and row.call_id is None:
            row.call_id = call_id  # correlate once a matching Call becomes known
        return row

    row = CallProviderStatus(provider=provider, external_call_id=external_call_id, call_id=call_id)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
        return row
    except IntegrityError:
        # Concurrent first-sighting of the same provider call — same race-safe
        # savepoint pattern as claim_turn()/claim_webhook_delivery().
        return db.scalar(
            select(CallProviderStatus).where(
                CallProviderStatus.provider == provider, CallProviderStatus.external_call_id == external_call_id,
            )
        )
