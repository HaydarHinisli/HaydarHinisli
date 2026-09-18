from __future__ import annotations
import hashlib


def assign_variant(call_id: int, experiment_key: str, variants: list[str]) -> str:
    if not variants:
        raise ValueError('variants required')
    digest = hashlib.sha256(f'{experiment_key}:{call_id}'.encode()).hexdigest()
    bucket = int(digest[:8], 16)
    return variants[bucket % len(variants)]
