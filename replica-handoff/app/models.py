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
    """Provider-Ready Gate: idempotent, effectively-once processing guard for real
    turns — precisely: not "exactly-once delivery" (a provider may call REPLICA more
    than once for the same real turn), but the persisted effect happens exactly once
    per successful attempt, and a failed attempt leaves zero trace, because the claim
    lives in the same DB transaction as every other side effect the turn produces
    (see docs/DECISIONS.md ADR-034). Uniqueness is scoped to (call_id, action,
    turn_id): the same real utterance is legitimately claimed once for 'transcribe'
    (via POST /calls/{id}/turns) and once for 'live_assist' (via POST
    /copilot/suggest) under today's two-endpoint MVP split — see ADR-031/ADR-032.
    `turn_id` is REPLICA's own idempotency key; `utterance_id`/`stream_id`/
    `provider_event_id` are carried through for correlation/debugging but are not
    themselves the uniqueness boundary, since a provider may legitimately reuse or
    omit them across interim/final ASR revisions. `result_ref` points at the result
    produced by the first (successful) claim, so a duplicate can return it instead of
    reprocessing.
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


class CallProviderStatus(Base):
    """Provider-Ready Gate hardening: materialized "latest applied" provider call
    status, kept separate from the WebhookDelivery ledger above (which only records
    "have I seen this exact event before") and from Call's own seller-driven business
    outcome fields. Twilio delivers status callbacks at-least-once and in no
    guaranteed order — this row is what `app/webhooks/call_status.is_newer_event()`
    compares an incoming event against, so a late/out-of-order event (e.g. a delayed
    'in-progress' arriving after 'completed' was already applied) can be recognized
    and NOT applied, without discarding the fact that it arrived (see ADR-035).
    Keyed by (provider, external_call_id) rather than call_id so it works even before
    a matching `Call` row can be resolved.
    """
    __tablename__ = 'call_provider_status'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(60), index=True)
    external_call_id: Mapped[str] = mapped_column(String(220), index=True)
    call_id: Mapped[int | None] = mapped_column(ForeignKey('calls.id'), nullable=True, index=True)
    last_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_sequence_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint('provider', 'external_call_id', name='uq_call_provider_status'),)


class TurnLatencyTrace(Base):
    """Sprint 2: end-to-end pipeline timing for one final turn, produced by the
    Twilio Media Streams pipeline (app/streaming/pipeline.py) via
    app/streaming/timing.py's LatencyTrace. One row per final turn processed through
    app/services/turn_pipeline.process_final_turn().

    Wall-clock `_at` columns are for audit/cross-system correlation only. Every
    server-side `_ms` duration column (everything except `real_rsl_ms` and
    `client_render_latency_ms`, see below) is computed from monotonic clock
    readings taken in-process (see docs/DECISIONS.md ADR-041) — monotonic values
    themselves are never persisted, only the deltas, since a monotonic clock's
    epoch is arbitrary and meaningless outside the process that read it.

    `salesbrain_latency_ms` is the pre-existing internal Fast-Path engine latency
    (ADR-021/022) now measured inside a real pipeline — it is NOT, and must never be
    reported as, real RSL. `real_rsl_ms` is the actual product metric
    (`t_ui_rendered - t_turn_end_detected`, per docs/ARCHITECTURE.md §8) and stays
    NULL until a real Render-ACK from the browser exists (Sprint 3A, ADR-048); it is
    never backfilled with an approximation. Unlike every other `_ms` column here,
    `real_rsl_ms` is necessarily a WALL-CLOCK delta, not a monotonic one — the
    browser and this server are different processes (usually different machines)
    with no shared monotonic clock, so wall-clock is the only cross-machine
    correlation available, exactly as docs/DATA_MODEL.md's evidence-level note and
    the Sprint 3A brief both allow ("Wall-Clock kann zusätzlich für Korrelation/
    Audit vorhanden sein"). This means `real_rsl_ms` inherits ordinary NTP clock-skew
    risk between the two machines — a documented limitation, not an oversight.

    Sprint 2B (ADR-045/046): `asr_provider`/`is_synthetic` make it structurally
    impossible to confuse a `SimulatedASRProvider` development measurement with a
    real-provider one when querying this table later — every row states which
    produced it. `t_provider_endpoint_detected_at` / `provider_endpoint_vs_turn_end_ms`
    capture the ASR provider's OWN endpointing signal (e.g. Deepgram's
    `speech_final`), purely so it can be compared against our VAD-driven
    `t_turn_end_detected_at` after real test calls — never used to drive turn-end
    itself (our own VAD remains authoritative, see docs/DECISIONS.md ADR-039/046).

    Sprint 3A (ADR-048): `t_browser_received_at`/`t_ui_rendered_at` and
    `client_render_latency_ms` are populated later, out of band, by
    POST /api/suggestions/{id}/render-ack — NOT by the streaming pipeline that
    creates this row. `client_render_latency_ms` is the browser's own monotonic
    delta (`performance.now()` at render minus at receipt) and is a distinct
    measurement from `real_rsl_ms`: one is "how long did the browser take to paint
    it", the other is "how long did the whole thing take from turn-end" — never
    merged into a single number.
    """
    __tablename__ = 'turn_latency_traces'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('companies.id'), index=True)
    call_id: Mapped[int] = mapped_column(ForeignKey('calls.id'), index=True)
    turn_id: Mapped[str] = mapped_column(String(200), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    speaker: Mapped[str] = mapped_column(String(20))

    # Sprint 2B: which ASR provider produced this trace, and whether it is a
    # synthetic development measurement (SimulatedASRProvider) or a real one.
    # Defaults assume the pre-Sprint-2B/simulated case so existing call sites that
    # don't pass these explicitly stay honestly labelled as synthetic, never
    # silently "real" by omission.
    asr_provider: Mapped[str] = mapped_column(String(40), default='simulated', index=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    t_audio_received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    t_asr_interim_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    t_asr_final_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    t_turn_end_detected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    t_provider_endpoint_detected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    t_salesbrain_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    t_salesbrain_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    t_suggestion_persisted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    t_suggestion_pushed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Sprint 3A (ADR-048): set from the browser's own Render-ACK, NOT estimated
    # server-side — the two halves of "how long did delivery to the browser take"
    # vs. "how long did the browser take to paint it" (client_render_latency_ms
    # below), kept separate rather than blended into one number.
    t_browser_received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    t_ui_rendered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    audio_to_interim_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    audio_to_final_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    turn_detection_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Positive: our VAD-driven turn-end fired AFTER the provider's own endpointing
    # signal. Negative: ours fired first. Comparison-only (ADR-046) — see above.
    provider_endpoint_vs_turn_end_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    salesbrain_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggestion_persist_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggestion_push_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Sprint 3A (ADR-048): the browser's OWN monotonic delta (performance.now() at
    # render minus performance.now() at receipt) — how long the browser itself took
    # to paint the suggestion after receiving it. Never mixed with any server-side
    # or wall-clock number; it is meaningful only as a client-local duration.
    client_render_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    real_rsl_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
