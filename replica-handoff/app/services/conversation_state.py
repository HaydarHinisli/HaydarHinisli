"""Call-bound Conversation State (Sprint 1.5): SalesBrain's phase logic understands
transitions across the whole running call — greeting -> rapport_smalltalk ->
transition -> opening -> discovery — instead of reclassifying each prospect sentence
in isolation (see docs/DECISIONS.md ADR-026).

This module is pure/DB-free by design (like the rest of sales_brain.py) so the state
machine itself is fast to unit-test; app/main.py owns loading/saving the persisted
ConversationState DB row (app/models.py) and converting to/from this dataclass.
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace

from .sales_brain import (
    CLOSING_MARKERS, DIRECT_TO_BUSINESS_MARKERS, GREETING_MARKERS, NEGOTIATION_MARKERS,
    OBJECTION_EVENTS, build_response, classify_sales_event, detect_special_phase, analyze_smalltalk,
)

# The strict front-of-call progression. Once the call has reached a later phase here,
# a superficially "earlier" phase detected from a single new utterance (e.g. an aside
# that merely sounds like smalltalk) must not reset progress — see _resume_phase().
FRONT_PHASE_ORDER = ('greeting', 'rapport_smalltalk', 'transition', 'opening', 'discovery')

# Business-relevant anchors that can appear INSIDE what otherwise reads as smalltalk.
# When the prospect mentions one of these while making a personal/social remark, that
# remark is itself a discovery opportunity and must not be flattened into generic
# rapport handling or forced toward a content-free transition (per the product brief's
# "neuer Standort" / "geschäftliches Problem" example).
BUSINESS_ANCHOR_MARKERS = (
    'neuen standort', 'neue filiale', 'neues büro', 'expansion', 'expandieren',
    'wachstum', 'wachsen', 'herausforderung', 'problem', 'engpass', 'schwierigkeiten',
    'projekt', 'wir suchen', 'wir bauen gerade auf', 'skalieren', 'mehr mitarbeiter',
    'neues team', 'reorganisation', 'umstrukturierung',
)


@dataclass
class ConversationState:
    call_id: int | None = None
    current_phase: str = 'greeting'
    previous_phase: str | None = None
    turn_index: int = 0
    smalltalk_turns: int = 0
    business_transition_started: bool = False
    opening_completed: bool = False
    discovery_started: bool = False
    pitch_delivered: bool = False
    price_discussed: bool = False
    active_objection: str | None = None
    resolved_objections: list[str] = field(default_factory=list)
    last_seller_action: str | None = None
    last_prospect_event: str | None = None


def initial_state(call_id: int | None = None) -> ConversationState:
    return ConversationState(call_id=call_id)


def _front_index(phase: str) -> int | None:
    return FRONT_PHASE_ORDER.index(phase) if phase in FRONT_PHASE_ORDER else None


def has_business_anchor(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in BUSINESS_ANCHOR_MARKERS)


def _resume_phase(state: ConversationState) -> str:
    """Where the call should stay/return to when a new utterance would otherwise
    regress a front-of-call phase that has already been passed — never restart at
    greeting (or earlier) once real progress has been made."""
    if state.discovery_started:
        return 'discovery'
    if state.opening_completed:
        return 'discovery'
    if state.business_transition_started:
        return 'opening'
    return state.current_phase


def apply_prospect_turn(state: ConversationState, text: str, language_policy: dict) -> tuple[ConversationState, dict]:
    """Advances the conversation by one prospect turn. Returns (new_state, decision),
    where `decision` has the same shape as sales_brain.decide()'s return value
    (event, phase, strategy, suggestion, do_not, reason, confidence, smalltalk).
    """
    event = classify_sales_event(text)
    smalltalk = analyze_smalltalk(text, turn_index=state.turn_index)
    business_anchor = has_business_anchor(text)

    resolved_objections = list(state.resolved_objections)
    active_objection = state.active_objection
    discovery_started = state.discovery_started
    business_transition_started = state.business_transition_started
    opening_completed = state.opening_completed
    smalltalk_turns = state.smalltalk_turns
    price_discussed = state.price_discussed or event == 'price'

    if event in OBJECTION_EVENTS:
        if active_objection and active_objection != event:
            resolved_objections.append(active_objection)
        active_objection = event
        phase = 'objection'
    else:
        if active_objection:
            resolved_objections.append(active_objection)
            active_objection = None

        special_phase = detect_special_phase(text, turn_index=state.turn_index)

        if special_phase == 'rapport_smalltalk' and business_anchor:
            # A business-relevant anchor inside smalltalk IS a discovery opportunity —
            # never flatten it into generic rapport handling or a content-free
            # transition just because the sentence also reads as smalltalk.
            phase = 'discovery'
            discovery_started = True
            business_transition_started = True
            opening_completed = True
        elif special_phase == 'rapport_smalltalk':
            smalltalk_turns += 1
            # MVP default: after a first pure-smalltalk exchange, prefer moving toward
            # transition rather than prolonging rapport. This is a default, not a hard
            # rule — the business_anchor branch above already overrides it whenever
            # the prospect raises something relevant, at any turn.
            phase = 'transition' if smalltalk_turns > 1 else 'rapport_smalltalk'
            if phase == 'transition':
                business_transition_started = True
        elif special_phase:
            phase = special_phase
            if special_phase == 'transition':
                business_transition_started = True
            if special_phase in ('negotiation', 'closing'):
                # Reaching these implies opening/discovery already happened, even if
                # this specific call never had them explicitly detected.
                discovery_started = True
                opening_completed = True
                business_transition_started = True
        else:
            phase = 'pitch' if event == 'question' else event  # event == 'discovery'
            if phase == 'discovery':
                discovery_started = True
                opening_completed = True
                business_transition_started = True

        current_idx = _front_index(state.current_phase)
        new_idx = _front_index(phase)
        if current_idx is not None and new_idx is not None and new_idx < current_idx:
            phase = _resume_phase(state)

    response = build_response(phase=phase, event=event, language_policy=language_policy)

    new_state = ConversationState(
        call_id=state.call_id,
        current_phase=phase,
        previous_phase=state.current_phase,
        turn_index=state.turn_index + 1,
        smalltalk_turns=smalltalk_turns,
        business_transition_started=business_transition_started,
        opening_completed=opening_completed,
        discovery_started=discovery_started,
        pitch_delivered=state.pitch_delivered or phase in ('pitch', 'negotiation', 'closing'),
        price_discussed=price_discussed,
        active_objection=active_objection,
        resolved_objections=resolved_objections,
        last_seller_action=state.last_seller_action,
        last_prospect_event=event,
    )
    decision = {
        'event': event,
        'phase': phase,
        **response,
        'confidence': 0.88 if event != 'discovery' else 0.68,
        'smalltalk': smalltalk,
    }
    return new_state, decision


def apply_seller_turn(state: ConversationState, text: str) -> ConversationState:
    """Coarse bookkeeping for the seller's OWN turns. This only maintains
    last_seller_action / opening_completed / pitch_delivered — it never drives the
    phase machine itself, since REPLICA reacts to what the prospect says next, not to
    the seller's own utterance (see docs/DECISIONS.md ADR-023 on why 'opening' is not
    independently phase-classified)."""
    lower = text.lower()
    if any(m in lower for m in GREETING_MARKERS):
        action = 'greeting'
    elif any(m in lower for m in DIRECT_TO_BUSINESS_MARKERS) or 'ich rufe an' in lower or 'anlass meines anrufs' in lower:
        action = 'opening'
    elif any(m in lower for m in NEGOTIATION_MARKERS):
        action = 'negotiation'
    elif any(m in lower for m in CLOSING_MARKERS):
        action = 'closing'
    elif '?' in text:
        action = 'discovery_question'
    else:
        action = 'pitch'
    return replace(
        state,
        last_seller_action=action,
        opening_completed=state.opening_completed or action == 'opening',
        pitch_delivered=state.pitch_delivered or action == 'pitch',
    )
