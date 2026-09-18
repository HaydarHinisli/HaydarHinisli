from __future__ import annotations
import time
from .language_sync import analyze_language
from .sales_brain import decide


def suggest(
    utterance: str, recent_context: list[str] | None = None, reaction_snapshot: dict | None = None,
    *, turn_index: int | None = None,
) -> dict:
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
