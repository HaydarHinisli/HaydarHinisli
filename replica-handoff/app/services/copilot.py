from __future__ import annotations
import time
from .language_sync import analyze_language
from .sales_brain import decide


def suggest(utterance: str, recent_context: list[str] | None = None, reaction_snapshot: dict | None = None) -> dict:
    started = time.perf_counter()
    language_policy = analyze_language(utterance)
    decision = decide(utterance, language_policy)

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
