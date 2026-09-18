from __future__ import annotations
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .migrate import run_migrations
from .models import (
    AuditEvent, Call, Company, ComplianceReviewSignoff, ConsentEvent, ConversationStateEvent, Experiment,
    ExperimentAssignment, Meeting, Seller, Suggestion, TenantFeatureFlag, Turn, User,
)
from .models import ConversationState as ConversationStateRow
from .schemas import (
    CompleteCallRequest, ComplianceReviewSignoffRequest, ConsentEventRequest, ConsentRequest, CreateCallRequest,
    CreateExperimentRequest, CreateUserRequest, FeatureFlagRequest, LoginRequest, NetworkLearningOptRequest,
    PolicyResolveRequest, SuggestRequest, SuggestionFeedbackRequest, TurnRequest,
)
from .secrets import get_secrets_provider
from .seed import seed_demo
from .services.conversation_state import ConversationState, apply_turn
from .services.copilot import suggest, suggest_with_state
from .services.experiments import assign_variant
from .services.language_sync import analyze_language
from .services.reaction_delta import build_baseline, reaction_delta
from .services.review import build_call_review, manager_analysis
from .services.turn_identity import claim_turn, record_result, synthesize_turn_id
from .integrations import google_calendar, hubspot, salesforce
from .integrations.openai_realtime import status as openai_status, session_blueprint
from .integrations.twilio_stream import TwilioStreamState
from .compliance.admin import record_review_signoff, set_feature_flag, set_network_learning_opt_in
from .compliance.audit import log_audit
from .compliance.jurisdiction_policy import resolve_country_policy
from .compliance.policy_engine import Decision, can_process
from .auth.dependencies import AuthContext, get_current_user, require_role, resolve_tenant_id
from .auth.security import create_access_token, hash_password, verify_password
from .logging_config import RequestContextMiddleware, configure_logging
from .webhooks.call_status import get_or_create_provider_status, is_newer_event, parse_sequence_number
from .webhooks.idempotency import claim_webhook_delivery
from .webhooks.security import verify_twilio_signature

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


def _load_or_create_conversation_state_row(db: Session, call: Call) -> ConversationStateRow:
    """Race-safe get-or-create (ADR-034): two concurrent first turns for the same
    call can both see no existing row and both attempt to create one — the loser
    hits `ConversationState.call_id`'s unique index. That is handled inside a
    SAVEPOINT (`db.begin_nested()`), the same pattern as claim_turn()/
    claim_webhook_delivery(), so only this insert attempt is undone rather than the
    request's whole pending transaction."""
    row = db.scalar(select(ConversationStateRow).where(ConversationStateRow.call_id == call.id))
    if row is not None:
        return row
    row = ConversationStateRow(call_id=call.id)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
        return row
    except IntegrityError:
        return db.scalar(select(ConversationStateRow).where(ConversationStateRow.call_id == call.id))


def _state_from_row(row: ConversationStateRow) -> ConversationState:
    return ConversationState(
        call_id=row.call_id, current_phase=row.current_phase, previous_phase=row.previous_phase,
        turn_index=row.turn_index, smalltalk_turns=row.smalltalk_turns,
        business_transition_started=row.business_transition_started, opening_completed=row.opening_completed,
        discovery_started=row.discovery_started, pitch_delivered=row.pitch_delivered,
        price_discussed=row.price_discussed, active_objection=row.active_objection,
        resolved_objections=list(row.resolved_objections or []),
        last_seller_action=row.last_seller_action, last_prospect_event=row.last_prospect_event,
    )


def _apply_state_to_row(row: ConversationStateRow, state: ConversationState) -> None:
    row.current_phase = state.current_phase
    row.previous_phase = state.previous_phase
    row.turn_index = state.turn_index
    row.smalltalk_turns = state.smalltalk_turns
    row.business_transition_started = state.business_transition_started
    row.opening_completed = state.opening_completed
    row.discovery_started = state.discovery_started
    row.pitch_delivered = state.pitch_delivered
    row.price_discussed = state.price_discussed
    row.active_objection = state.active_objection
    row.resolved_objections = state.resolved_objections
    row.last_seller_action = state.last_seller_action
    row.last_prospect_event = state.last_prospect_event


def _record_state_event(db: Session, call: Call, speaker: str, transition: dict, turn_index: int) -> None:
    """Provider-Ready Gate (ADR-030): append-only history row alongside the fast
    ConversationState snapshot. A single INSERT next to the state-row UPDATE already
    happening in the same request/transaction — this does not add a query or slow
    the pure state machine in app/services/conversation_state.py."""
    db.add(ConversationStateEvent(
        company_id=call.company_id, call_id=call.id, turn_index=turn_index, speaker=speaker,
        from_phase=transition.get('from_phase'), to_phase=transition.get('to_phase'),
        event_type=transition.get('event_type', 'unknown'), objection_type=transition.get('objection_type'),
        sales_action=transition.get('sales_action'), trigger=transition.get('trigger'),
    ))


def _conversation_state_dict(row: ConversationStateRow) -> dict:
    return {
        'call_id': row.call_id,
        'current_phase': row.current_phase,
        'previous_phase': row.previous_phase,
        'turn_index': row.turn_index,
        'smalltalk_turns': row.smalltalk_turns,
        'business_transition_started': row.business_transition_started,
        'opening_completed': row.opening_completed,
        'discovery_started': row.discovery_started,
        'pitch_delivered': row.pitch_delivered,
        'price_discussed': row.price_discussed,
        'active_objection': row.active_objection,
        'resolved_objections': row.resolved_objections,
        'last_seller_action': row.last_seller_action,
        'last_prospect_event': row.last_prospect_event,
        'updated_at': row.updated_at.isoformat(),
    }


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
        state_row = _load_or_create_conversation_state_row(db, call)
        new_state, transition, _ = apply_turn(_state_from_row(state_row), 'seller', req.text)
        _apply_state_to_row(state_row, new_state)
        _record_state_event(db, call, 'seller', transition, turn_index=new_state.turn_index)
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
        state_row = _load_or_create_conversation_state_row(db, call)
        pre_state = _state_from_row(state_row)

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
        _apply_state_to_row(state_row, new_state)
        _record_state_event(db, call, 'prospect', transition, turn_index=new_state.turn_index)
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
        out['conversation_state'] = _conversation_state_dict(state_row)
    return out


@app.get('/api/calls/{call_id}/conversation-state')
def call_conversation_state(call_id: int, current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin', 'compliance_admin')), db: Session = Depends(get_db)):
    call = _get_call_or_404(db, call_id, current_user.company_id)
    state_row = _load_or_create_conversation_state_row(db, call)
    db.commit()
    return _conversation_state_dict(state_row)


@app.post('/api/suggestions/{suggestion_id}/feedback')
def suggestion_feedback(suggestion_id: int, req: SuggestionFeedbackRequest, current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin')), db: Session = Depends(get_db)):
    row = db.get(Suggestion, suggestion_id)
    if not row or row.company_id != current_user.company_id:
        raise HTTPException(404, 'Suggestion not found')
    row.rating = req.rating
    row.used = req.used
    db.commit()
    return {'ok': True, 'rating': row.rating, 'used': row.used}


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
        'twilio': {'provider': 'twilio', 'connected': bool(settings.twilio_account_sid and settings.twilio_auth_token)},
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

    call = db.scalar(select(Call).where(Call.external_call_id == call_sid))
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

@app.websocket('/ws/twilio-media')
async def twilio_media(ws: WebSocket):
    # Twilio Media Streams authenticate via request/signature verification (see
    # docs/INTEGRATIONS.md), not a REPLICA user bearer token — no user JWT applies here.
    await ws.accept()
    state = TwilioStreamState()
    try:
        while True:
            message = json.loads(await ws.receive_text())
            state.consume(message)
            if message.get('event') == 'stop':
                break
    except WebSocketDisconnect:
        pass


@app.get('/api/demo/review-call')
def demo_review_call(current_user: AuthContext = Depends(require_role('seller', 'manager', 'tenant_admin')), db: Session = Depends(get_db)):
    seller = db.scalar(select(Seller).where(Seller.name == 'Haydar', Seller.company_id == current_user.company_id))
    if not seller:
        raise HTTPException(404, 'Demo seller not found')
    call = db.scalar(select(Call).where(Call.seller_id == seller.id, Call.company_id == current_user.company_id).order_by(Call.started_at.desc()))
    if not call:
        raise HTTPException(404, 'Demo call not found')
    return {'call_id': call.id}
