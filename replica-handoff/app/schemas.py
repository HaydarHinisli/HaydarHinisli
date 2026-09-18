from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class CreateCallRequest(BaseModel):
    seller_id: int
    prospect_company: str = ''
    prospect_role: str = ''
    segment: str = ''
    offer_key: str = 'default'
    campaign_key: str = 'pilot'
    campaign_type: str = 'cold_b2b'
    prospect_type: Literal['b2b', 'b2c', 'unknown'] = 'unknown'
    speaker_mode: Literal['human_seller', 'human_with_replica_assist', 'ai_agent', 'hybrid'] = 'human_with_replica_assist'
    jurisdiction_country: str | None = None


class ConsentRequest(BaseModel):
    state: Literal['granted', 'declined', 'withdrawn']


class TurnRequest(BaseModel):
    speaker: Literal['seller', 'prospect']
    text: str = Field(min_length=1, max_length=6000)
    started_ms: int = 0
    ended_ms: int = 0
    asr_confidence: float | None = Field(default=None, ge=0, le=1)
    words_per_minute: float | None = Field(default=None, ge=0, le=500)
    response_latency_ms: float | None = Field(default=None, ge=0, le=30000)
    pause_before_ms: float | None = Field(default=None, ge=0, le=30000)
    overlap_ms: float | None = Field(default=None, ge=0, le=30000)
    avg_loudness_dbfs: float | None = None
    avg_pitch_hz: float | None = Field(default=None, ge=0, le=1000)
    pitch_range_hz: float | None = Field(default=None, ge=0, le=1000)
    # Provider-Ready Gate (ADR-031): optional today because current callers (manual
    # UI, demo flows) have no provider-stable identity to give us; a real streaming
    # ASR caller should always pass turn_id (and, when available, utterance_id/
    # stream_id/provider_event_id) so retries/reconnects can't double-process a turn.
    turn_id: str | None = Field(default=None, max_length=200)
    utterance_id: str | None = Field(default=None, max_length=200)
    stream_id: str | None = Field(default=None, max_length=200)
    provider_event_id: str | None = Field(default=None, max_length=200)


class SuggestRequest(BaseModel):
    call_id: int | None = None
    seller_id: int | None = None
    utterance: str = Field(min_length=1, max_length=6000)
    recent_context: list[str] = Field(default_factory=list, max_length=12)
    reaction_snapshot: dict = Field(default_factory=dict)
    turn_index: int | None = Field(default=None, ge=0)
    # Provider-Ready Gate: see TurnRequest above for turn_id/utterance_id/stream_id/
    # provider_event_id. trace_id lets a caller that already has one (from its own
    # POST /calls/{id}/turns call for the same utterance) correlate this suggestion
    # with that turn end-to-end instead of getting a fresh, unrelated one.
    turn_id: str | None = Field(default=None, max_length=200)
    utterance_id: str | None = Field(default=None, max_length=200)
    stream_id: str | None = Field(default=None, max_length=200)
    provider_event_id: str | None = Field(default=None, max_length=200)
    trace_id: str | None = Field(default=None, max_length=80)


class SuggestionFeedbackRequest(BaseModel):
    rating: Literal['good', 'usable', 'bad']
    used: bool | None = None


class SuggestionRenderAckRequest(BaseModel):
    """Sprint 3A (docs/DECISIONS.md ADR-048): the browser's own Render-ACK, sent
    once after a suggestion has actually been painted on screen — never estimated
    server-side. `*_epoch_ms` are wall-clock (`Date.now()`), used to correlate
    against this server's own wall-clock `t_turn_end_detected_at` for `real_rsl_ms`
    (the two are different processes/machines with no shared monotonic clock).
    `*_perf_ms` are the browser's own monotonic `performance.now()` readings, used
    only for the browser-local `client_render_latency_ms` delta — never compared
    against anything server-side."""
    trace_id: str | None = Field(default=None, max_length=80)
    call_id: int | None = None
    client_received_epoch_ms: float = Field(gt=0)
    client_rendered_epoch_ms: float = Field(gt=0)
    client_received_perf_ms: float = Field(ge=0)
    client_rendered_perf_ms: float = Field(ge=0)


class CompleteCallRequest(BaseModel):
    outcome: str = 'no_meeting'
    meeting_booked: bool = False
    meeting_held: bool = False
    qualified_opportunity: bool = False
    revenue: float = 0


class CreateExperimentRequest(BaseModel):
    key: str = Field(min_length=2, max_length=120)
    hypothesis: str = Field(min_length=5, max_length=2000)
    primary_metric: str = 'held_meeting_rate'
    variants: dict[str, dict]


class PolicyResolveRequest(BaseModel):
    action: str
    tenant_id: int | None = None
    call_id: int | None = None
    country_code: str | None = None
    prospect_type: Literal['b2b', 'b2c', 'unknown'] = 'unknown'
    campaign_type: str = 'cold_b2b'
    speaker_mode: Literal['human_seller', 'human_with_replica_assist', 'ai_agent', 'hybrid'] = 'human_with_replica_assist'


class ConsentEventRequest(BaseModel):
    consent_type: Literal[
        'call_recording', 'transcription', 'live_copilot_processing',
        'customer_private_learning', 'cross_customer_network_learning',
    ]
    status: Literal['granted', 'denied', 'withdrawn']
    purpose: str = ''
    jurisdiction: str = ''
    consent_text_version: str = 'v1'
    collection_method: str = 'api'
    evidence_ref: str = ''
    prospect_reference: str = ''


class NetworkLearningOptRequest(BaseModel):
    reason: str = ''
    evidence_ref: str = ''
    company_id: int | None = None


class FeatureFlagRequest(BaseModel):
    feature_key: str
    enabled: bool
    jurisdiction: str | None = None
    campaign_type: str | None = None
    reason: str = ''
    company_id: int | None = None


class ComplianceReviewSignoffRequest(BaseModel):
    action: str
    jurisdiction: str
    reason: str = ''
    reference: str = ''
    company_id: int | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class CreateUserRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    role: Literal['seller', 'manager', 'tenant_admin', 'compliance_admin']
