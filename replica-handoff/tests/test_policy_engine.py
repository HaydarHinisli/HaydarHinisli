"""Pure evaluate() coverage — no database required.

Covers the required Sprint 0 scenarios: allowed function, forbidden function,
missing consent, withdrawn consent, unknown jurisdiction, autonomous voice without
approval, employee analytics restriction, network intelligence without opt-in,
plus the emotion-inference product-level prohibition.
"""
from app.compliance.jurisdiction_policy import JurisdictionPolicy, resolve_country_policy
from app.compliance.policy_engine import Decision, PolicyContext, evaluate


def _policy(**overrides) -> JurisdictionPolicy:
    base = dict(
        country_code='DE', is_default_fallback=False,
        human_copilot='enabled_with_conditions', recording='consent_and_legal_review',
        autonomous_marketing_call='disabled_by_default', ai_identity_disclosure='required_for_direct_ai_interaction',
        employee_analytics='high_risk_controls', emotion_inference_workplace='disabled',
        network_intelligence='aggregate_only', raw={},
    )
    base.update(overrides)
    return JurisdictionPolicy(**base)


def test_allowed_function_live_assist_with_consent():
    ctx = PolicyContext(jurisdiction_policy=_policy(), tenant_id=1, consent_status={'live_copilot_processing': 'granted'})
    decision = evaluate('live_assist', ctx)
    assert decision.result == Decision.ALLOWED


def test_forbidden_function_autonomous_call_hard_denied_in_de():
    # DE autonomous_marketing_call=disabled_by_default is a hard policy floor: even an
    # explicitly enabled tenant feature flag must not turn it on.
    ctx = PolicyContext(jurisdiction_policy=_policy(), tenant_id=1, feature_flags={'autonomous_call': True})
    decision = evaluate('autonomous_call', ctx)
    assert decision.result == Decision.DENIED


def test_missing_consent_requires_consent():
    ctx = PolicyContext(jurisdiction_policy=_policy(), tenant_id=1)
    decision = evaluate('live_assist', ctx)
    assert decision.result == Decision.REQUIRES_CONSENT


def test_withdrawn_consent_is_denied():
    ctx = PolicyContext(jurisdiction_policy=_policy(), tenant_id=1, consent_status={'live_copilot_processing': 'withdrawn'})
    decision = evaluate('live_assist', ctx)
    assert decision.result == Decision.DENIED


def test_unknown_jurisdiction_fails_closed():
    policy = resolve_country_policy('ZZ')
    assert policy.is_default_fallback is True
    ctx = PolicyContext(jurisdiction_policy=policy, tenant_id=1)
    decision = evaluate('record_audio', ctx)
    assert decision.result == Decision.REQUIRES_LEGAL_REVIEW


def test_autonomous_voice_blocked_without_explicit_enable():
    # GB technically allows autonomous marketing calls with consent, but the product
    # default keeps every tenant off until they explicitly opt in via a feature flag.
    gb = _policy(country_code='GB', autonomous_marketing_call='consent_only')
    ctx = PolicyContext(jurisdiction_policy=gb, tenant_id=1)
    decision = evaluate('autonomous_call', ctx)
    assert decision.result == Decision.DENIED


def test_autonomous_voice_allowed_once_tenant_enables_and_jurisdiction_permits():
    gb = _policy(country_code='GB', autonomous_marketing_call='consent_only')
    ctx = PolicyContext(jurisdiction_policy=gb, tenant_id=1, feature_flags={'autonomous_call': True})
    decision = evaluate('autonomous_call', ctx)
    assert decision.result == Decision.ALLOWED


def test_employee_analytics_blocked_until_review_signoff():
    ctx = PolicyContext(jurisdiction_policy=_policy(), tenant_id=1)
    decision = evaluate('employee_analytics', ctx)
    assert decision.result == Decision.REQUIRES_LEGAL_REVIEW


def test_employee_analytics_allowed_after_signoff():
    ctx = PolicyContext(jurisdiction_policy=_policy(), tenant_id=1, review_signoffs={'employee_analytics'})
    decision = evaluate('employee_analytics', ctx)
    assert decision.result == Decision.ALLOWED


def test_network_intelligence_requires_opt_in():
    ctx = PolicyContext(jurisdiction_policy=_policy(), tenant_id=1, network_learning_opt_in=False)
    decision = evaluate('network_learning', ctx)
    assert decision.result == Decision.REQUIRES_CONSENT


def test_network_intelligence_allowed_after_opt_in():
    ctx = PolicyContext(jurisdiction_policy=_policy(), tenant_id=1, network_learning_opt_in=True)
    decision = evaluate('network_learning', ctx)
    assert decision.result == Decision.ALLOWED


def test_emotion_inference_always_denied_even_with_signoff_and_flags():
    ctx = PolicyContext(
        jurisdiction_policy=_policy(), tenant_id=1,
        review_signoffs={'employee_analytics', 'emotion_inference'},
        feature_flags={'emotion_inference': True},
    )
    decision = evaluate('emotion_inference', ctx)
    assert decision.result == Decision.DENIED


def test_unknown_action_fails_closed():
    ctx = PolicyContext(jurisdiction_policy=_policy(), tenant_id=1)
    decision = evaluate('some_future_action_nobody_mapped_yet', ctx)
    assert decision.result == Decision.DENIED
