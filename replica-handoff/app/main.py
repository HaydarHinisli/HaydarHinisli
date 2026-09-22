from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape
import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import SessionLocal, get_db
from .migrate import run_migrations
from .models import (
    AuditEvent, Call, Company, ComplianceReviewSignoff, ConsentEvent, Experiment,
    ExperimentAssignment, Meeting, Seller, Suggestion, TenantFeatureFlag, Turn, TurnLatencyTrace, User,
)
from .schemas import (
    CompleteCallRequest, ComplianceReviewSignoffRequest, ConsentEventRequest, ConsentRequest, CreateCallRequest,
    CreateExperimentRequest, CreateUserRequest, FeatureFlagRequest, LoginRequest, NetworkLearningOptRequest,
    PolicyResolveRequest, SuggestRequest, SuggestionFeedbackRequest, SuggestionRenderAckRequest, TurnRequest,
)
from .secrets import get_secrets_provider
from .seed import seed_demo
from .services.clock_sync import ClockSyncSample, estimate_clock_sync
from .services.latency_trace import RUNTIME_BOOT_ID
from .services.conversation_state import apply_turn
from .services.conversation_state_store import (
    apply_state_to_row, conversation_state_dict, load_or_create_conversation_state_row,
    record_state_event, state_from_row,
)
from .services.copilot import suggest, suggest_with_state
from .services.experiments import assign_variant
from .services.language_sync import analyze_language
from .services.live_push import get_live_suggestion_hub
from .services.voice_call_guard import get_voice_call_lock, get_voice_ticket_ledger
from .services.reaction_delta import build_baseline, reaction_delta
from .services.review import build_call_review, manager_analysis
from .services.turn_identity import claim_turn, record_result, synthesize_turn_id
from .integrations import google_calendar, hubspot, salesforce, twilio_rest
from .integrations.openai_realtime import status as openai_status, session_blueprint
from .streaming.asr import ASRProvider, get_asr_provider
from .streaming.media_stream_security import is_secure_transport, verify_media_stream_signature
from .streaming.media_stream_session import MediaStreamSession
from .streaming.pipeline import MediaStreamPipeline, PipelineStatus
from .services.ws_origin import is_allowed_origin, parse_allowed_origins
from .compliance.admin import record_review_signoff, set_feature_flag, set_network_learning_opt_in
from .compliance.audit import log_audit
from .compliance.jurisdiction_policy import resolve_country_policy
from .compliance.policy_engine import Decision, can_process
from .auth.dependencies import AuthContext, get_current_user, require_role, resolve_tenant_id
from .auth.security import (
    create_access_token, create_voice_call_ticket, decode_access_token, decode_voice_call_ticket,
    hash_password, verify_password,
)
from .logging_config import RequestContextMiddleware, configure_logging
from .webhooks.call_status import get_or_create_provider_status, is_newer_event, parse_sequence_number
from .webhooks.idempotency import claim_webhook_delivery
from .webhooks.security import compute_twilio_signature, verify_twilio_signature

logger = logging.getLogger('replica.webhooks')

BASE_DIR = Path(__file__).resolve().parent
settings = get_settings()
configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Sprint 1: schema is now versioned via Alembic instead of Base.metadata.create_all(),
    # so a stale local SQLite file no longer needs to be deleted between pulls — see
    # app/migrate.py and docs/DECISIONS.md ADR-017.
    run_migrations()
    if settings.replica_demo_mode:
        seed_demo()
    yield


app = FastAPI(title='REPLICA MVP', version='0.4.0', description='Adaptive Sales Intelligence pilot', lifespan=lifespan)
app.add_middleware(RequestContextMiddleware)
app.mount('/static', StaticFiles(directory=BASE_DIR/'static'), name='static')


@app.get('/')
def root():
    return FileResponse(BASE_DIR/'static'/'index.html')


@app.get('/api/health')
def health():
    return {'status': 'ok', 'version': '0.4.0', 'env': settings.replica_env, 'demo_mode': settings.replica_demo_mode}


def _get_call_or_404(db: Session, call_id: int, tenant_id: int) -> Call:
    """Cross-tenant access returns 404, never 403 — a tenant must not be able to
    distinguish "this call belongs to someone else" from "this call doesn't exist"
    by probing IDs."""
    call = db.get(Call, call_id)
    if not call or call.company_id != tenant_id:
        raise HTTPException(404, 'Call not found')
    return call


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.post('/api/auth/login')
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == req.email))
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, 'Invalid email or password')
    if not user.is_active:
        raise HTTPException(403, 'Account is disabled')
    user.last_login_at = datetime.utcnow()
    db.commit()
    token = create_access_token(user_id=user.id, company_id=user.company_id, role=user.role)
    return {
        'access_token': token,
        'token_type': 'bearer',
        'user': {'id': user.id, 'email': user.email, 'role': user.role, 'company_id': user.company_id},
    }


@app.get('/api/auth/me')
def me(current_user: AuthContext = Depends(get_current_user)):
    return {'id': current_user.user_id, 'email': current_user.email, 'role': current_user.role, 'company_id': current_user.company_id}


@app.post('/api/admin/users')
def create_user(req: CreateUserRequest, current_user: AuthContext = Depends(require_role('tenant_admin')), db: Session = Depends(get_db)):
    existing = db.scalar(select(User).where(User.email == req.email))
    if existing:
        raise HTTPException(409, 'Email already registered')
    user = User(company_id=current_user.company_id, email=req.email, password_hash=hash_password(req.password), role=req.role, is_active=True)
    db.add(user)
    db.flush()
    log_audit(db, current_user.company_id, actor=current_user.email, action='user.created', entity_type='user', entity_id=str(user.id), payload={'email': req.email, 'role': req.role})
    db.commit()
    db.refresh(user)
    return {'id': user.id, 'email': user.email, 'role': user.role, 'is_active': user.is_active}


@app.post('/api/admin/users/{user_id}/deactivate')
def deactivate_user(user_id: int, current_user: AuthContext = Depends(require_role('tenant_admin')), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user or user.company_id != current_user.company_id:
        raise HTTPException(404, 'User not found')
    user.is_active = False
    log_audit(db, current_user.company_id, actor=current_user.email, action='user.deactivated', entity_type='user', entity_id=str(user.id))
    db.commit()
    return {'ok': True, 'is_active': user.is_active}


@app.post('/api/admin/users/{user_id}/activate')
def activate_user(user_id: int, current_user: AuthContext = Depends(require_role('tenant_admin')), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user or user.company_id != current_user.company_id:
        raise HTTPException(404, 'User not found')
    user.is_active = True
    log_audit(db, current_user.company_id, actor=current_user.email, action='user.activated', entity_type='user', entity_id=str(user.id))
    db.commit()
    return {'ok': True, 'is_active': user.is_active}


# ---------------------------------------------------------------------------
# Dashboard / calls / turns / copilot
# ---------------------------------------------------------------------------

@app.get('/api/dashboard')
def dashboard(current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin')), db: Session = Depends(get_db)):
    company_id = current_user.company_id
    calls = db.scalars(select(Call).where(Call.company_id == company_id)).all()
    sellers = db.scalars(select(Seller).where(Seller.company_id == company_id)).all()
    meetings = db.scalars(select(Meeting).where(Meeting.company_id == company_id).order_by(Meeting.starts_at)).all()
    suggestions = db.scalars(select(Suggestion).where(Suggestion.company_id == company_id)).all()
    total = len(calls); booked = sum(c.meeting_booked for c in calls); held = sum(c.meeting_held for c in calls); opps = sum(c.qualified_opportunity for c in calls)
    helpful = sum(1 for s in suggestions if s.rating in ('good','usable')); rated = sum(1 for s in suggestions if s.rating)
    latency_values = [s.latency_ms for s in suggestions]
    return {
        'demo_data': settings.replica_demo_mode,
        'kpis': {
            'calls': total,
            'meeting_rate': round(booked/max(total,1)*100,1),
            'held_rate': round(held/max(booked,1)*100,1),
            'opportunity_rate': round(opps/max(total,1)*100,1),
            'helpful_suggestion_rate': round(helpful/max(rated,1)*100,1) if rated else None,
            'suggestion_latency_engine_ms': round(sum(latency_values)/len(latency_values),1) if latency_values else None,
        },
        'sellers': [{'id': s.id, 'name': s.name, 'role': s.role} for s in sellers],
        'upcoming_meetings': [
            {'id': m.id, 'title': m.title, 'starts_at': m.starts_at.isoformat(), 'source': m.source, 'held': m.held}
            for m in meetings if m.starts_at >= datetime.utcnow()
        ][:6],
    }


@app.post('/api/calls')
def create_call(req: CreateCallRequest, current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin')), db: Session = Depends(get_db)):
    seller = db.get(Seller, req.seller_id)
    if not seller or seller.company_id != current_user.company_id:
        raise HTTPException(404, 'Seller not found')
    company = db.get(Company, current_user.company_id)
    jurisdiction_country = req.jurisdiction_country or (company.country_code if company else None)
    call = Call(
        company_id=current_user.company_id, seller_id=seller.id, prospect_company=req.prospect_company,
        prospect_role=req.prospect_role, segment=req.segment, offer_key=req.offer_key, campaign_key=req.campaign_key,
        campaign_type=req.campaign_type, prospect_type=req.prospect_type, speaker_mode=req.speaker_mode,
        jurisdiction_country=jurisdiction_country,
    )
    db.add(call)
    db.flush()
    log_audit(db, current_user.company_id, actor=current_user.email, action='call.created', entity_type='call', entity_id=str(call.id))
    db.commit()
    db.refresh(call)
    return {'id': call.id, 'consent_state': call.consent_state, 'jurisdiction_country': call.jurisdiction_country}


@app.post('/api/calls/{call_id}/consent')
def set_consent(call_id: int, req: ConsentRequest, current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin')), db: Session = Depends(get_db)):
    call = _get_call_or_404(db, call_id, current_user.company_id)
    call.consent_state = req.state
    call.consented_at = datetime.utcnow() if req.state == 'granted' else None
    # Convenience: this legacy single-field gate now only drives display state.
    # Enforcement always runs through can_process() against the ConsentEvent ledger
    # below (see docs/DECISIONS.md ADR-019) — granting here writes BOTH purposes this
    # endpoint has always covered in one action (ADR-016), it does not itself bypass anything.
    event_status = {'granted': 'granted', 'declined': 'denied', 'withdrawn': 'withdrawn'}[req.state]
    withdrawn_at = datetime.utcnow() if event_status == 'withdrawn' else None
    for consent_type, label in (
        ('live_copilot_processing', 'Live-Copilot-Verarbeitung während des Calls'),
        ('transcription', 'Transkription der Gesprächsbeiträge'),
    ):
        db.add(ConsentEvent(
            company_id=call.company_id, call_id=call.id, consent_type=consent_type,
            purpose=label, status=event_status, collection_method='api', withdrawn_at=withdrawn_at,
        ))
    log_audit(db, call.company_id, actor=current_user.email, action=f'consent.{req.state}', entity_type='call', entity_id=str(call.id))
    db.commit()
    return {'ok': True, 'consent_state': call.consent_state}


@app.post('/api/calls/{call_id}/consents')
def create_consent_event(call_id: int, req: ConsentEventRequest, current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin')), db: Session = Depends(get_db)):
    call = _get_call_or_404(db, call_id, current_user.company_id)
    row = ConsentEvent(
        company_id=call.company_id, call_id=call_id, prospect_reference=req.prospect_reference,
        consent_type=req.consent_type, purpose=req.purpose or req.consent_type, jurisdiction=req.jurisdiction,
        consent_text_version=req.consent_text_version, status=req.status, collection_method=req.collection_method,
        evidence_ref=req.evidence_ref, withdrawn_at=datetime.utcnow() if req.status == 'withdrawn' else None,
    )
    db.add(row)
    log_audit(db, call.company_id, actor=current_user.email, action=f'consent.{req.status}', entity_type='consent_event', entity_id=req.consent_type, payload={'call_id': call_id, 'consent_type': req.consent_type, 'status': req.status})
    db.commit()
    db.refresh(row)
    return {'id': row.id, 'consent_type': row.consent_type, 'status': row.status, 'captured_at': row.captured_at.isoformat()}


@app.post('/api/calls/{call_id}/consents/{purpose}/withdraw')
def withdraw_consent_event(call_id: int, purpose: str, current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin')), db: Session = Depends(get_db)):
    call = _get_call_or_404(db, call_id, current_user.company_id)
    row = ConsentEvent(company_id=call.company_id, call_id=call_id, consent_type=purpose, purpose=purpose, status='withdrawn', collection_method='api', withdrawn_at=datetime.utcnow())
    db.add(row)
    log_audit(db, call.company_id, actor=current_user.email, action='consent.withdrawn', entity_type='consent_event', entity_id=purpose, payload={'call_id': call_id, 'consent_type': purpose})
    db.commit()
    db.refresh(row)
    return {'id': row.id, 'consent_type': row.consent_type, 'status': row.status}


@app.get('/api/calls/{call_id}/processing-permissions')
def call_processing_permissions(call_id: int, current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin', 'compliance_admin')), db: Session = Depends(get_db)):
    call = _get_call_or_404(db, call_id, current_user.company_id)
    actions = ['record_audio', 'transcribe', 'live_assist']
    decisions = [
        can_process(
            db, action, tenant_id=call.company_id, call_id=call_id, country_code=call.jurisdiction_country,
            prospect_type=call.prospect_type, campaign_type=call.campaign_type, speaker_mode=call.speaker_mode,
        ).as_dict()
        for action in actions
    ]
    db.commit()
    return {'call_id': call_id, 'permissions': decisions}


@app.post('/api/calls/{call_id}/turns')
def add_turn(call_id: int, req: TurnRequest, current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin')), db: Session = Depends(get_db)):
    call = _get_call_or_404(db, call_id, current_user.company_id)
    # Sprint 1 (ADR-020): the legacy `consent_state != 'granted' -> 409` gate is gone.
    # Storing any turn's text is transcription processing, so it goes through the same
    # central resolver as every other sensitive action — no separate/legacy bypass.
    decision = can_process(
        db, 'transcribe', tenant_id=call.company_id, call_id=call.id, country_code=call.jurisdiction_country,
        prospect_type=call.prospect_type, campaign_type=call.campaign_type, speaker_mode=call.speaker_mode,
    )
    if decision.result != Decision.ALLOWED:
        db.commit()
        raise HTTPException(403, {'message': 'Transcription is not currently permitted for this call.', **decision.as_dict()})

    # Provider-Ready Gate (ADR-031): a webhook retry, reconnect, or duplicate final
    # transcript must not store the same real turn twice. Callers without a real
    # provider-stable id yet (manual/demo flows) get one synthesized from the call's
    # current turn count so nothing breaks before Sprint 2's real ASR pipeline exists.
    existing_turn_count = db.scalar(select(func.count()).select_from(Turn).where(Turn.call_id == call_id)) or 0
    turn_id = req.turn_id or synthesize_turn_id(call_id, 'transcribe', existing_turn_count)
    claimed, claim_row = claim_turn(
        db, company_id=call.company_id, call_id=call_id, action='transcribe', turn_id=turn_id,
        utterance_id=req.utterance_id, stream_id=req.stream_id, provider_event_id=req.provider_event_id,
    )
    if not claimed:
        db.commit()
        return {**claim_row.result_ref, 'duplicate': True, 'policy_decision': decision.as_dict()}

    style = analyze_language(req.text) if req.speaker == 'prospect' else {}
    turn_fields = req.model_dump(exclude={'turn_id', 'utterance_id', 'stream_id', 'provider_event_id'})
    turn = Turn(call_id=call_id, style_snapshot=style, lexical_complexity=style.get('complexity_score') if style else None, **turn_fields)
    db.add(turn)
    db.flush()
    if req.speaker == 'seller':
        # Bookkeeping only (last_seller_action/opening_completed/pitch_delivered) —
        # the phase machine itself only advances on prospect turns via
        # POST /api/copilot/suggest (see docs/DECISIONS.md ADR-027). Sprint 2
        # forward-compat (ADR-032): this is an MVP simplification, not permanent —
        # see apply_seller_turn()'s docstring.
        state_row = load_or_create_conversation_state_row(db, call)
        new_state, transition, _ = apply_turn(state_from_row(state_row), 'seller', req.text)
        apply_state_to_row(state_row, new_state)
        record_state_event(db, call, 'seller', transition, turn_index=new_state.turn_index)
    result_ref = {'id': turn.id, 'style_snapshot': style}
    record_result(claim_row, result_ref)
    db.commit()
    db.refresh(turn)
    return {**result_ref, 'policy_decision': decision.as_dict()}


@app.post('/api/copilot/suggest')
def copilot(req: SuggestRequest, request: Request, current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin')), db: Session = Depends(get_db)):
    decision = None
    state_row = None
    claim_row = None
    # Provider-Ready Gate (ADR-033): reuse a trace_id the caller already has for this
    # same utterance (e.g. from its own POST /calls/{id}/turns call) so both requests'
    # Suggestion/log rows correlate end-to-end; otherwise fall back to this request's
    # own middleware-assigned trace_id.
    trace_id = req.trace_id or getattr(request.state, 'trace_id', None)
    if req.call_id is not None:
        call = _get_call_or_404(db, req.call_id, current_user.company_id)
        decision = can_process(
            db, 'live_assist', tenant_id=call.company_id, call_id=call.id, country_code=call.jurisdiction_country,
            prospect_type=call.prospect_type, campaign_type=call.campaign_type, speaker_mode=call.speaker_mode,
        )
        if decision.result != Decision.ALLOWED:
            db.commit()
            raise HTTPException(403, {'message': 'Live copilot assistance is not currently permitted for this call.', **decision.as_dict()})

        # Sprint 1.5 (ADR-026): call-scoped suggestions advance the call's persisted
        # ConversationState instead of reclassifying the utterance in isolation, so
        # SalesBrain understands phase transitions across the whole running call.
        state_row = load_or_create_conversation_state_row(db, call)
        pre_state = state_from_row(state_row)

        # Provider-Ready Gate (ADR-031): the same real utterance must trigger exactly
        # one Copilot processing run, even across provider retries/reconnects.
        turn_id = req.turn_id or synthesize_turn_id(call.id, 'live_assist', pre_state.turn_index)
        claimed, claim_row = claim_turn(
            db, company_id=call.company_id, call_id=call.id, action='live_assist', turn_id=turn_id,
            utterance_id=req.utterance_id, stream_id=req.stream_id, provider_event_id=req.provider_event_id,
        )
        if not claimed:
            db.commit()
            return {**claim_row.result_ref, 'duplicate': True, 'policy_decision': decision.as_dict()}

        new_state, result, transition = suggest_with_state(pre_state, req.utterance, req.reaction_snapshot)
        apply_state_to_row(state_row, new_state)
        record_state_event(db, call, 'prospect', transition, turn_index=new_state.turn_index)
    else:
        # req.call_id is None: sandbox/practice mode. No real prospect is on the line,
        # so there is nothing to obtain consent for and no call to persist state
        # against; only tenant/role authorization applies (ADR-015). Still
        # tenant-scoped via company_id below so feedback on it can never cross tenants.
        # Not a real ASR turn, so no dedup claim applies here either.
        result = suggest(req.utterance, req.recent_context, req.reaction_snapshot, turn_index=req.turn_index)
    row = Suggestion(
        company_id=current_user.company_id,
        call_id=req.call_id,
        trace_id=trace_id,
        prospect_text=req.utterance,
        suggestion=result['suggestion'],
        strategy=result['strategy'],
        reason=result['reason'],
        do_not=result['do_not'],
        confidence=result['confidence'],
        latency_ms=result['latency_ms'],
        language_policy=result['language_policy'],
        reaction_snapshot=result['reaction_snapshot'],
    )
    db.add(row)
    db.flush()
    if claim_row is not None:
        record_result(claim_row, {'suggestion_id': row.id, **result})
    db.commit()
    db.refresh(row)
    out = {**result, 'suggestion_id': row.id, 'trace_id': trace_id}
    if decision is not None:
        out['policy_decision'] = decision.as_dict()
    if state_row is not None:
        out['conversation_state'] = conversation_state_dict(state_row)
    return out


@app.get('/api/calls/{call_id}/conversation-state')
def call_conversation_state(call_id: int, current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin', 'compliance_admin')), db: Session = Depends(get_db)):
    call = _get_call_or_404(db, call_id, current_user.company_id)
    state_row = load_or_create_conversation_state_row(db, call)
    db.commit()
    return conversation_state_dict(state_row)


@app.post('/api/suggestions/{suggestion_id}/feedback')
def suggestion_feedback(suggestion_id: int, req: SuggestionFeedbackRequest, current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin')), db: Session = Depends(get_db)):
    row = db.get(Suggestion, suggestion_id)
    if not row or row.company_id != current_user.company_id:
        raise HTTPException(404, 'Suggestion not found')
    row.rating = req.rating
    row.used = req.used
    db.commit()
    return {'ok': True, 'rating': row.rating, 'used': row.used}


@app.post('/api/suggestions/{suggestion_id}/render-ack')
def suggestion_render_ack(suggestion_id: int, req: SuggestionRenderAckRequest, current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin')), db: Session = Depends(get_db)):
    """Sprint 3A (docs/DECISIONS.md ADR-048), refined by ADR-051: the browser's
    Render-ACK, sent once a suggestion has actually been painted — this is the ONLY
    place `t_ui_rendered_at`/`wallclock_rsl_estimate_ms` are ever set; nothing in the
    streaming pipeline approximates them (see app/streaming/pipeline.py's
    `_process_turn()`). Looked up by `trace_id` (the correlation id shared by the
    Suggestion row, the live-push envelope, and the TurnLatencyTrace row for the
    same finalized turn) rather than by suggestion_id directly, since
    TurnLatencyTrace is keyed by trace_id/turn_id, not suggestion_id.

    ADR-051 adds two things on top of Sprint 3A's original wall-clock-only
    computation: `server_render_ack_latency_ms`, a robust monotonic upper bound
    computed ENTIRELY server-side (never crosses a clock boundary, deliberately
    includes this very HTTP request's own network/round-trip time); and, when the
    caller supplies `clock_sync_samples`, a persisted clock-offset/RTT/uncertainty
    estimate for later analysis (not yet used to correct anything).
    """
    row = db.get(Suggestion, suggestion_id)
    if not row or row.company_id != current_user.company_id:
        raise HTTPException(404, 'Suggestion not found')
    if req.call_id is not None and row.call_id is not None and req.call_id != row.call_id:
        raise HTTPException(400, 'call_id does not match this suggestion')

    trace_id = req.trace_id or row.trace_id
    trace_row = None
    if trace_id:
        trace_row = db.scalar(
            select(TurnLatencyTrace).where(TurnLatencyTrace.trace_id == trace_id, TurnLatencyTrace.company_id == current_user.company_id)
        )
    if trace_row is None and row.call_id is not None:
        # Fallback for a Suggestion whose trace_id didn't correlate to a trace row
        # (e.g. an older/sandbox suggestion) — best-effort: the most recent trace
        # for the same call. Never guessed across calls/tenants.
        trace_row = db.scalar(
            select(TurnLatencyTrace)
            .where(TurnLatencyTrace.call_id == row.call_id, TurnLatencyTrace.company_id == current_user.company_id)
            .order_by(TurnLatencyTrace.id.desc())
        )
    if trace_row is None:
        db.commit()
        return {'ok': True, 'wallclock_rsl_estimate_ms': None, 'note': 'no matching TurnLatencyTrace found — nothing to update'}

    now_monotonic = time.monotonic()
    trace_row.t_render_ack_received_at = datetime.utcnow()
    received_at = datetime.utcfromtimestamp(req.client_received_epoch_ms / 1000)
    rendered_at = datetime.utcfromtimestamp(req.client_rendered_epoch_ms / 1000)
    trace_row.t_browser_received_at = received_at
    trace_row.t_ui_rendered_at = rendered_at
    trace_row.client_render_latency_ms = req.client_rendered_perf_ms - req.client_received_perf_ms
    if trace_row.t_turn_end_detected_at is not None:
        # ADR-051 (renamed from Sprint 3A's real_rsl_ms): a cross-machine
        # WALL-CLOCK delta (docs/DATA_MODEL.md's evidence-level note, app/models.py's
        # TurnLatencyTrace docstring) — the only comparison possible between this
        # server and the browser without clock-sync correction, subject to
        # ordinary NTP clock skew. Hence "estimate", never treated as exact.
        trace_row.wallclock_rsl_estimate_ms = (rendered_at - trace_row.t_turn_end_detected_at).total_seconds() * 1000
    if (
        trace_row.t_turn_end_detected_monotonic is not None
        and trace_row.t_turn_end_detected_monotonic_runtime_id == RUNTIME_BOOT_ID
    ):
        # Runtime-id match confirms this monotonic value was captured by THIS
        # same process — the only condition under which comparing it against a
        # fresh time.monotonic() reading is valid (see app/models.py's docstring
        # and app/services/latency_trace.py's RUNTIME_BOOT_ID). A negative delta
        # despite a matching id would be a genuine anomaly (should not happen),
        # checked defensively and discarded rather than persisted.
        upper_bound = (now_monotonic - trace_row.t_turn_end_detected_monotonic) * 1000
        if upper_bound >= 0:
            trace_row.server_render_ack_latency_ms = upper_bound
    elif trace_row.t_turn_end_detected_monotonic is not None:
        # A process restart, host change, or (in a misconfigured multi-instance
        # deployment) a different instance entirely between turn-end and this
        # request — comparability cannot be verified, so nothing is computed
        # from it. Never fabricate a number from an unverifiable comparison.
        logger.warning(
            'render-ack: monotonic runtime mismatch — server_render_ack_latency_ms not computed',
            extra={'fields': {'trace_id': trace_row.trace_id}},
        )
    if req.clock_sync_samples:
        samples = [
            ClockSyncSample(
                t1_client_send_ms=s.t1_client_send_ms, t2_server_recv_ms=s.t2_server_recv_ms,
                t3_server_send_ms=s.t3_server_send_ms, t4_client_recv_ms=s.t4_client_recv_ms,
            )
            for s in req.clock_sync_samples
        ]
        estimate = estimate_clock_sync(samples)
        if estimate is not None:
            trace_row.clock_offset_estimate_ms = estimate['offset_ms']
            trace_row.clock_rtt_estimate_ms = estimate['rtt_ms']
            trace_row.clock_uncertainty_ms = estimate['uncertainty_ms']
    db.commit()
    return {
        'ok': True, 'trace_id': trace_row.trace_id,
        'wallclock_rsl_estimate_ms': trace_row.wallclock_rsl_estimate_ms,
        'server_render_ack_latency_ms': trace_row.server_render_ack_latency_ms,
        'client_render_latency_ms': trace_row.client_render_latency_ms,
        'clock_offset_estimate_ms': trace_row.clock_offset_estimate_ms,
        'clock_rtt_estimate_ms': trace_row.clock_rtt_estimate_ms,
        'clock_uncertainty_ms': trace_row.clock_uncertainty_ms,
        'is_synthetic': trace_row.is_synthetic, 'asr_provider': trace_row.asr_provider,
    }


@app.post('/api/calls/{call_id}/complete')
def complete_call(call_id: int, req: CompleteCallRequest, current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin')), db: Session = Depends(get_db)):
    call = _get_call_or_404(db, call_id, current_user.company_id)
    call.ended_at = datetime.utcnow()
    call.outcome = req.outcome
    call.meeting_booked = req.meeting_booked
    call.meeting_held = req.meeting_held
    call.qualified_opportunity = req.qualified_opportunity
    call.revenue = req.revenue
    db.commit()
    return {'ok': True}


@app.get('/api/calls/{call_id}/review')
def call_review(call_id: int, current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin')), db: Session = Depends(get_db)):
    call = _get_call_or_404(db, call_id, current_user.company_id)
    turns = db.scalars(select(Turn).where(Turn.call_id == call_id).order_by(Turn.started_ms)).all()
    return build_call_review(turns, call)


@app.get('/api/calls/{call_id}/reaction')
def call_reaction(call_id: int, current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin')), db: Session = Depends(get_db)):
    call = _get_call_or_404(db, call_id, current_user.company_id)
    turns = db.scalars(select(Turn).where(Turn.call_id == call_id, Turn.speaker == 'prospect').order_by(Turn.started_ms)).all()
    if len(turns) < 2:
        return {'baseline': {}, 'events': [], 'message': 'Need at least two prospect turns.'}
    baseline = build_baseline(turns)
    return {'baseline': baseline, 'events': [{'turn_id': t.id, **reaction_delta(baseline, t)} for t in turns[1:]]}


@app.get('/api/calls/recent/list')
def recent_calls(limit: int = 12, current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin')), db: Session = Depends(get_db)):
    company_id = current_user.company_id
    rows = db.scalars(select(Call).where(Call.company_id == company_id).order_by(Call.started_at.desc()).limit(limit)).all()
    return [{'id': c.id, 'seller': c.seller.name, 'prospect_company': c.prospect_company, 'prospect_role': c.prospect_role, 'started_at': c.started_at.isoformat(), 'outcome': c.outcome, 'meeting_booked': c.meeting_booked, 'meeting_held': c.meeting_held} for c in rows]


@app.get('/api/manager/overview')
def manager_overview(current_user: AuthContext = Depends(require_role('manager', 'tenant_admin')), db: Session = Depends(get_db)):
    company_id = current_user.company_id
    company = db.get(Company, company_id)
    decision = can_process(db, 'employee_analytics', tenant_id=company_id, country_code=company.country_code)
    log_audit(db, company_id, actor=current_user.email, action='employee_analytics.accessed', entity_type='company', entity_id=str(company_id), payload=decision.as_dict())
    db.commit()
    if decision.result != Decision.ALLOWED:
        raise HTTPException(403, {'message': 'Employee analytics is not currently permitted for this tenant/jurisdiction.', **decision.as_dict()})
    sellers = db.scalars(select(Seller).where(Seller.company_id == company_id)).all()
    all_calls = db.scalars(select(Call).where(Call.company_id == company_id)).all()
    return {
        'demo_data': settings.replica_demo_mode,
        'policy_decision': decision.as_dict(),
        'sellers': [manager_analysis(s, [c for c in all_calls if c.seller_id == s.id], all_calls) for s in sellers],
    }


# ---------------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------------

@app.get('/api/integrations')
def integrations_status(current_user: AuthContext = Depends(require_role('tenant_admin'))):
    return {
        'hubspot': hubspot.status(),
        'google_calendar': google_calendar.status(),
        'salesforce': salesforce.status(),
        'twilio': twilio_rest.status(),
        'openai_realtime': openai_status(),
    }


@app.post('/api/integrations/hubspot/sync')
async def sync_hubspot(current_user: AuthContext = Depends(require_role('tenant_admin'))):
    return {'meetings': await hubspot.recent_meetings(), 'deals': await hubspot.recent_deals()}


@app.post('/api/integrations/google-calendar/sync')
async def sync_google(current_user: AuthContext = Depends(require_role('tenant_admin'))):
    return await google_calendar.upcoming_events()


@app.get('/api/integrations/openai-realtime/blueprint')
def openai_realtime_blueprint(current_user: AuthContext = Depends(require_role('tenant_admin'))):
    return session_blueprint()


# ---------------------------------------------------------------------------
# Provider webhooks
# ---------------------------------------------------------------------------

@app.post('/webhooks/twilio/call-status')
async def twilio_call_status(request: Request, db: Session = Depends(get_db)):
    """Twilio's call-status-callback webhook (see docs/PROVIDER_REFERENCES.md).
    Authenticated ONLY by the X-Twilio-Signature header, verified via Twilio's own
    official RequestValidator (ADR-029/ADR-036) — Twilio cannot present one of our
    bearer tokens, so a missing/invalid/unresolvable signature fails closed with 403,
    never "process anyway".

    Two independent hardening layers on top of that (ADR-035):
    - Delivery idempotency: a byte-identical retried delivery (same CallSid + the
      same SequenceNumber, or the same CallStatus when Twilio doesn't send one) is
      recognized via `claim_webhook_delivery()` and never reprocessed.
    - Ordering: a delivery that IS new (never claimed before) can still describe a
      point in time OLDER than what's already been applied for this call — e.g. a
      delayed 'in-progress' arriving after 'completed'. `is_newer_event()` decides
      whether to apply it; a stale one is still durably recorded (the
      WebhookDelivery claim above already persisted it) and separately audit-logged
      as `.stale`, never silently dropped and never allowed to regress the call's
      materialized status.

    ADR-054: for a `<Number>`-level statusCallback (a PSTN child/dialed-out leg,
    as used for the outbound-sales-flow topology), Twilio's `CallSid` here is the
    CHILD leg's own SID, not the Parent/Media-Stream call's SID — `ParentCallSid`
    is the one that matches `Call.external_call_id`. Falling back to `CallSid`
    keeps this correct for a status callback that fires directly on the parent
    call (no `ParentCallSid` present, e.g. a plain `<Dial>`-level callback).
    `CallProviderStatus` ordering, however, still tracks the CHILD leg's own SID
    (`call_sid`) — its status progression is independent of the parent call's.

    Tech debt (documented, see final report): this endpoint must be `async def` to
    read the form body via Starlette, but the SQLAlchemy calls inside it are
    synchronous and briefly block the event loop — acceptable for Twilio's
    low-frequency status callbacks today, revisit if webhook volume grows.
    """
    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    signature = request.headers.get('x-twilio-signature')

    try:
        auth_token = get_secrets_provider().get('TWILIO_AUTH_TOKEN', settings.twilio_auth_token)
    except NotImplementedError as exc:
        logger.error('secrets backend error while resolving Twilio auth token', extra={'fields': {'error': str(exc)}})
        raise HTTPException(403, 'Webhook verification unavailable') from exc

    # Twilio signs the exact URL it called, protocol through the end of the query
    # string. Behind a TLS-terminating reverse proxy, request.url can come back as
    # http:// even though Twilio called https://, so the publicly configured base URL
    # is authoritative here, not request.url's scheme/host — but the PATH and QUERY
    # STRING still have to match exactly what Twilio actually requested (ADR-029/036).
    query = f'?{request.url.query}' if request.url.query else ''
    url = f'{settings.replica_public_base_url.rstrip("/")}{request.url.path}{query}'
    if not verify_twilio_signature(url, params, signature, auth_token):
        logger.warning('twilio webhook signature verification failed', extra={'fields': {'path': request.url.path}})
        raise HTTPException(403, 'Invalid webhook signature')

    call_sid = params.get('CallSid', '')
    call_status = params.get('CallStatus', 'unknown')
    if not call_sid:
        raise HTTPException(400, 'Missing CallSid')

    # ADR-035: CallSid alone is not a unique event identifier — one call legitimately
    # produces several distinct status events over its lifetime. SequenceNumber (when
    # Twilio sends it) is the authoritative per-event id; without it, fall back to
    # (CallSid, CallStatus) — a real limitation documented in ADR-035 rather than
    # silently assumed away.
    sequence_number = parse_sequence_number(params.get('SequenceNumber'))
    external_id = f'{call_sid}:{sequence_number}' if sequence_number is not None else f'{call_sid}:{call_status}'

    claimed = claim_webhook_delivery(
        db, provider='twilio', event_type='call-status', external_id=external_id,
        payload_summary={'call_status': call_status, 'sequence_number': sequence_number},
    )
    if not claimed:
        db.commit()
        return {'ok': True, 'duplicate': True}

    parent_call_sid = params.get('ParentCallSid') or None
    correlating_sid = parent_call_sid or call_sid
    call = db.scalar(select(Call).where(Call.external_call_id == correlating_sid))
    provider_status = get_or_create_provider_status(db, provider='twilio', external_call_id=call_sid, call_id=call.id if call else None)
    applied = is_newer_event(
        incoming_status=call_status, incoming_sequence=sequence_number,
        last_status=provider_status.last_status, last_sequence=provider_status.last_sequence_number,
    )
    if applied:
        provider_status.last_status = call_status
        provider_status.last_sequence_number = sequence_number
    if call is not None:
        log_audit(
            db, call.company_id, actor='twilio-webhook',
            action=f'call.status.{call_status}' if applied else f'call.status.{call_status}.stale',
            entity_type='call', entity_id=str(call.id),
            payload={'sequence_number': sequence_number, 'applied': applied},
        )
    db.commit()
    return {'ok': True, 'applied': applied}


# ---------------------------------------------------------------------------
# Browser-based outbound calling (Twilio Voice JS SDK, ADR-060)
# ---------------------------------------------------------------------------

_E164_RE = re.compile(r'\+[1-9]\d{6,14}')


@app.post('/api/voice/access-token')
def voice_access_token(
    call_id: int = Query(..., description='The REPLICA call this Access Token/ticket will be used for.'),
    current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin')),
    db: Session = Depends(get_db),
):
    """ADR-060: mints a short-lived Twilio Access Token so the seller's browser
    (Twilio Voice JS SDK, app/static/live.html) can register a `Device` and place
    an outbound call via `device.connect()` — the first real test's call path when
    the seller is calling from their own MacBook's browser rather than a phone.
    Requires the same auth as every other seller-facing endpoint; the token itself
    is scoped (via VoiceGrant) to only ever reach the one configured TwiML
    Application (`TWILIO_TWIML_APP_SID`), never an arbitrary Twilio resource.

    ADR-061: also returns `edge` (`TWILIO_EDGE`, e.g. `dublin`) alongside the
    token — the Voice SDK's `Device` takes the signaling edge as a constructor
    option, not something embeddable in the Access Token itself, so the
    browser needs it explicitly rather than hardcoding a second copy of
    `TWILIO_EDGE` in JavaScript.

    Red-team hardening (docs/DECISIONS.md ADR-063, item 7/8): a Twilio Access
    Token by itself grants the ability to REGISTER a Device and place SOME call
    through the configured TwiML App — it says nothing about which REPLICA
    call/tenant that's for, and `/webhooks/twilio/voice-outbound` (the ONLY
    place that ever turns a browser's `device.connect()` into TwiML) cannot see
    this bearer token at all (Twilio, not the browser, calls that webhook).
    `call_id` is therefore now REQUIRED here, tenant-checked exactly like every
    other call-scoped endpoint (`_get_call_or_404` — cross-tenant is a 404, never
    a distinguishable 403), and gated on the same consent/policy check
    (`can_process(..., 'live_assist', ...)`) `/api/calls/{id}/turns` already
    enforces — a real call must not even be able to fetch a working token if
    live-assist processing isn't currently permitted for it. On success, mints a
    short-lived, REPLICA-signed `voice_ticket` (`create_voice_call_ticket()`,
    app/auth/security.py) binding exactly this `call_id`/tenant/user — this,
    not the raw call_id, is what the browser must pass to `device.connect()`
    and what `/webhooks/twilio/voice-outbound` actually trusts (see that
    endpoint below); the browser never receives, and the webhook never accepts,
    any other Twilio account credential/secret.
    """
    call = _get_call_or_404(db, call_id, current_user.company_id)
    decision = can_process(
        db, 'live_assist', tenant_id=call.company_id, call_id=call.id, country_code=call.jurisdiction_country,
        prospect_type=call.prospect_type, campaign_type=call.campaign_type, speaker_mode=call.speaker_mode,
    )
    db.commit()
    if decision.result != Decision.ALLOWED:
        raise HTTPException(403, {'message': 'Live-Assist-Verarbeitung ist für diesen Call aktuell nicht zulässig.', **decision.as_dict()})
    try:
        result = twilio_rest.create_voice_access_token(identity=f'user-{current_user.user_id}')
    except ValueError as exc:
        raise HTTPException(500, str(exc)) from exc
    ticket = create_voice_call_ticket(call_id=call.id, company_id=call.company_id, user_id=current_user.user_id)
    return {
        'token': result['token'], 'identity': f'user-{current_user.user_id}', 'ttl_seconds': 3600,
        'region': result['region'], 'edge': result['edge'],
        'voice_ticket': ticket['ticket'], 'voice_ticket_ttl_seconds': ticket['ttl_seconds'],
    }


@app.post('/webhooks/twilio/voice-outbound')
async def twilio_voice_outbound(request: Request, db: Session = Depends(get_db)):
    """ADR-060: the Voice Request URL configured on the TwiML Application that
    `TWILIO_TWIML_APP_SID` points to — Twilio calls this the moment the browser's
    `device.connect({params: {...}})` places the outbound leg. Same
    authentication posture as `twilio_call_status()` above: X-Twilio-Signature is
    the ONLY authentication available here (fail-closed, ADR-029/036) — a bearer
    token cannot apply since Twilio itself is the caller.

    `To` (the Prospect test person's number, supplied by the browser at
    `device.connect()` time — see app/static/live.html) is validated against a
    plain E.164 shape and never logged: a rejection warning names the failure
    reason, never the rejected value, matching this project's existing token-
    rejection logging discipline (ADR-057).

    Red-team hardening (docs/DECISIONS.md ADR-063, item 8): `replica_call_id` is
    no longer accepted as a raw parameter from the browser at all — Twilio
    signing this REQUEST only proves the request genuinely came from Twilio, it
    proves nothing about which REPLICA tenant/call the BROWSER that called
    `device.connect()` was actually authorized for. A compromised/malicious
    browser client could otherwise set `replica_call_id` to any other tenant's
    call, causing this webhook to bind a real Media Stream (and this call's real
    audio) to that unrelated call/tenant's record — `_resolve_call_for_media_
    stream()` has no independent tenant check of its own, by design (it cannot:
    Twilio's media-stream WebSocket handshake is signature-authenticated only,
    same as this webhook, never bearer-token-authenticated). Instead, the
    browser sends `replica_voice_ticket` — the short-lived, REPLICA-signed
    ticket `/api/voice/access-token` minted only after independently verifying
    tenant ownership and consent/policy for a specific call_id
    (`create_voice_call_ticket()`). This webhook decodes and verifies THAT
    (`decode_voice_call_ticket()`) and uses ONLY the call_id/company_id it
    contains — there is no code path here that ever reads a call_id from
    anywhere else. A missing/invalid/expired/tampered ticket is rejected before
    any TwiML is ever generated (fail closed), and even a validly-issued ticket
    is re-checked against the CURRENT `Call`/consent state (not just what it was
    moments earlier when the ticket was minted) — closing the window where
    consent could have been withdrawn between minting and placing the call.

    Red-team hardening (docs/DECISIONS.md ADR-064, item 1/2): a ticket being
    genuinely valid does not by itself mean this specific request should
    place a NEW call — Twilio's own documented retry behavior means the exact
    same request (same ticket) can legitimately arrive twice for the SAME
    call attempt, which must succeed identically both times, while the same
    ticket being reused to start a SECOND, independent call attempt must fail
    closed. `app/services/voice_call_guard.VoiceTicketLedger` tells these
    apart using Twilio's own `CallSid` (one per real call-setup attempt,
    stable across that attempt's own retries). Independently,
    `VoiceCallConcurrencyLock` ensures at most one real call is ever in
    flight for a given `call_id` at a time, even across two DIFFERENT,
    individually valid tickets (e.g. two browser tabs) — released the moment
    that call's Media Stream ends (`/ws/twilio-media`, any exit path).

    The generated TwiML mirrors the already-confirmed, already-tested shape from
    docs/REAL_TEST_SETUP.md exactly: `<Start><Stream track="both_tracks">` first
    (so the Media Stream is running before anything is dialed), then
    `<Dial callerId="...">` to the Prospect — `callerId` is the operator's own
    Verified Caller ID from server-side config (`TWILIO_VERIFIED_CALLER_ID`),
    never something the browser could set, so a compromised/buggy browser client
    could never spoof an arbitrary caller ID.
    """
    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    signature = request.headers.get('x-twilio-signature')

    try:
        auth_token = get_secrets_provider().get('TWILIO_AUTH_TOKEN', settings.twilio_auth_token)
    except NotImplementedError as exc:
        logger.error('secrets backend error while resolving Twilio auth token', extra={'fields': {'error': str(exc)}})
        raise HTTPException(403, 'Webhook verification unavailable') from exc

    query = f'?{request.url.query}' if request.url.query else ''
    url = f'{settings.replica_public_base_url.rstrip("/")}{request.url.path}{query}'
    if not verify_twilio_signature(url, params, signature, auth_token):
        # Temporary red-team diagnostic (no secret values, only shape/metadata) for the
        # persistent real-call 403 investigation. Put directly in the message text
        # (not just `extra`) since this logger's handler doesn't render extra fields.
        # Remove once resolved.
        redacted_params = {
            key: (f'<{len(value)} chars, starts {value[:8]!r}>' if key == 'replica_voice_ticket' else value)
            for key, value in params.items()
        }
        try:
            our_expected_signature = compute_twilio_signature(url, params, auth_token) if auth_token else None
        except Exception as exc:  # noqa: BLE001 — diagnostic only, never let this hide the real 403
            our_expected_signature = f'<error computing: {exc!r}>'
        diag = {
            'path': request.url.path,
            'computed_url': url,
            'params': redacted_params,
            'received_signature': signature,
            'our_expected_signature': our_expected_signature,
            'auth_token_len': len(auth_token) if auth_token else 0,
            'auth_token_from_os_environ': os.environ.get('TWILIO_AUTH_TOKEN') is not None,
        }
        logger.warning('twilio voice webhook signature verification failed | diag=%s', json.dumps(diag))
        raise HTTPException(403, 'Invalid webhook signature')

    to_number = params.get('To', '').strip()
    if not _E164_RE.fullmatch(to_number):
        logger.warning('twilio voice webhook: rejected malformed To parameter', extra={'fields': {'path': request.url.path}})
        raise HTTPException(400, 'Invalid destination number')

    ticket_raw = params.get('replica_voice_ticket', '').strip()
    if not ticket_raw:
        logger.warning('twilio voice webhook: missing replica_voice_ticket parameter', extra={'fields': {'path': request.url.path}})
        raise HTTPException(400, 'Missing replica_voice_ticket parameter')
    try:
        ticket_payload = decode_voice_call_ticket(ticket_raw)
    except jwt.InvalidTokenError as exc:
        logger.warning('twilio voice webhook: rejected invalid/expired voice ticket', extra={'fields': {'exception': type(exc).__name__}})
        raise HTTPException(403, 'Invalid or expired voice ticket') from exc

    replica_call_id = ticket_payload['call_id']
    ticket_company_id = ticket_payload['company_id']
    call = db.get(Call, replica_call_id)
    if call is None or call.company_id != ticket_company_id:
        # Cannot happen for a ticket this server itself signed moments earlier
        # unless the Call was deleted/reassigned in between — fail closed rather
        # than trust a ticket whose claims no longer match reality.
        logger.warning('twilio voice webhook: ticket call_id no longer valid', extra={'fields': {'path': request.url.path}})
        raise HTTPException(403, 'Call is no longer valid for this ticket')
    decision = can_process(
        db, 'live_assist', tenant_id=call.company_id, call_id=call.id, country_code=call.jurisdiction_country,
        prospect_type=call.prospect_type, campaign_type=call.campaign_type, speaker_mode=call.speaker_mode,
    )
    db.commit()
    if decision.result != Decision.ALLOWED:
        logger.warning('twilio voice webhook: live-assist processing no longer permitted for this call', extra={'fields': {'call_id': call.id}})
        raise HTTPException(403, 'Processing is not currently permitted for this call')
    if not settings.twilio_verified_caller_id:
        raise HTTPException(500, 'TWILIO_VERIFIED_CALLER_ID is not configured')

    # Red-team hardening (docs/DECISIONS.md ADR-064, item 1/2): everything
    # above this point can be re-derived identically on a retry (it only
    # depends on the ticket and the current Call/consent state), so it is
    # safe to redo. From here on we are about to COMMIT to placing one real
    # call — this is where replay/concurrency must be checked, using
    # Twilio's own CallSid (allocated once per real call-setup attempt,
    # including its retries) to tell a legitimate retry of THIS attempt apart
    # from a second, independent one.
    call_sid = params.get('CallSid', '').strip()
    if not call_sid:
        logger.warning('twilio voice webhook: missing CallSid', extra={'fields': {'path': request.url.path}})
        raise HTTPException(400, 'Missing CallSid')
    ticket_jti = ticket_payload.get('jti')
    if not ticket_jti:
        # Every ticket minted by create_voice_call_ticket() carries a jti —
        # a ticket without one cannot be safely deduplicated and must not be
        # silently allowed through as if it could be.
        logger.warning('twilio voice webhook: voice ticket missing jti claim', extra={'fields': {'call_id': call.id}})
        raise HTTPException(403, 'Invalid voice ticket')

    verdict = get_voice_ticket_ledger().check_and_record(jti=ticket_jti, call_sid=call_sid)
    if verdict == 'conflict':
        logger.warning('twilio voice webhook: ticket reused for a different call attempt', extra={'fields': {'call_id': call.id}})
        raise HTTPException(403, 'This voice ticket has already been used for a different call attempt')
    if verdict == 'new':
        # A `'retry'` verdict means THIS SAME attempt already holds the lock
        # (acquired the first time this jti/CallSid pair was seen) — only a
        # genuinely new attempt needs to acquire it.
        if not get_voice_call_lock().try_acquire(call_id=call.id):
            logger.warning('twilio voice webhook: a real test call is already in progress for this call', extra={'fields': {'call_id': call.id}})
            raise HTTPException(409, 'A real test call is already in progress for this call')

    # xml_escape()'s default entity set is &/</> only — NOT quotes (that's
    # xml.sax.saxutils's own documented default). Fine for the <Number> element's
    # TEXT content below, but replica_call_id/callerId sit inside double-quoted
    # ATTRIBUTE values, where an unescaped `"` would let a value break out of its
    # attribute and inject arbitrary TwiML. Caught by this ADR's own test suite
    # (tests/test_voice_outbound.py) before this ever shipped.
    def xml_attr_escape(value: str) -> str:
        return xml_escape(value, {'"': '&quot;'})

    public_host = settings.replica_public_base_url.split('://', 1)[-1].rstrip('/')
    # Red-team hardening (docs/DECISIONS.md ADR-065): the ONLY release path for
    # the VoiceCallConcurrencyLock acquired just above was, until now,
    # /ws/twilio-media's own `finally` block — meaning a call that never even
    # reaches that WebSocket (busy/no-answer/failed dial, or the <Stream>
    # handshake itself never completing) left the lock held for its full
    # 30-minute safety-net TTL. Twilio's own `<Stream statusCallback>` fires
    # regardless of whether the Media Stream WebSocket ever connects at all —
    # `replica_call_id` travels in the URL's OWN query string (not something
    # Twilio's statusCallback payload carries), verified the same way every
    # other webhook here verifies its query string as part of the signed URL.
    stream_status_url = f'https://{public_host}/webhooks/twilio/stream-status?replica_call_id={replica_call_id}'
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Response>'
        '<Start>'
        f'<Stream url="wss://{public_host}/ws/twilio-media" track="both_tracks" '
        f'statusCallback="{xml_attr_escape(stream_status_url)}" statusCallbackMethod="POST">'
        f'<Parameter name="replica_call_id" value="{xml_attr_escape(str(replica_call_id))}" />'
        '</Stream>'
        '</Start>'
        f'<Dial callerId="{xml_attr_escape(settings.twilio_verified_caller_id)}">'
        f'<Number>{xml_escape(to_number)}</Number>'
        '</Dial>'
        '</Response>'
    )
    return Response(content=twiml, media_type='application/xml')


@app.post('/webhooks/twilio/stream-status')
async def twilio_stream_status(request: Request):
    """docs/DECISIONS.md ADR-065: releases `VoiceCallConcurrencyLock`
    (app/services/voice_call_guard.py) even when `/ws/twilio-media` is NEVER
    connected at all — e.g. the dialed number is busy/no-answer, or the
    `<Stream>` WebSocket handshake itself never completes. Without this, the
    only release path was that endpoint's own `finally` block, so a call
    that never got that far would hold the lock for its full 30-minute
    safety-net TTL — locking the operator out of retrying their own first
    real call for no real reason.

    Same authentication posture as every other Twilio webhook here:
    X-Twilio-Signature is the only authentication available, verified
    against the full request URL INCLUDING its query string (Twilio signs
    exactly the URL it was given) — `replica_call_id` travels there, in the
    URL `twilio_voice_outbound()` itself generated moments earlier, because
    Twilio's own `<Stream statusCallback>` payload has no notion of our
    custom `<Parameter>` values (those only ever reach the Media Stream
    WebSocket's own `start` event, never this callback).

    Idempotent by construction: `VoiceCallConcurrencyLock.release()` is a
    no-op for a call_id that is already released or was never held — this
    endpoint can safely be called multiple times (Twilio may retry it) or
    arrive after `/ws/twilio-media` already released the same lock itself.
    Only `stream-stopped`/`stream-error` release anything; `stream-started`
    is acknowledged and otherwise ignored (the lock is already held from
    the moment TwiML was returned — nothing to (re)acquire here).
    """
    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    signature = request.headers.get('x-twilio-signature')

    try:
        auth_token = get_secrets_provider().get('TWILIO_AUTH_TOKEN', settings.twilio_auth_token)
    except NotImplementedError as exc:
        logger.error('secrets backend error while resolving Twilio auth token', extra={'fields': {'error': str(exc)}})
        raise HTTPException(403, 'Webhook verification unavailable') from exc

    query = f'?{request.url.query}' if request.url.query else ''
    url = f'{settings.replica_public_base_url.rstrip("/")}{request.url.path}{query}'
    if not verify_twilio_signature(url, params, signature, auth_token):
        logger.warning('twilio stream-status webhook signature verification failed', extra={'fields': {'path': request.url.path}})
        raise HTTPException(403, 'Invalid webhook signature')

    stream_event = params.get('StreamEvent', '')
    try:
        replica_call_id = int(request.query_params.get('replica_call_id', ''))
    except (TypeError, ValueError):
        logger.warning('twilio stream-status webhook: missing/invalid replica_call_id', extra={'fields': {'stream_event': stream_event}})
        return {'ok': True}  # signature already proved this is genuinely from Twilio; just nothing to release

    if stream_event in ('stream-stopped', 'stream-error'):
        get_voice_call_lock().release(call_id=replica_call_id)
        logger.info('twilio stream-status: released voice-call concurrency lock', extra={
            'fields': {'call_id': replica_call_id, 'stream_event': stream_event},
        })
    return {'ok': True}


@app.get('/api/voice/preflight')
def voice_preflight(current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin'))):
    """ADR-062: status-only readiness check for the first real browser call.
    Reports presence/absence per required setting and, for the two
    non-secret ones (`TWILIO_REGION`/`TWILIO_EDGE`), their actual value —
    everything else is a boolean only, NEVER the underlying value, even
    though several of these (e.g. `TWILIO_ACCOUNT_SID`) are not acutely
    sensitive on their own; treated uniformly here rather than drawing that
    line per-field. `app/static/live.html` calls this before ever attempting
    to fetch an Access Token and refuses to start a real call if `ready` is
    false, showing exactly which checks failed (by label, never a value).
    """
    def present(value) -> bool:
        return bool(value)

    expected_origin = settings.replica_public_base_url.rstrip('/')
    origin_allowed = is_allowed_origin(
        expected_origin, env=settings.replica_env,
        allowed_origins=parse_allowed_origins(settings.replica_allowed_ws_origins),
    )
    checks = [
        {'key': 'twilio_account_sid', 'label': 'TWILIO_ACCOUNT_SID', 'ok': present(settings.twilio_account_sid)},
        {'key': 'twilio_api_key_sid', 'label': 'TWILIO_API_KEY_SID', 'ok': present(settings.twilio_api_key_sid)},
        {'key': 'twilio_api_key_secret', 'label': 'TWILIO_API_KEY_SECRET', 'ok': present(settings.twilio_api_key_secret)},
        {'key': 'twilio_twiml_app_sid', 'label': 'TWILIO_TWIML_APP_SID', 'ok': present(settings.twilio_twiml_app_sid)},
        {'key': 'twilio_verified_caller_id', 'label': 'TWILIO_VERIFIED_CALLER_ID', 'ok': present(settings.twilio_verified_caller_id)},
        {'key': 'twilio_region', 'label': 'TWILIO_REGION', 'ok': settings.twilio_region == 'ie1', 'value': settings.twilio_region},
        {'key': 'twilio_edge', 'label': 'TWILIO_EDGE', 'ok': settings.twilio_edge == 'dublin', 'value': settings.twilio_edge},
        {'key': 'deepgram_api_key', 'label': 'DEEPGRAM_API_KEY', 'ok': present(settings.deepgram_api_key)},
        {'key': 'replica_public_base_url', 'label': 'REPLICA_PUBLIC_BASE_URL', 'ok': present(settings.replica_public_base_url), 'value': settings.replica_public_base_url},
        {
            'key': 'ws_origin_allowlist', 'label': 'Erlaubte WS-Origin', 'ok': origin_allowed,
            'detail': 'lokal — Origin-Prüfung nicht aktiv' if settings.replica_env == 'local' else f'erwartet: {expected_origin}',
        },
    ]
    return {'ready': all(c['ok'] for c in checks), 'checks': checks}


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------

@app.post('/api/experiments')
def create_experiment(req: CreateExperimentRequest, current_user: AuthContext = Depends(require_role('tenant_admin', 'manager')), db: Session = Depends(get_db)):
    experiment = Experiment(company_id=current_user.company_id, key=req.key, hypothesis=req.hypothesis, primary_metric=req.primary_metric, variants=req.variants)
    db.add(experiment)
    db.commit()
    db.refresh(experiment)
    return {'id': experiment.id, 'key': experiment.key, 'status': experiment.status}


@app.post('/api/experiments/{experiment_id}/assign/{call_id}')
def assign_experiment(experiment_id: int, call_id: int, current_user: AuthContext = Depends(require_role('tenant_admin', 'manager')), db: Session = Depends(get_db)):
    call = _get_call_or_404(db, call_id, current_user.company_id)
    experiment = db.get(Experiment, experiment_id)
    if not experiment or experiment.company_id != current_user.company_id:
        raise HTTPException(404, 'Experiment not found')
    variant = assign_variant(call_id, experiment.key, list(experiment.variants.keys()))
    row = ExperimentAssignment(experiment_id=experiment.id, call_id=call.id, variant_key=variant)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {'assignment_id': row.id, 'variant': variant}


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------

@app.post('/api/policy/resolve')
def policy_resolve(req: PolicyResolveRequest, current_user: AuthContext = Depends(require_role('tenant_admin', 'compliance_admin', 'system_admin')), db: Session = Depends(get_db)):
    tenant_id = resolve_tenant_id(current_user, req.tenant_id)
    decision = can_process(
        db, req.action, tenant_id=tenant_id, call_id=req.call_id, country_code=req.country_code,
        prospect_type=req.prospect_type, campaign_type=req.campaign_type, speaker_mode=req.speaker_mode,
    )
    db.commit()
    return decision.as_dict()


@app.get('/api/policy/jurisdictions/{country}')
def policy_jurisdiction(country: str, current_user: AuthContext = Depends(get_current_user)):
    policy = resolve_country_policy(country)
    return {
        'country_code': policy.country_code,
        'is_default_fallback': policy.is_default_fallback,
        'human_copilot': policy.human_copilot,
        'recording': policy.recording,
        'autonomous_marketing_call': policy.autonomous_marketing_call,
        'ai_identity_disclosure': policy.ai_identity_disclosure,
        'employee_analytics': policy.employee_analytics,
        'emotion_inference_workplace': policy.emotion_inference_workplace,
        'network_intelligence': policy.network_intelligence,
    }


@app.post('/api/network-learning/opt-in')
def network_learning_opt_in(req: NetworkLearningOptRequest, current_user: AuthContext = Depends(require_role('tenant_admin', 'compliance_admin', 'system_admin')), db: Session = Depends(get_db)):
    tenant_id = resolve_tenant_id(current_user, req.company_id)
    company = set_network_learning_opt_in(db, company_id=tenant_id, opt_in=True, actor=current_user.email, reason=req.reason, evidence_ref=req.evidence_ref)
    return {'company_id': company.id, 'network_learning_opt_in': company.network_learning_opt_in}


@app.post('/api/network-learning/withdraw')
def network_learning_withdraw(req: NetworkLearningOptRequest, current_user: AuthContext = Depends(require_role('tenant_admin', 'compliance_admin', 'system_admin')), db: Session = Depends(get_db)):
    tenant_id = resolve_tenant_id(current_user, req.company_id)
    company = set_network_learning_opt_in(db, company_id=tenant_id, opt_in=False, actor=current_user.email, reason=req.reason, evidence_ref=req.evidence_ref)
    return {'company_id': company.id, 'network_learning_opt_in': company.network_learning_opt_in}


@app.get('/api/admin/feature-flags')
def list_feature_flags(company_id: int | None = Query(None), current_user: AuthContext = Depends(require_role('tenant_admin', 'compliance_admin', 'system_admin')), db: Session = Depends(get_db)):
    tenant_id = resolve_tenant_id(current_user, company_id)
    rows = db.scalars(select(TenantFeatureFlag).where(TenantFeatureFlag.company_id == tenant_id)).all()
    return [
        {
            'id': r.id, 'feature_key': r.feature_key, 'jurisdiction': r.jurisdiction, 'campaign_type': r.campaign_type,
            'enabled': r.enabled, 'updated_by': r.updated_by, 'reason': r.reason, 'updated_at': r.updated_at.isoformat(),
        }
        for r in rows
    ]


@app.post('/api/admin/feature-flags')
def upsert_feature_flag(req: FeatureFlagRequest, current_user: AuthContext = Depends(require_role('tenant_admin', 'compliance_admin', 'system_admin')), db: Session = Depends(get_db)):
    tenant_id = resolve_tenant_id(current_user, req.company_id)
    row = set_feature_flag(
        db, company_id=tenant_id, feature_key=req.feature_key, enabled=req.enabled,
        jurisdiction=req.jurisdiction, campaign_type=req.campaign_type, actor=current_user.email, reason=req.reason,
    )
    return {'id': row.id, 'feature_key': row.feature_key, 'enabled': row.enabled, 'jurisdiction': row.jurisdiction, 'campaign_type': row.campaign_type}


@app.post('/api/admin/compliance-signoffs')
def upsert_compliance_signoff(req: ComplianceReviewSignoffRequest, current_user: AuthContext = Depends(require_role('tenant_admin', 'compliance_admin', 'system_admin')), db: Session = Depends(get_db)):
    tenant_id = resolve_tenant_id(current_user, req.company_id)
    row = record_review_signoff(
        db, company_id=tenant_id, action=req.action, jurisdiction=req.jurisdiction,
        acknowledged_by=current_user.email, reason=req.reason, reference=req.reference,
    )
    return {'id': row.id, 'action': row.action, 'jurisdiction': row.jurisdiction, 'acknowledged_by': row.acknowledged_by}


@app.get('/api/audit/export')
def audit_export(limit: int = 100, company_id: int | None = Query(None), current_user: AuthContext = Depends(require_role('tenant_admin', 'compliance_admin', 'system_admin')), db: Session = Depends(get_db)):
    tenant_id = resolve_tenant_id(current_user, company_id)
    rows = db.scalars(
        select(AuditEvent).where(AuditEvent.company_id == tenant_id).order_by(AuditEvent.created_at.desc()).limit(min(limit, 500))
    ).all()
    return [
        {'id': r.id, 'actor': r.actor, 'action': r.action, 'entity_type': r.entity_type, 'entity_id': r.entity_id, 'payload': r.payload, 'created_at': r.created_at.isoformat()}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Streaming / demo helpers
# ---------------------------------------------------------------------------

def _resolve_call_for_media_stream(db: Session, session: MediaStreamSession) -> Call | None:
    """Prefer a `customParameters.replica_call_id` set via a `<Parameter>` on the
    `<Stream>` TwiML noun (unambiguous); fall back to matching Twilio's own
    `callSid` against `Call.external_call_id` (the same correlation the call-status
    webhook already uses, ADR-029). No match -> the stream cannot be attributed to a
    tenant/policy context and must be rejected, not processed under an unknown
    context (see docs/DECISIONS.md ADR-037)."""
    raw_call_id = session.custom_parameters.get('replica_call_id')
    if raw_call_id:
        try:
            call = db.get(Call, int(raw_call_id))
        except (TypeError, ValueError):
            call = None
        if call is not None:
            return call
    if session.call_sid:
        return db.scalar(select(Call).where(Call.external_call_id == session.call_sid))
    return None


@app.websocket('/ws/twilio-media')
async def twilio_media(websocket: WebSocket, asr_provider: ASRProvider = Depends(get_asr_provider)):
    """Twilio Media Streams WebSocket ingestion (Sprint 2, docs/DECISIONS.md
    ADR-037..041). Twilio cannot present a REPLICA bearer token here either, so this
    is authenticated the same way as the HTTP call-status webhook: X-Twilio-Signature,
    verified via the official RequestValidator (ADR-036), checked BEFORE
    `websocket.accept()` — an unauthenticated connection is refused at the handshake,
    never accepted and then dropped (ADR-037). Production connections must arrive
    over wss (`REPLICA_ENV=production` gates enforcement — see
    app/streaming/media_stream_security.py for why local/dev `ws://` remains allowed).
    """
    if settings.replica_env == 'production' and not is_secure_transport(websocket):
        logger.warning('rejecting insecure (non-wss) media stream connection in production')
        await websocket.close(code=1008)
        return
    try:
        auth_token = get_secrets_provider().get('TWILIO_AUTH_TOKEN', settings.twilio_auth_token)
    except NotImplementedError as exc:
        logger.error('secrets backend error while resolving Twilio auth token for media stream', extra={'fields': {'error': str(exc)}})
        await websocket.close(code=1008)
        return
    if not verify_media_stream_signature(websocket, auth_token=auth_token, public_base_url=settings.replica_public_base_url):
        logger.warning('twilio media stream signature verification failed')
        await websocket.close(code=1008)
        return

    await websocket.accept()
    correlation_session = MediaStreamSession()
    pipeline: MediaStreamPipeline | None = None
    # Red-team hardening (docs/DECISIONS.md ADR-064, item 2): tracked
    # separately from `pipeline` because the concurrency lock is acquired by
    # the voice-outbound webhook BEFORE this connection ever exists, and must
    # still be released even if pipeline construction itself fails below
    # (pipeline stays None in that case) — this is set once a Call is
    # resolved and released, unconditionally, in the `finally` block for
    # every exit path (clean stop, unclean disconnect, or any exception).
    resolved_call_id: int | None = None
    hub = get_live_suggestion_hub()
    is_real_asr = type(asr_provider).__name__ == 'DeepgramASRProvider'
    try:
        while True:
            message = json.loads(await websocket.receive_text())
            event = message.get('event')
            if event == 'connected':
                continue
            if event == 'start':
                correlation_session.consume_start(message)
                db = SessionLocal()
                try:
                    call = _resolve_call_for_media_stream(db, correlation_session)
                finally:
                    db.close()
                if call is None:
                    logger.warning('media stream: could not resolve a Call for this stream — closing', extra={'fields': {'call_sid': correlation_session.call_sid}})
                    await websocket.close(code=1008)
                    return
                resolved_call_id = call.id
                # Red-team hardening (docs/DECISIONS.md ADR-063, item 3): a phone
                # call connecting is NOT the same fact as REPLICA's own analysis
                # pipeline working — pushed as its own, independent signal the
                # instant the Media Stream itself attaches to this call, before
                # ASR/turn-detection/SalesBrain have done anything at all yet.
                await hub.push_status(call_id=call.id, company_id=call.company_id, status=PipelineStatus.MEDIA_STREAM_CONNECTED)
                if is_real_asr:
                    await hub.push_status(call_id=call.id, company_id=call.company_id, status=PipelineStatus.DEEPGRAM_CONNECTING)
                try:
                    pipeline = await MediaStreamPipeline.create(call_id=call.id, company_id=call.company_id, asr_provider=asr_provider)
                except Exception:
                    # Fail closed (item 3/4): pipeline construction failing (most
                    # likely a real ASR provider refusing to construct/connect)
                    # must never leave the seller believing analysis is running
                    # just because the phone call itself connected fine.
                    logger.exception('media stream: pipeline creation failed', extra={'fields': {'call_id': call.id}})
                    detail = PipelineStatus.DETAIL_DEEPGRAM_UNAVAILABLE if is_real_asr else PipelineStatus.DETAIL_PIPELINE_ERROR
                    await hub.push_status(call_id=call.id, company_id=call.company_id, status=PipelineStatus.DISRUPTED, detail=detail)
                    await hub.push_suggestion_stale(call_id=call.id, company_id=call.company_id, reason=detail)
                    await websocket.close(code=1011)
                    return
                pipeline.consume_start(message)
            elif event == 'media':
                if pipeline is None:
                    continue  # media before a resolved start is a protocol violation — ignore, don't crash
                await pipeline.consume_media(message)
            elif event == 'stop':
                if pipeline is not None:
                    await pipeline.consume_stop(message)
                break
    except WebSocketDisconnect:
        if pipeline is not None:
            await pipeline.consume_stop({'event': 'stop', 'sequenceNumber': None})
            # item 4/6: the Media Stream WebSocket dropping without Twilio ever
            # sending a clean 'stop' event first is itself an abnormal transport
            # event (docs/PROVIDER_REFERENCES.md documents 'stop' as the clean
            # end-of-stream signal) — surfaced so a genuinely still-connected
            # phone call never silently loses analysis without the seller's UI
            # reflecting it. A call that ends normally with a proper 'stop'
            # event never reaches this branch at all (see the `break` above).
            await hub.push_status(
                call_id=pipeline.call_id, company_id=pipeline.company_id, status=PipelineStatus.DISRUPTED,
                detail=PipelineStatus.DETAIL_MEDIA_STREAM_DISCONNECTED,
            )
            await hub.push_suggestion_stale(
                call_id=pipeline.call_id, company_id=pipeline.company_id, reason=PipelineStatus.DETAIL_MEDIA_STREAM_DISCONNECTED,
            )
    except Exception:
        # item 4: an unhandled exception anywhere in per-message pipeline
        # processing (consume_media/consume_stop) must never fail silently —
        # the Twilio side of the call may well still be connected and proceeding
        # fine, which is exactly the dangerous case: analysis has stopped but
        # nothing said so.
        logger.exception('media stream: unexpected pipeline failure', extra={'fields': {
            'call_id': pipeline.call_id if pipeline is not None else None,
        }})
        if pipeline is not None:
            await hub.push_status(
                call_id=pipeline.call_id, company_id=pipeline.company_id, status=PipelineStatus.DISRUPTED,
                detail=PipelineStatus.DETAIL_PIPELINE_ERROR,
            )
            await hub.push_suggestion_stale(
                call_id=pipeline.call_id, company_id=pipeline.company_id, reason=PipelineStatus.DETAIL_PIPELINE_ERROR,
            )
    finally:
        if pipeline is not None:
            await pipeline.close()
            logger.info('media stream diagnostics', extra={'fields': pipeline.diagnostics_summary()})
        # ADR-064 item 2: released unconditionally here (clean stop, unclean
        # disconnect, a pipeline-construction failure, or any other
        # exception) — this is the ONE place a call_id's concurrency lock is
        # ever released, so every exit path frees it exactly once, never
        # requiring its own copy of this line.
        if resolved_call_id is not None:
            get_voice_call_lock().release(call_id=resolved_call_id)


_LIVE_AUTH_TIMEOUT_S = 5.0


@app.websocket('/ws/live/{call_id}')
async def live_suggestions(websocket: WebSocket, call_id: int):
    """Sprint 3A (docs/DECISIONS.md ADR-048): live suggestion delivery to a
    connected seller's browser client (app/services/live_push.LiveSuggestionHub).

    Auth model: unlike Twilio's media stream (authenticated by X-Twilio-Signature
    before accept()), this is a real browser client — it cannot set a custom
    Authorization header on a WebSocket handshake, and putting a bearer token in
    the URL query string risks it being captured in proxy/CDN access logs. So
    instead of either, the connection is accepted first, and the FIRST message
    must be `{"type": "auth", "token": "<JWT>"}` within `_LIVE_AUTH_TIMEOUT_S` —
    functionally the same fail-closed posture as the media stream (an
    unauthenticated connection is never left open, never processed), just carried
    over the WS message channel instead of HTTP headers. Anything else (timeout, no
    token, invalid/expired token, disabled user, role not permitted, call not in
    this token's tenant) closes the connection immediately with code 1008.

    Tenant isolation mirrors `_get_call_or_404()`'s posture: a wrong-tenant call_id
    and a nonexistent call_id both just close the connection — never distinguishable
    from each other, so a client can never probe for another tenant's call_id.

    Fix-Sprint (ADR-051, hardened further per follow-up review): on top of the
    JWT auth above, the `Origin` header is checked against a configurable
    allowlist (`REPLICA_ALLOWED_WS_ORIGINS`) outside local dev — a valid JWT
    alone no longer suffices in production/staging if the connecting page isn't
    served from an allowed REPLICA origin. This check now runs BEFORE
    `websocket.accept()` — an ASGI WebSocket's headers (including `Origin`) are
    available from the connection scope immediately, before any accept/close
    call, exactly like the Twilio media stream's signature check above. A
    disallowed origin is rejected at the handshake (`websocket.close()` is valid
    pre-accept per ASGI — sending `websocket.close` instead of
    `websocket.accept` IS how a WebSocket handshake is rejected) and never
    receives an accepted connection at all, rather than being accepted and then
    immediately dropped. See app/services/ws_origin.py.
    """
    if not is_allowed_origin(
        websocket.headers.get('origin'), env=settings.replica_env,
        allowed_origins=parse_allowed_origins(settings.replica_allowed_ws_origins),
    ):
        logger.warning('live suggestions: origin not allowed', extra={'fields': {'origin': websocket.headers.get('origin')}})
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=_LIVE_AUTH_TIMEOUT_S)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await websocket.close(code=1008)
        return

    token = None
    auth_message: dict = {}
    try:
        auth_message = json.loads(raw)
        if auth_message.get('type') == 'auth':
            token = auth_message.get('token')
    except (json.JSONDecodeError, AttributeError):
        pass
    if not token:
        logger.warning('live suggestions: first message was not a valid auth frame')
        await websocket.close(code=1008)
        return

    # Fix (docs/DECISIONS.md ADR-057): unlike REST (where FastAPI's HTTPBearer
    # strips the "Bearer " scheme prefix from the Authorization header before
    # this code ever sees the token, see app/auth/dependencies.py), the token
    # here arrives as a plain JSON string value that the browser typed/pasted
    # into a form field — nothing strips an accidentally-included "Bearer "
    # prefix or incidental whitespace before it reaches us. Both are normalized
    # the same way a copy-paste mistake would produce one, so they don't fail
    # decode and get misreported as "expired" below.
    normalized_token = token.strip()
    if normalized_token[:7].lower() == 'bearer ':
        normalized_token = normalized_token[7:].strip()

    try:
        payload = decode_access_token(normalized_token)
    except jwt.InvalidTokenError as exc:
        # Fix (ADR-057): the previous blanket "invalid or expired token" message
        # made a malformed token (wrong prefix, stray whitespace, truncated
        # copy-paste) indistinguishable from a genuinely expired one. Logging the
        # real exception class plus non-secret token shape/fingerprint metadata
        # (never the token itself) lets this be diagnosed from server logs alone.
        logger.warning('live suggestions: token rejected', extra={'fields': {
            'exception': type(exc).__name__,
            'token_len': len(token),
            'token_segments': token.count('.') + 1,
            'token_sha256_prefix': hashlib.sha256(token.encode('utf-8')).hexdigest()[:12],
        }})
        await websocket.close(code=1008)
        return

    db = SessionLocal()
    try:
        user = db.get(User, int(payload['sub']))
        if user is None or not user.is_active:
            await websocket.close(code=1008)
            return
        if user.role not in ('seller', 'manager', 'tenant_admin', 'system_admin'):
            await websocket.close(code=1008)
            return
        call = db.get(Call, call_id)
        tenant_id = user.company_id
        if user.role == 'system_admin':
            tenant_id = auth_message.get('company_id') or (call.company_id if call else None)
        if call is None or tenant_id is None or call.company_id != tenant_id:
            await websocket.close(code=1008)
            return
    finally:
        db.close()

    hub = get_live_suggestion_hub()
    sub = hub.register(call_id=call_id, company_id=call.company_id, user_id=user.id, websocket=websocket)
    logger.info('live suggestion client connected', extra={'fields': {'call_id': call_id, 'user_id': user.id}})
    try:
        # Fix (docs/DECISIONS.md ADR-058, found by the real-browser E2E test
        # added in ADR-057): the client previously showed 'Bereit' as soon as
        # the raw WebSocket opened, before the server had actually validated
        # the auth frame — a rejected token could still flash the authenticated
        # state for the brief window between `open` and the server's 1008
        # close arriving. This explicit ack, sent only once every check above
        # has actually passed, lets the client wait for real confirmation
        # instead of assuming success from the absence of a close so far.
        await websocket.send_json({'type': 'auth_ok'})
        last = hub.last_payload(call_id)
        if last is not None:
            # Reconnect behavior (Sprint 3A requirement 1): a reconnecting client
            # is never left blank — it immediately gets the most recent suggestion
            # for this call. The client is expected to dedupe on `suggestion_id`
            # (it may already have rendered this exact one) — see app/static/live.html.
            await websocket.send_json({'type': 'sync', **last})
        # Red-team hardening (docs/DECISIONS.md ADR-063, item 3): resync the last
        # known pipeline/analysis status too, on the exact same reconnect logic —
        # a seller reconnecting mid-call must never fall back to a default
        # "wartet" display when the real state might already be "gestört".
        last_status = hub.last_status(call_id)
        if last_status is not None:
            await websocket.send_json({'type': 'pipeline_status', **last_status})
        while True:
            # This connection is push-only for SUGGESTION delivery (the
            # Render-ACK goes over a separate, reliable HTTP POST — see
            # POST /api/suggestions/{id}/render-ack — precisely so a momentarily
            # flaky WS connection can never silently swallow an ACK). The one
            # thing the client DOES send here is clock-sync ping/pong (ADR-051,
            # app/services/clock_sync.py) — anything else inbound is ignored;
            # reading in a loop otherwise only serves to detect a disconnect promptly.
            raw_in = await websocket.receive_text()
            try:
                inbound = json.loads(raw_in)
            except (json.JSONDecodeError, AttributeError):
                continue
            if inbound.get('type') == 'ping':
                server_recv_epoch_ms = time.time() * 1000
                await websocket.send_json({
                    'type': 'pong', 'seq': inbound.get('seq'),
                    't1_client_send_ms': inbound.get('t1_client_send_ms'),
                    't2_server_recv_ms': server_recv_epoch_ms,
                    't3_server_send_ms': time.time() * 1000,
                })
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(sub)
        logger.info('live suggestion client disconnected', extra={'fields': {'call_id': call_id, 'user_id': user.id}})


@app.get('/live/{call_id}')
def live_page(call_id: int):
    return FileResponse(BASE_DIR/'static'/'live.html')


@app.get('/api/demo/review-call')
def demo_review_call(current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin')), db: Session = Depends(get_db)):
    seller = db.scalar(select(Seller).where(Seller.name == 'Haydar', Seller.company_id == current_user.company_id))
    if not seller:
        raise HTTPException(404, 'Demo seller not found')
    call = db.scalar(select(Call).where(Call.seller_id == seller.id, Call.company_id == current_user.company_id).order_by(Call.started_at.desc()))
    if not call:
        raise HTTPException(404, 'Demo call not found')
    return {'call_id': call.id}
