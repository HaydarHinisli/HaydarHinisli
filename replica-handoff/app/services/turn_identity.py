"""Event/Turn Identity & Deduplication (Provider-Ready Gate).

Prepares the architecture for streaming ASR: webhook retries, duplicate final
transcripts, reconnects, interim/final ASR revisions, and provider retries must never
cause the same real prospect/seller turn to trigger a second state transition or a
second Copilot suggestion. `claim_turn()` is the single choke point that enforces
"exactly once per (call, action, turn_id)" via the DB's unique constraint — the same
race-safe pattern as webhook idempotency (app/webhooks/idempotency.py), reused here
because it is the same problem: "have I already claimed this token."

Identity fields (see docs/DECISIONS.md ADR-031):
- `turn_id`: REPLICA's own idempotency key for this real turn. Callers with a real
  ASR pipeline should derive it from something provider-stable (e.g. a final
  transcript's own event id); callers without one yet (today's manual/demo flows) get
  a synthesized default from (call_id, action, next turn_index) so nothing breaks.
- `utterance_id`: ties together multiple ASR revisions (interim + final) of the SAME
  spoken utterance — carried through for correlation, not itself the uniqueness key,
  since a provider may reuse/omit it inconsistently across revisions.
- `stream_id` / `provider_event_id`: provider-specific correlation, carried through
  for debugging/tracing, not the uniqueness key either.
"""
from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import ProcessedTurnEvent


def synthesize_turn_id(call_id: int, action: str, turn_index: int) -> str:
    """Default turn_id for callers that don't yet have a real provider-derived one
    (today's manual/demo flows). Real streaming ASR callers should pass their own."""
    return f'{call_id}:{action}:{turn_index}'


def claim_turn(
    db: Session, *, company_id: int, call_id: int, action: str, turn_id: str,
    utterance_id: str | None = None, stream_id: str | None = None,
    provider_event_id: str | None = None,
) -> tuple[bool, ProcessedTurnEvent]:
    """Returns (claimed, row). claimed=True means this is the first time turn_id has
    been seen for (call_id, action) — the caller should process it and then call
    record_result() to store what it produced. claimed=False means it's a duplicate;
    `row` is the ORIGINAL claim, whose `result_ref` holds the cached result the caller
    should return instead of reprocessing.
    """
    existing = db.scalar(
        select(ProcessedTurnEvent).where(
            ProcessedTurnEvent.call_id == call_id,
            ProcessedTurnEvent.action == action,
            ProcessedTurnEvent.turn_id == turn_id,
        )
    )
    if existing is not None:
        return False, existing

    row = ProcessedTurnEvent(
        company_id=company_id, call_id=call_id, action=action, turn_id=turn_id,
        utterance_id=utterance_id, stream_id=stream_id, provider_event_id=provider_event_id,
    )
    db.add(row)
    try:
        db.flush()
        return True, row
    except IntegrityError:
        # Lost a race against a concurrent identical claim — the other request owns
        # it; fetch and treat as a duplicate rather than erroring.
        db.rollback()
        existing = db.scalar(
            select(ProcessedTurnEvent).where(
                ProcessedTurnEvent.call_id == call_id,
                ProcessedTurnEvent.action == action,
                ProcessedTurnEvent.turn_id == turn_id,
            )
        )
        return False, existing


def record_result(row: ProcessedTurnEvent, result_ref: dict) -> None:
    row.result_ref = result_ref
