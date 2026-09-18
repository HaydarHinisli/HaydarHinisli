from __future__ import annotations
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


class Company(Base):
    __tablename__ = 'companies'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    country_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    network_learning_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    """Auth identity. company_id is NULL only for role='system_admin' (cross-tenant
    superuser); every other role must belong to exactly one tenant."""
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey('companies.id'), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(40), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Seller(Base):
    __tablename__ = 'sellers'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('companies.id'), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(140))
    role: Mapped[str] = mapped_column(String(80), default='SDR')
    hired_at: Mapped[datetime] = mapped_column(DateTime)
    product_started_at: Mapped[datetime] = mapped_column(DateTime)
    company: Mapped[Company] = relationship()


class Call(Base):
    __tablename__ = 'calls'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('companies.id'), index=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey('sellers.id'), index=True)
    prospect_company: Mapped[str] = mapped_column(String(180), default='')
    prospect_role: Mapped[str] = mapped_column(String(140), default='')
    segment: Mapped[str] = mapped_column(String(140), default='')
    offer_key: Mapped[str] = mapped_column(String(120), default='default')
    campaign_key: Mapped[str] = mapped_column(String(120), default='pilot')
    campaign_type: Mapped[str] = mapped_column(String(60), default='cold_b2b')
    prospect_type: Mapped[str] = mapped_column(String(20), default='unknown')
    speaker_mode: Mapped[str] = mapped_column(String(40), default='human_with_replica_assist')
    jurisdiction_country: Mapped[str | None] = mapped_column(String(10), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consent_state: Mapped[str] = mapped_column(String(40), default='not_requested')
    consented_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    outcome: Mapped[str] = mapped_column(String(80), default='open')
    meeting_booked: Mapped[bool] = mapped_column(Boolean, default=False)
    meeting_held: Mapped[bool] = mapped_column(Boolean, default=False)
    qualified_opportunity: Mapped[bool] = mapped_column(Boolean, default=False)
    revenue: Mapped[float] = mapped_column(Float, default=0)
    external_call_id: Mapped[str] = mapped_column(String(220), default='')
    seller: Mapped[Seller] = relationship()


class Turn(Base):
    __tablename__ = 'turns'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey('calls.id'), index=True)
    speaker: Mapped[str] = mapped_column(String(20), index=True)
    text: Mapped[str] = mapped_column(Text)
    started_ms: Mapped[int] = mapped_column(Integer, default=0)
    ended_ms: Mapped[int] = mapped_column(Integer, default=0)
    asr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    words_per_minute: Mapped[float | None] = mapped_column(Float, nullable=True)
    response_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    pause_before_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    overlap_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_loudness_dbfs: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_pitch_hz: Mapped[float | None] = mapped_column(Float, nullable=True)
    pitch_range_hz: Mapped[float | None] = mapped_column(Float, nullable=True)
    lexical_complexity: Mapped[float | None] = mapped_column(Float, nullable=True)
    style_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    call: Mapped[Call] = relationship()


class Suggestion(Base):
    __tablename__ = 'suggestions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Nullable for pre-Sprint-1 rows; every suggestion created via the API from Sprint 1
    # onward always sets it (sandbox suggestions with call_id=None still belong to the
    # authenticated caller's tenant — see app/main.py copilot()). Without this, feedback
    # on a sandbox suggestion (no call_id to derive a tenant from) could not be tenant-scoped.
    company_id: Mapped[int | None] = mapped_column(ForeignKey('companies.id'), nullable=True, index=True)
    call_id: Mapped[int | None] = mapped_column(ForeignKey('calls.id'), nullable=True, index=True)
    # Provider-Ready Gate: correlates this suggestion end-to-end with the ASR/turn
    # pipeline event that produced it, for later real RSL measurement (t_turn_end ->
    # t_ui_rendered) once Sprint 2 exists — see docs/DECISIONS.md ADR-030/031.
    trace_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    prospect_text: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str] = mapped_column(Text)
    strategy: Mapped[str] = mapped_column(String(160))
    reason: Mapped[str] = mapped_column(Text, default='')
    do_not: Mapped[str] = mapped_column(Text, default='')
    confidence: Mapped[float] = mapped_column(Float, default=0)
    latency_ms: Mapped[float] = mapped_column(Float)
    language_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    reaction_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    rating: Mapped[str | None] = mapped_column(String(20), nullable=True)
    used: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class Meeting(Base):
    __tablename__ = 'meetings'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('companies.id'), index=True)
    call_id: Mapped[int | None] = mapped_column(ForeignKey('calls.id'), nullable=True, index=True)
    external_id: Mapped[str] = mapped_column(String(220), default='', index=True)
    source: Mapped[str] = mapped_column(String(60), default='manual')
    title: Mapped[str] = mapped_column(String(260), default='')
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    held: Mapped[bool] = mapped_column(Boolean, default=False)
    outcome: Mapped[str] = mapped_column(String(80), default='scheduled')


class Deal(Base):
    __tablename__ = 'deals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('companies.id'), index=True)
    call_id: Mapped[int | None] = mapped_column(ForeignKey('calls.id'), nullable=True, index=True)
    external_id: Mapped[str] = mapped_column(String(220), default='', index=True)
    source: Mapped[str] = mapped_column(String(60), default='manual')
    stage: Mapped[str] = mapped_column(String(120), default='open')
    amount: Mapped[float] = mapped_column(Float, default=0)
    closed_won: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Experiment(Base):
    __tablename__ = 'experiments'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('companies.id'), index=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    hypothesis: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default='draft')
    primary_metric: Mapped[str] = mapped_column(String(120), default='held_meeting_rate')
    variants: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ExperimentAssignment(Base):
    __tablename__ = 'experiment_assignments'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey('experiments.id'), index=True)
    call_id: Mapped[int] = mapped_column(ForeignKey('calls.id'), index=True)
    variant_key: Mapped[str] = mapped_column(String(80))
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('companies.id'), index=True)
    actor: Mapped[str] = mapped_column(String(180), default='system')
    action: Mapped[str] = mapped_column(String(180), index=True)
    entity_type: Mapped[str] = mapped_column(String(100), default='')
    entity_id: Mapped[str] = mapped_column(String(100), default='')
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ConsentEvent(Base):
    """Purpose-bound consent ledger entry.

    One row per consent action (grant/deny/withdraw) for one purpose. The current
    status for a purpose is always the most recent row for that (call_id, consent_type)
    pair, so history is preserved rather than overwritten.
    """
    __tablename__ = 'consent_events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('companies.id'), index=True)
    call_id: Mapped[int | None] = mapped_column(ForeignKey('calls.id'), nullable=True, index=True)
    prospect_reference: Mapped[str] = mapped_column(String(220), default='')
    consent_type: Mapped[str] = mapped_column(String(60), index=True)
    purpose: Mapped[str] = mapped_column(Text, default='')
    jurisdiction: Mapped[str] = mapped_column(String(10), default='')
    consent_text_version: Mapped[str] = mapped_column(String(40), default='')
    status: Mapped[str] = mapped_column(String(20), index=True)
    collection_method: Mapped[str] = mapped_column(String(60), default='api')
    evidence_ref: Mapped[str] = mapped_column(String(220), default='')
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TenantFeatureFlag(Base):
    """Tenant x jurisdiction x campaign_type kill-switch.

    Can only ever make a policy-allowed action MORE restrictive; the policy engine
    never lets an enabled flag override a policy-denied action (see policy_engine.evaluate).
    NULL jurisdiction/campaign_type means "applies to all" for that dimension.
    """
    __tablename__ = 'tenant_feature_flags'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('companies.id'), index=True)
    feature_key: Mapped[str] = mapped_column(String(80), index=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(10), nullable=True)
    campaign_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str] = mapped_column(String(180), default='system')
    reason: Mapped[str] = mapped_column(Text, default='')
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ComplianceReviewSignoff(Base):
    """Records that a tenant/action/jurisdiction combination requiring legal or
    compliance review has been reviewed and acknowledged. This is the only way a
    policy_engine 'requires_legal_review' tier can resolve toward allowed; it never
    clears a hard 'denied' tier (see policy_engine.evaluate).
    """
    __tablename__ = 'compliance_review_signoffs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('companies.id'), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    jurisdiction: Mapped[str] = mapped_column(String(10), index=True)
    acknowledged_by: Mapped[str] = mapped_column(String(180))
    reason: Mapped[str] = mapped_column(Text, default='')
    reference: Mapped[str] = mapped_column(String(220), default='')
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ConversationState(Base):
    """Sprint 1.5: call-bound conversation state so SalesBrain understands phase
    transitions across the whole running call (greeting -> rapport_smalltalk ->
    transition -> opening -> discovery, objections layered on top) instead of
    reclassifying each prospect sentence in isolation. One row per Call; mirrors
    app/services/conversation_state.ConversationState (see that module for the state
    machine itself — this is storage only).
    """
    __tablename__ = 'conversation_states'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey('calls.id'), unique=True, index=True)
    current_phase: Mapped[str] = mapped_column(String(40), default='greeting')
    previous_phase: Mapped[str | None] = mapped_column(String(40), nullable=True)
    turn_index: Mapped[int] = mapped_column(Integer, default=0)
    smalltalk_turns: Mapped[int] = mapped_column(Integer, default=0)
    business_transition_started: Mapped[bool] = mapped_column(Boolean, default=False)
    opening_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    discovery_started: Mapped[bool] = mapped_column(Boolean, default=False)
    pitch_delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    price_discussed: Mapped[bool] = mapped_column(Boolean, default=False)
    active_objection: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolved_objections: Mapped[list] = mapped_column(JSON, default=list)
    last_seller_action: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_prospect_event: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConversationStateEvent(Base):
    """Provider-Ready Gate: append-only history of conversation-state transitions,
    alongside (not instead of) the fast `ConversationState` snapshot above. One row
    per processed turn (prospect or seller), so post-call review, coaching, the
    Experiment Engine and the Cold Call Genome can reconstruct how a call actually
    developed, not just its current state. Writing this row is a single extra INSERT
    in the DB-aware endpoint layer (app/main.py) — the pure state machine in
    app/services/conversation_state.py stays exactly as fast as before (see
    docs/DECISIONS.md ADR-030).
    """
    __tablename__ = 'conversation_state_events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('companies.id'), index=True)
    call_id: Mapped[int] = mapped_column(ForeignKey('calls.id'), index=True)
    turn_index: Mapped[int] = mapped_column(Integer, default=0)
    speaker: Mapped[str] = mapped_column(String(20), index=True)
    from_phase: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_phase: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    objection_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sales_action: Mapped[str | None] = mapped_column(String(160), nullable=True)
    trigger: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    event_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class ProcessedTurnEvent(Base):
    """Provider-Ready Gate: exactly-once processing guard for real turns. Uniqueness
    is scoped to (call_id, action, turn_id): the same real utterance is legitimately
    claimed once for 'transcribe' (via POST /calls/{id}/turns) and once for
    'live_assist' (via POST /copilot/suggest) under today's two-endpoint MVP split —
    see docs/DECISIONS.md ADR-031/ADR-032. `turn_id` is REPLICA's own idempotency key;
    `utterance_id`/`stream_id`/`provider_event_id` are carried through for
    correlation/debugging but are not themselves the uniqueness boundary, since a
    provider may legitimately reuse or omit them across interim/final ASR revisions.
    `result_ref` points at the row produced by the first (successful) claim, so a
    duplicate can return the original result instead of reprocessing.
    """
    __tablename__ = 'processed_turn_events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('companies.id'), index=True)
    call_id: Mapped[int] = mapped_column(ForeignKey('calls.id'), index=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    turn_id: Mapped[str] = mapped_column(String(200), index=True)
    utterance_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    stream_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    result_ref: Mapped[dict] = mapped_column(JSON, default=dict)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint('call_id', 'action', 'turn_id', name='uq_processed_turn_event'),)


class WebhookDelivery(Base):
    """Provider-Ready Gate: idempotency ledger for inbound provider webhooks.
    Uniqueness on (provider, event_type, external_id) — a retried delivery of the
    same provider event is recognized and skipped rather than reprocessed (see
    docs/DECISIONS.md ADR-029).
    """
    __tablename__ = 'webhook_deliveries'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(60), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    external_id: Mapped[str] = mapped_column(String(220), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey('companies.id'), nullable=True, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    payload_summary: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (UniqueConstraint('provider', 'event_type', 'external_id', name='uq_webhook_delivery'),)
