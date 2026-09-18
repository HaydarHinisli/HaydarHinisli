from __future__ import annotations
import time
from .conversation_state import ConversationState, apply_turn
from .language_sync import analyze_language
from .sales_brain import decide


def suggest(
    utterance: str, recent_context: list[str] | None = None, reaction_snapshot: dict | None = None,
    *, turn_index: int | None = None,
) -> dict:
    """Stateless single-utterance suggestion — used for sandbox/practice mode
    (no call_id, see docs/DECISIONS.md ADR-015) where there is no persisted
    conversation state to advance. For a real call, use suggest_with_state()."""
    started = time.perf_counter()
    if turn_index is None:
        # Best-effort inference when the caller doesn't track it explicitly: how many
        # prior utterances have already been exchanged in this call.
        turn_index = len(recent_context or [])
    language_policy = analyze_language(utterance)
    decision = decide(utterance, language_policy, turn_index=turn_index)

    # The deterministic Fast Path is intentionally simple for the MVP.
    # Replace/augment with streaming ASR + small classifier + LLM Smart Path in production.
    result = {
        **decision,
        'language_policy': language_policy,
        'reaction_snapshot': reaction_snapshot or {},
        'evidence_level': 'heuristic_fast_path',
    }
    result['latency_ms'] = round((time.perf_counter() - started) * 1000, 2)
    return result


def suggest_with_state(
    state: ConversationState, utterance: str, reaction_snapshot: dict | None = None,
) -> tuple[ConversationState, dict, dict]:
    """Call-bound counterpart to suggest(): advances the call's persisted
    ConversationState by one prospect turn instead of reclassifying the utterance in
    isolation (Sprint 1.5, docs/DECISIONS.md ADR-026). Goes through the unified
    apply_turn() dispatcher (Provider-Ready Gate, ADR-030) so app/main.py gets a
    `transition` summary for the ConversationStateEvent history row without
    recomputing anything. Returns (new_state, result, transition)."""
    started = time.perf_counter()
    language_policy = analyze_language(utterance)
    new_state, transition, decision = apply_turn(state, 'prospect', utterance, language_policy)
    result = {
        **decision,
        'language_policy': language_policy,
        'reaction_snapshot': reaction_snapshot or {},
        'evidence_level': 'heuristic_fast_path_stateful',
    }
    result['latency_ms'] = round((time.perf_counter() - started) * 1000, 2)
    return new_state, result, transition
