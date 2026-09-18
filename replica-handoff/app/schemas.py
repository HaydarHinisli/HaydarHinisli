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


class SuggestRequest(BaseModel):
    call_id: int | None = None
    seller_id: int | None = None
    utterance: str = Field(min_length=1, max_length=6000)
    recent_context: list[str] = Field(default_factory=list, max_length=12)
    reaction_snapshot: dict = Field(default_factory=dict)


class SuggestionFeedbackRequest(BaseModel):
    rating: Literal['good', 'usable', 'bad']
    used: bool | None = None


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


class FeatureFlagRequest(BaseModel):
    feature_key: str
    enabled: bool
    jurisdiction: str | None = None
    campaign_type: str | None = None
    actor: str = 'admin'
    reason: str = ''


class ComplianceReviewSignoffRequest(BaseModel):
    action: str
    jurisdiction: str
    acknowledged_by: str
    reason: str = ''
    reference: str = ''
