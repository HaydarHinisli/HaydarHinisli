"""DB-aware persistence helpers for the call-bound ConversationState row and its
append-only ConversationStateEvent history (Sprint 1.5 / Provider-Ready Gate).

Moved out of app/main.py in Sprint 2 (pure relocation, no behavior change — see
docs/DECISIONS.md ADR-040) so both the HTTP endpoints (POST /api/copilot/suggest,
POST /api/calls/{id}/turns) and the new Twilio Media Streams pipeline
(app/services/turn_pipeline.py, app/streaming/pipeline.py) share the exact same
state-loading/persisting logic instead of each re-implementing it — the split that
made this necessary is documented in ADR-032's Sprint 2 forward-compat note.
"""
from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Call, ConversationStateEvent
from ..models import ConversationState as ConversationStateRow
from .conversation_state import ConversationState


def load_or_create_conversation_state_row(db: Session, call: Call) -> ConversationStateRow:
    """Race-safe get-or-create (ADR-034): two concurrent first turns for the same
    call can both see no existing row and both attempt to create one — the loser
    hits `ConversationState.call_id`'s unique index. That is handled inside a
    SAVEPOINT (`db.begin_nested()`), the same pattern as claim_turn()/
    claim_webhook_delivery(), so only this insert attempt is undone rather than the
    request's whole pending transaction."""
    row = db.scalar(select(ConversationStateRow).where(ConversationStateRow.call_id == call.id))
    if row is not None:
        return row
    row = ConversationStateRow(call_id=call.id)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
        return row
    except IntegrityError:
        return db.scalar(select(ConversationStateRow).where(ConversationStateRow.call_id == call.id))


def state_from_row(row: ConversationStateRow) -> ConversationState:
    return ConversationState(
        call_id=row.call_id, current_phase=row.current_phase, previous_phase=row.previous_phase,
        turn_index=row.turn_index, smalltalk_turns=row.smalltalk_turns,
        business_transition_started=row.business_transition_started, opening_completed=row.opening_completed,
        discovery_started=row.discovery_started, pitch_delivered=row.pitch_delivered,
        price_discussed=row.price_discussed, active_objection=row.active_objection,
        resolved_objections=list(row.resolved_objections or []),
        last_seller_action=row.last_seller_action, last_prospect_event=row.last_prospect_event,
    )


def apply_state_to_row(row: ConversationStateRow, state: ConversationState) -> None:
    row.current_phase = state.current_phase
    row.previous_phase = state.previous_phase
    row.turn_index = state.turn_index
    row.smalltalk_turns = state.smalltalk_turns
    row.business_transition_started = state.business_transition_started
    row.opening_completed = state.opening_completed
    row.discovery_started = state.discovery_started
    row.pitch_delivered = state.pitch_delivered
    row.price_discussed = state.price_discussed
    row.active_objection = state.active_objection
    row.resolved_objections = state.resolved_objections
    row.last_seller_action = state.last_seller_action
    row.last_prospect_event = state.last_prospect_event


def record_state_event(db: Session, call: Call, speaker: str, transition: dict, turn_index: int) -> None:
    """Provider-Ready Gate (ADR-030): append-only history row alongside the fast
    ConversationState snapshot. A single INSERT next to the state-row UPDATE already
    happening in the same request/transaction — this does not add a query or slow
    the pure state machine in app/services/conversation_state.py."""
    db.add(ConversationStateEvent(
        company_id=call.company_id, call_id=call.id, turn_index=turn_index, speaker=speaker,
        from_phase=transition.get('from_phase'), to_phase=transition.get('to_phase'),
        event_type=transition.get('event_type', 'unknown'), objection_type=transition.get('objection_type'),
        sales_action=transition.get('sales_action'), trigger=transition.get('trigger'),
    ))


def conversation_state_dict(row: ConversationStateRow) -> dict:
    return {
        'call_id': row.call_id,
        'current_phase': row.current_phase,
        'previous_phase': row.previous_phase,
        'turn_index': row.turn_index,
        'smalltalk_turns': row.smalltalk_turns,
        'business_transition_started': row.business_transition_started,
        'opening_completed': row.opening_completed,
        'discovery_started': row.discovery_started,
        'pitch_delivered': row.pitch_delivered,
        'price_discussed': row.price_discussed,
        'active_objection': row.active_objection,
        'resolved_objections': row.resolved_objections,
        'last_seller_action': row.last_seller_action,
        'last_prospect_event': row.last_prospect_event,
        'updated_at': row.updated_at.isoformat(),
    }
