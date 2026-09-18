"""Processing Permission Resolver: can_process(action, context) -> PolicyDecision.

Design invariants (see docs/DECISIONS.md ADR-007..ADR-010 for rationale):
  1. Fail closed. Any unrecognized action, jurisdiction value, or missing consent
     resolves to DENIED / REQUIRES_CONSENT / REQUIRES_LEGAL_REVIEW, never ALLOWED.
  2. A tenant feature flag can only make a decision MORE restrictive. It can turn an
     otherwise-allowed action off; it can never turn a policy-denied action on.
  3. A "requires_legal_review" tier can only resolve toward allowed via an explicit,
     audited ComplianceReviewSignoff. A "denied" tier never resolves via signoff or flag.
  4. Emotion/psychological-state inference is a permanent product-level prohibition,
     independent of jurisdiction, consent, or flags (ADR-003).

`evaluate()` is a pure function over PolicyContext so it can be unit-tested without a
database. `can_process()` is the DB-aware wrapper used by the API layer; it also writes
a 'policy.decision' audit event so every decision is explainable after the fact.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Company, ComplianceReviewSignoff, ConsentEvent, TenantFeatureFlag
from .audit import log_audit
from .jurisdiction_policy import JurisdictionPolicy, resolve_country_policy


class Decision(str, Enum):
    ALLOWED = 'allowed'
    DENIED = 'denied'
    REQUIRES_CONSENT = 'requires_consent'
    REQUIRES_LEGAL_REVIEW = 'requires_legal_review'


# Maps every literal value used in config/jurisdictions.yaml to a fail-closed tier.
# Any value not listed here (e.g. a future/typo'd value) defaults to 'review' via tier_for().
VALUE_TIER: dict[str, str] = {
    'disabled': 'denied',
    'disabled_by_default': 'denied',
    'disabled_by_product_policy': 'denied',
    'consent_only': 'consent',
    'enabled_with_conditions': 'consent',
    'aggregate_only': 'consent',
    'assist_only': 'consent',
    'review_required': 'review',
    'legal_review_required': 'review',
    'state_specific_review': 'review',
    'state_territory_review': 'review',
    'state_and_federal_review': 'review',
    'consent_and_legal_review': 'review',
    'high_risk_controls': 'review',
    'campaign_specific_review': 'review',
}

# ADR-008: transcribe/live_assist are governed by the human_copilot field (transient
# processing that enables copilot assistance); record_audio is governed by the
# stricter recording field (persistent storage of audio).
ACTION_POLICY_FIELD: dict[str, str] = {
    'record_audio': 'recording',
    'transcribe': 'human_copilot',
    'live_assist': 'human_copilot',
    'employee_analytics': 'employee_analytics',
    'autonomous_call': 'autonomous_marketing_call',
    'network_learning': 'network_intelligence',
}

CONSENT_PURPOSE: dict[str, str] = {
    'record_audio': 'call_recording',
    'transcribe': 'transcription',
    'live_assist': 'live_copilot_processing',
}
CONSENT_GATED_ACTIONS = set(CONSENT_PURPOSE)

# ADR-010: autonomous_call defaults to denied for every tenant/jurisdiction until a
# tenant explicitly enables it via TenantFeatureFlag, even where the jurisdiction
# tier alone would otherwise permit it (product default: autonomous voice OFF).
DEFAULT_DENY_ACTIONS = {'autonomous_call'}

KNOWN_ACTIONS = set(ACTION_POLICY_FIELD) | {'emotion_inference'}


def tier_for(value: str) -> str:
    return VALUE_TIER.get(value, 'review')


@dataclass
class PolicyContext:
    jurisdiction_policy: JurisdictionPolicy
    tenant_id: int
    review_signoffs: set[str] = field(default_factory=set)
    feature_flags: dict[str, bool] = field(default_factory=dict)
    network_learning_opt_in: bool = False
    consent_status: dict[str, str] = field(default_factory=dict)
    prospect_type: str = 'unknown'
    campaign_type: str = 'cold_b2b'
    speaker_mode: str = 'human_with_replica_assist'

    def has_review_signoff(self, action: str) -> bool:
        return action in self.review_signoffs

    def feature_flag_state(self, action: str) -> str:
        if action not in self.feature_flags:
            return 'not_set'
        return 'enabled' if self.feature_flags[action] else 'disabled'


@dataclass(frozen=True)
class PolicyDecision:
    action: str
    result: Decision
    reason: str
    policy_reference: str

    def as_dict(self) -> dict:
        return {
            'action': self.action,
            'result': self.result.value,
            'reason': self.reason,
            'policy_reference': self.policy_reference,
        }


def evaluate(action: str, ctx: PolicyContext) -> PolicyDecision:
    if action not in KNOWN_ACTIONS:
        return PolicyDecision(action, Decision.DENIED, f'Unknown action "{action}" has no policy mapping; failing closed.', 'policy_engine.unknown_action')

    if action == 'emotion_inference':
        return PolicyDecision(
            action, Decision.DENIED,
            'Emotion/psychological-state inference from voice or behavioral signals is a '
            'permanent product-level prohibition, independent of jurisdiction, consent, or feature flags.',
            'GLOBAL_PRODUCT_COMPLIANCE_SPEC.md#1.2 / ADR-003',
        )

    field_name = ACTION_POLICY_FIELD[action]
    raw_value = getattr(ctx.jurisdiction_policy, field_name)
    tier = tier_for(raw_value)
    ref = f'config/jurisdictions.yaml:{ctx.jurisdiction_policy.country_code}.{field_name}={raw_value}'

    if tier == 'denied':
        return PolicyDecision(action, Decision.DENIED, f'Jurisdiction policy blocks "{action}" ({field_name}={raw_value}).', ref)

    if tier == 'review' and not ctx.has_review_signoff(action):
        return PolicyDecision(
            action, Decision.REQUIRES_LEGAL_REVIEW,
            f'{field_name}={raw_value} requires a recorded compliance review signoff before '
            f'"{action}" can proceed for {ctx.jurisdiction_policy.country_code}.',
            ref,
        )

    flag_state = ctx.feature_flag_state(action)
    if flag_state == 'disabled':
        return PolicyDecision(action, Decision.DENIED, f'Tenant feature flag explicitly disables "{action}".', 'tenant_feature_flag')
    if action in DEFAULT_DENY_ACTIONS and flag_state != 'enabled':
        return PolicyDecision(
            action, Decision.DENIED,
            f'"{action}" defaults to disabled for every tenant/jurisdiction until explicitly '
            'enabled (product default: autonomous voice OFF everywhere).',
            'product_default_deny',
        )

    if action == 'network_learning':
        if not ctx.network_learning_opt_in:
            return PolicyDecision(action, Decision.REQUIRES_CONSENT, 'Tenant has not opted into Network Intelligence.', ref)
        return PolicyDecision(action, Decision.ALLOWED, 'Tenant opted into aggregated, delayed Network Intelligence.', ref)

    if action in ('employee_analytics', 'autonomous_call'):
        return PolicyDecision(action, Decision.ALLOWED, f'{field_name}={raw_value} permits "{action}" for this tenant/jurisdiction.', ref)

    # Remaining actions are exactly the per-call consent-gated ones (record_audio,
    # transcribe, live_assist); every other action returns earlier above.
    purpose = CONSENT_PURPOSE[action]
    status = ctx.consent_status.get(purpose, 'not_requested')
    if status == 'granted':
        return PolicyDecision(action, Decision.ALLOWED, f'Consent granted for purpose "{purpose}".', ref)
    if status in ('withdrawn', 'denied'):
        return PolicyDecision(action, Decision.DENIED, f'Consent for purpose "{purpose}" is {status}.', ref)
    return PolicyDecision(action, Decision.REQUIRES_CONSENT, f'Consent for purpose "{purpose}" has not been granted yet.', ref)


def _best_flag(rows: list[TenantFeatureFlag], country_code: str, campaign_type: str) -> bool | None:
    """Picks the most specific matching flag row: jurisdiction+campaign > jurisdiction
    > campaign > global. Ties broken by most recently updated."""
    best: TenantFeatureFlag | None = None
    best_score = -1
    for row in rows:
        if row.jurisdiction not in (None, country_code):
            continue
        if row.campaign_type not in (None, campaign_type):
            continue
        score = (2 if row.jurisdiction == country_code else 0) + (1 if row.campaign_type == campaign_type else 0)
        if score > best_score or (score == best_score and best is not None and row.updated_at >= best.updated_at):
            best, best_score = row, score
    return None if best is None else bool(best.enabled)


def build_context(
    db: Session, *, action: str, tenant_id: int, call_id: int | None = None,
    country_code: str | None = None, prospect_type: str = 'unknown',
    campaign_type: str = 'cold_b2b', speaker_mode: str = 'human_with_replica_assist',
) -> PolicyContext:
    jurisdiction_policy = resolve_country_policy(country_code)

    signoff_rows = db.scalars(
        select(ComplianceReviewSignoff).where(
            ComplianceReviewSignoff.company_id == tenant_id,
            ComplianceReviewSignoff.jurisdiction == jurisdiction_policy.country_code,
        )
    ).all()
    review_signoffs = {row.action for row in signoff_rows}

    flag_rows = db.scalars(
        select(TenantFeatureFlag).where(
            TenantFeatureFlag.company_id == tenant_id,
            TenantFeatureFlag.feature_key == action,
        )
    ).all()
    feature_flags: dict[str, bool] = {}
    resolved = _best_flag(flag_rows, jurisdiction_policy.country_code, campaign_type)
    if resolved is not None:
        feature_flags[action] = resolved

    company = db.get(Company, tenant_id)
    network_learning_opt_in = bool(company.network_learning_opt_in) if company else False

    consent_status: dict[str, str] = {}
    if call_id is not None:
        for purpose in set(CONSENT_PURPOSE.values()):
            row = db.scalars(
                select(ConsentEvent)
                .where(ConsentEvent.call_id == call_id, ConsentEvent.consent_type == purpose)
                .order_by(ConsentEvent.captured_at.desc())
            ).first()
            if row is not None:
                consent_status[purpose] = row.status

    return PolicyContext(
        jurisdiction_policy=jurisdiction_policy,
        tenant_id=tenant_id,
        review_signoffs=review_signoffs,
        feature_flags=feature_flags,
        network_learning_opt_in=network_learning_opt_in,
        consent_status=consent_status,
        prospect_type=prospect_type,
        campaign_type=campaign_type,
        speaker_mode=speaker_mode,
    )


def can_process(
    db: Session, action: str, *, tenant_id: int, call_id: int | None = None,
    country_code: str | None = None, prospect_type: str = 'unknown',
    campaign_type: str = 'cold_b2b', speaker_mode: str = 'human_with_replica_assist',
    log: bool = True,
) -> PolicyDecision:
    ctx = build_context(
        db, action=action, tenant_id=tenant_id, call_id=call_id, country_code=country_code,
        prospect_type=prospect_type, campaign_type=campaign_type, speaker_mode=speaker_mode,
    )
    decision = evaluate(action, ctx)
    if log:
        log_audit(
            db, tenant_id, actor='system', action='policy.decision',
            entity_type='policy_action', entity_id=action,
            payload={
                **decision.as_dict(),
                'country_code': ctx.jurisdiction_policy.country_code,
                'call_id': call_id,
                'campaign_type': campaign_type,
                'speaker_mode': speaker_mode,
            },
        )
    return decision
