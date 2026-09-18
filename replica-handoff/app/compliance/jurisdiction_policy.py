"""Loads config/jurisdictions.yaml as the first-cut, server-side policy source.

This is an engineering default, not legal advice (see docs/GLOBAL_PRODUCT_COMPLIANCE_SPEC.md
and docs/SECURITY_PRIVACY.md). Any country not explicitly listed falls back to the
`default` block, which is intentionally conservative (fail closed).
"""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / 'config' / 'jurisdictions.yaml'


@dataclass(frozen=True)
class JurisdictionPolicy:
    country_code: str
    is_default_fallback: bool
    human_copilot: str
    recording: str
    autonomous_marketing_call: str
    ai_identity_disclosure: str
    employee_analytics: str
    emotion_inference_workplace: str
    network_intelligence: str
    raw: dict


@lru_cache
def _catalog() -> dict:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as fh:
        return yaml.safe_load(fh)


def get_policy_catalog() -> dict:
    """Returns the raw parsed jurisdictions.yaml. Cached for the process lifetime;
    a config change requires a restart (Sprint 1+ candidate: hot reload / DB-backed policy).
    """
    return _catalog()


def resolve_country_policy(country_code: str | None) -> JurisdictionPolicy:
    catalog = get_policy_catalog()
    default = catalog.get('default', {})
    countries = catalog.get('jurisdictions', {})
    code = (country_code or '').upper().strip()
    entry = countries.get(code)
    is_fallback = entry is None
    merged = {**default, **(entry or {})}
    return JurisdictionPolicy(
        country_code=code or 'DEFAULT',
        is_default_fallback=is_fallback,
        human_copilot=merged.get('human_copilot', 'review_required'),
        recording=merged.get('recording', 'review_required'),
        autonomous_marketing_call=merged.get('autonomous_marketing_call', 'disabled'),
        ai_identity_disclosure=merged.get('ai_identity_disclosure', 'review_required'),
        employee_analytics=merged.get('employee_analytics', 'review_required'),
        emotion_inference_workplace=merged.get('emotion_inference_workplace', 'disabled'),
        network_intelligence=merged.get('network_intelligence', 'aggregate_only'),
        raw=merged,
    )
