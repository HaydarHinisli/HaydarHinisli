"""Event/Turn Identity & Deduplication (Provider-Ready Gate).

Prepares the architecture for streaming ASR: webhook retries, duplicate final
transcripts, reconnects, interim/final ASR revisions, and provider retries must never
cause the same real prospect/seller turn to trigger a second state transition or a
second Copilot suggestion. `claim_turn()` is the single choke point enforcing that,
via the DB's unique constraint on `(call_id, action, turn_id)` — the same race-safe
pattern as webhook idempotency (app/webhooks/idempotency.py), reused here because it
is the same problem: "have I already claimed this token."

Terminology (docs/DECISIONS.md ADR-034): this is **idempotent, effectively-once**
processing, precisely — not "exactly-once delivery" (a provider may call REPLICA more
than once for the same real turn; that is expected and unavoidable over HTTP/webhooks)
but the persisted *effect* is applied exactly once per successful attempt, and a
failed attempt leaves zero trace. That guarantee holds only because `claim_turn()` is
called inside the SAME DB transaction/Session as every other side effect the turn
produces (ConversationState update, ConversationStateEvent, Suggestion — see
app/main.py's `add_turn()`/`copilot()`) with exactly one commit at the end: a crash or
exception before that commit rolls back the claim along with everything else (nothing
is left half-done), so a retry reprocesses the turn from scratch rather than being
wrongly treated as already-handled. Only after a full commit does a repeat delivery
get treated as a duplicate. See ADR-034 for the full transaction-boundary writeup.

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


def _find(db: Session, call_id: int, action: str, turn_id: str) -> ProcessedTurnEvent | None:
    return db.scalar(
        select(ProcessedTurnEvent).where(
            ProcessedTurnEvent.call_id == call_id,
            ProcessedTurnEvent.action == action,
            ProcessedTurnEvent.turn_id == turn_id,
        )
    )


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

    Concurrency (ADR-034): two callers racing to claim the same (call_id, action,
    turn_id) from *different* DB sessions can both pass the initial `select()` check
    (neither sees the other's uncommitted insert) and both attempt the INSERT; the
    loser hits the unique constraint. That loss is handled inside a SAVEPOINT
    (`db.begin_nested()`), not a full `db.rollback()` — a full rollback would discard
    *every* pending change already queued in the loser's own transaction this request
    cycle (e.g. an audit-log entry from an earlier `can_process()` call in the same
    request), which would silently lose unrelated, already-decided work. The SAVEPOINT
    undoes only this claim attempt; everything else the caller already added to `db`
    survives to be committed normally.
    """
    existing = _find(db, call_id, action, turn_id)
    if existing is not None:
        return False, existing

    row = ProcessedTurnEvent(
        company_id=company_id, call_id=call_id, action=action, turn_id=turn_id,
        utterance_id=utterance_id, stream_id=stream_id, provider_event_id=provider_event_id,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
        return True, row
    except IntegrityError:
        # Lost a race against a concurrent identical claim — the other session owns
        # it. Only this claim attempt is undone (SAVEPOINT rollback); the rest of this
        # request's pending transaction is untouched. Fetch and treat as a duplicate.
        existing = _find(db, call_id, action, turn_id)
        return False, existing


def record_result(row: ProcessedTurnEvent, result_ref: dict) -> None:
    row.result_ref = result_ref
