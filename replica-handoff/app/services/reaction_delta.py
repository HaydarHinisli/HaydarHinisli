from __future__ import annotations
from statistics import mean


def _avg(values):
    clean = [v for v in values if v is not None]
    return mean(clean) if clean else None


def build_baseline(prospect_turns: list) -> dict:
    sample = prospect_turns[:4]
    return {
        'words_per_minute': _avg([t.words_per_minute for t in sample]),
        'response_latency_ms': _avg([t.response_latency_ms for t in sample]),
        'avg_loudness_dbfs': _avg([t.avg_loudness_dbfs for t in sample]),
        'pitch_range_hz': _avg([t.pitch_range_hz for t in sample]),
        'turn_words': _avg([len(t.text.split()) for t in sample]),
    }


def reaction_delta(baseline: dict, current_turn) -> dict:
    mapping = {
        'words_per_minute': current_turn.words_per_minute,
        'response_latency_ms': current_turn.response_latency_ms,
        'avg_loudness_dbfs': current_turn.avg_loudness_dbfs,
        'pitch_range_hz': current_turn.pitch_range_hz,
        'turn_words': len(current_turn.text.split()),
    }
    deltas = {}
    for key, current in mapping.items():
        base = baseline.get(key)
        if base is None or current is None:
            deltas[key] = None
        elif key == 'avg_loudness_dbfs':
            deltas[key] = round(current - base, 2)
        elif base == 0:
            deltas[key] = None
        else:
            deltas[key] = round((current - base) / abs(base), 3)
    return {
        'baseline': baseline,
        'delta': deltas,
        'evidence_level': 'measured_or_derived',
        'interpretation_guardrail': 'Do not infer emotions or personality from these deltas.',
    }
