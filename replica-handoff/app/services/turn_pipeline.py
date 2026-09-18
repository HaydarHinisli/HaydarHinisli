"""The central final-turn processing path (Sprint 2, docs/DECISIONS.md ADR-040).

The Provider-Ready Gate's ADR-032 flagged explicitly that today's HTTP API splits a
single real turn across two independently-claimed actions (`POST
/api/calls/{id}/turns` = 'transcribe', `POST /api/copilot/suggest` = 'live_assist')
and predicted that "once Sprint 2 has one real 'final turn' event, it should call
apply_turn() exactly once through a single processing path." `process_final_turn()`
is that path — the ONLY function the new Twilio Media Streams pipeline
(app/streaming/pipeline.py) calls to turn a detected final utterance into persisted
state. It does NOT touch or change the existing HTTP endpoints (`add_turn()`/
`copilot()` in app/main.py keep their existing two-action behavior byte for byte —
verified by the full existing test suite) — this is a new, additional path for the
new ingestion route, not a replacement for the old one, since changing the HTTP
contract was out of scope for this sprint.

One call = one DB transaction = one commit, exactly like the HTTP endpoints (ADR-034):
policy check, `ProcessedTurnEvent` claim (action `'final_turn'`, a distinct action
value from the HTTP paths' so their dedup ledgers can never collide), the `Turn`
transcript row, the ConversationState update + `ConversationStateEvent`, and (for a
prospect turn) the `Suggestion` row all share one session with one commit at the end
— a crash before that commit rolls everything back together (see
tests/test_turn_processing_atomicity.py's pattern, reused for this path in
tests/test_streaming_pipeline.py).
"""
from __future__ import annotations
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Call, Suggestion, Turn
from .conversation_state import apply_turn
from .conversation_state_store import (
    apply_state_to_row, conversation_state_dict, load_or_create_conversation_state_row, record_state_event,
    state_from_row,
)
from .copilot import suggest_with_state
from .language_sync import analyze_language
from .latency_trace import LatencyTrace
from .turn_identity import claim_turn, record_result, synthesize_turn_id
from ..compliance.policy_engine import Decision, can_process

ACTION = 'final_turn'


def process_final_turn(
    db: Session, call: Call, speaker: str, text: str, *, company_id: int,
    turn_id: str | None = None, utterance_id: str | None = None, stream_id: str | None = None,
    provider_event_id: str | None = None, reaction_snapshot: dict | None = None, trace_id: str | None = None,
    started_ms: int = 0, ended_ms: int = 0, latency_trace: LatencyTrace | None = None,
) -> dict:
    """`speaker` is 'prospect' or 'seller'. Returns a result dict; check `denied`
    first (nothing was processed at all), then `duplicate` (already processed by an
    earlier delivery of the same `turn_id` — cached fields are returned instead of
    reprocessing). `latency_trace`, when given (the streaming pipeline always passes
    one; direct/manual callers may omit it), gets its `salesbrain_started`/
    `salesbrain_finished`/`suggestion_persisted` stages marked at the precise points
    below — see docs/DECISIONS.md ADR-041."""
    decision = can_process(
        db, 'transcribe', tenant_id=call.company_id, call_id=call.id, country_code=call.jurisdiction_country,
        prospect_type=call.prospect_type, campaign_type=call.campaign_type, speaker_mode=call.speaker_mode,
    )
    if decision.result != Decision.ALLOWED:
        db.commit()
        return {'denied': True, 'blocked_action': 'transcribe', 'policy_decision': decision.as_dict()}

    existing_turn_count = db.scalar(select(func.count()).select_from(Turn).where(Turn.call_id == call.id)) or 0
    resolved_turn_id = turn_id or synthesize_turn_id(call.id, ACTION, existing_turn_count)
    claimed, claim_row = claim_turn(
        db, company_id=company_id, call_id=call.id, action=ACTION, turn_id=resolved_turn_id,
        utterance_id=utterance_id, stream_id=stream_id, provider_event_id=provider_event_id,
    )
    if not claimed:
        db.commit()
        return {
            **claim_row.result_ref, 'duplicate': True, 'denied': False,
            'turn_id': resolved_turn_id, 'policy_decision': decision.as_dict(),
        }

    style = analyze_language(text) if speaker == 'prospect' else {}
    turn_row = Turn(
        call_id=call.id, speaker=speaker, text=text, started_ms=started_ms, ended_ms=ended_ms,
        style_snapshot=style, lexical_complexity=style.get('complexity_score') if style else None,
    )
    db.add(turn_row)
    db.flush()

    state_row = load_or_create_conversation_state_row(db, call)
    pre_state = state_from_row(state_row)

    suggestion_id = None
    live_assist_decision = None
    if speaker == 'prospect':
        live_assist_decision = can_process(
            db, 'live_assist', tenant_id=call.company_id, call_id=call.id, country_code=call.jurisdiction_country,
            prospect_type=call.prospect_type, campaign_type=call.campaign_type, speaker_mode=call.speaker_mode,
        )
        if live_assist_decision.result == Decision.ALLOWED:
            if latency_trace:
                latency_trace.mark('salesbrain_started')
            new_state, result, transition = suggest_with_state(pre_state, text, reaction_snapshot)
            if latency_trace:
                latency_trace.mark('salesbrain_finished')
            apply_state_to_row(state_row, new_state)
            record_state_event(db, call, 'prospect', transition, turn_index=new_state.turn_index)
            suggestion_row = Suggestion(
                company_id=company_id, call_id=call.id, trace_id=trace_id, prospect_text=text,
                suggestion=result['suggestion'], strategy=result['strategy'], reason=result['reason'],
                do_not=result['do_not'], confidence=result['confidence'], latency_ms=result['latency_ms'],
                language_policy=result['language_policy'], reaction_snapshot=result['reaction_snapshot'],
            )
            db.add(suggestion_row)
            db.flush()
            suggestion_id = suggestion_row.id
        # else: transcription is allowed but live-assist isn't for this call right
        # now — the transcript above still persists (that's a separately gated
        # action, ADR-031/032), but phase does not advance and no suggestion is
        # generated. Mirrors the HTTP API's two independently-gated actions,
        # collapsed into one call rather than one blanket permission.
    else:
        if latency_trace:
            latency_trace.mark('salesbrain_started')
        new_state, transition, _ = apply_turn(pre_state, 'seller', text)
        if latency_trace:
            latency_trace.mark('salesbrain_finished')
        apply_state_to_row(state_row, new_state)
        record_state_event(db, call, 'seller', transition, turn_index=new_state.turn_index)

    result_ref = {'turn_row_id': turn_row.id, 'suggestion_id': suggestion_id}
    record_result(claim_row, result_ref)
    db.commit()
    if latency_trace:
        latency_trace.mark('suggestion_persisted')
    db.refresh(turn_row)
    out = {
        **result_ref, 'duplicate': False, 'denied': False, 'turn_id': resolved_turn_id,
        'policy_decision': decision.as_dict(), 'conversation_state': conversation_state_dict(state_row),
    }
    if live_assist_decision is not None:
        out['live_assist_policy_decision'] = live_assist_decision.as_dict()
    return out
