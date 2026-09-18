from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import Base, engine, get_db
from .models import AuditEvent, Call, Company, ComplianceReviewSignoff, ConsentEvent, Experiment, ExperimentAssignment, Meeting, Seller, Suggestion, TenantFeatureFlag, Turn
from .schemas import (
    CompleteCallRequest, ComplianceReviewSignoffRequest, ConsentEventRequest, ConsentRequest, CreateCallRequest,
    CreateExperimentRequest, FeatureFlagRequest, NetworkLearningOptRequest, PolicyResolveRequest, SuggestRequest,
    SuggestionFeedbackRequest, TurnRequest,
)
from .seed import seed_demo
from .services.copilot import suggest
from .services.experiments import assign_variant
from .services.language_sync import analyze_language
from .services.reaction_delta import build_baseline, reaction_delta
from .services.review import build_call_review, manager_analysis
from .integrations import google_calendar, hubspot, salesforce
from .integrations.openai_realtime import status as openai_status, session_blueprint
from .integrations.twilio_stream import TwilioStreamState
from .compliance.admin import record_review_signoff, set_feature_flag, set_network_learning_opt_in
from .compliance.audit import log_audit
from .compliance.jurisdiction_policy import resolve_country_policy
from .compliance.policy_engine import Decision, can_process

BASE_DIR = Path(__file__).resolve().parent
settings = get_settings()
app = FastAPI(title='REPLICA MVP', version='0.3.0', description='Adaptive Sales Intelligence pilot')
app.mount('/static', StaticFiles(directory=BASE_DIR/'static'), name='static')


@app.on_event('startup')
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    if settings.replica_demo_mode:
        seed_demo()


@app.get('/')
def root():
    return FileResponse(BASE_DIR/'static'/'index.html')


@app.get('/api/health')
def health():
    return {'status': 'ok', 'version': '0.3.0', 'env': settings.replica_env, 'demo_mode': settings.replica_demo_mode}


def _demo_company_id(db: Session) -> int:
    company = db.scalar(select(Company).order_by(Company.id))
    if not company:
        raise HTTPException(404, 'No company found')
    return company.id


@app.get('/api/dashboard')
def dashboard(db: Session = Depends(get_db)):
    company_id = _demo_company_id(db)
    calls = db.scalars(select(Call).where(Call.company_id == company_id)).all()
    sellers = db.scalars(select(Seller).where(Seller.company_id == company_id)).all()
    meetings = db.scalars(select(Meeting).where(Meeting.company_id == company_id).order_by(Meeting.starts_at)).all()
    suggestions = db.scalars(select(Suggestion)).all()
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
def create_call(req: CreateCallRequest, db: Session = Depends(get_db)):
    seller = db.get(Seller, req.seller_id)
    if not seller:
        raise HTTPException(404, 'Seller not found')
    call = Call(company_id=seller.company_id, seller_id=seller.id, prospect_company=req.prospect_company, prospect_role=req.prospect_role, segment=req.segment, offer_key=req.offer_key, campaign_key=req.campaign_key)
    db.add(call); db.flush()
    db.add(AuditEvent(company_id=seller.company_id, actor='seller', action='call.created', entity_type='call', entity_id=str(call.id)))
    db.commit(); db.refresh(call)
    return {'id': call.id, 'consent_state': call.consent_state}


@app.post('/api/calls/{call_id}/consent')
def set_consent(call_id: int, req: ConsentRequest, db: Session = Depends(get_db)):
    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(404, 'Call not found')
    call.consent_state = req.state
    call.consented_at = datetime.utcnow() if req.state == 'granted' else None
    # Purpose-bound ledger entry alongside the legacy single-field gate above, so the
    # new compliance layer has a real audit trail from day one (see docs/DECISIONS.md ADR-007).
    event_status = {'granted': 'granted', 'declined': 'denied', 'withdrawn': 'withdrawn'}[req.state]
    db.add(ConsentEvent(
        company_id=call.company_id, call_id=call.id, consent_type='live_copilot_processing',
        purpose='Live-Copilot-Verarbeitung während des Calls', status=event_status, collection_method='api',
        withdrawn_at=datetime.utcnow() if event_status == 'withdrawn' else None,
    ))
    db.add(AuditEvent(company_id=call.company_id, actor='seller', action=f'consent.{req.state}', entity_type='call', entity_id=str(call.id)))
    db.commit()
    return {'ok': True, 'consent_state': call.consent_state}


@app.post('/api/calls/{call_id}/consents')
def create_consent_event(call_id: int, req: ConsentEventRequest, db: Session = Depends(get_db)):
    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(404, 'Call not found')
    row = ConsentEvent(
        company_id=call.company_id, call_id=call_id, prospect_reference=req.prospect_reference,
        consent_type=req.consent_type, purpose=req.purpose or req.consent_type, jurisdiction=req.jurisdiction,
        consent_text_version=req.consent_text_version, status=req.status, collection_method=req.collection_method,
        evidence_ref=req.evidence_ref, withdrawn_at=datetime.utcnow() if req.status == 'withdrawn' else None,
    )
    db.add(row)
    log_audit(db, call.company_id, actor='seller', action=f'consent.{req.status}', entity_type='consent_event', entity_id=req.consent_type, payload={'call_id': call_id, 'consent_type': req.consent_type, 'status': req.status})
    db.commit(); db.refresh(row)
    return {'id': row.id, 'consent_type': row.consent_type, 'status': row.status, 'captured_at': row.captured_at.isoformat()}


@app.post('/api/calls/{call_id}/consents/{purpose}/withdraw')
def withdraw_consent_event(call_id: int, purpose: str, db: Session = Depends(get_db)):
    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(404, 'Call not found')
    row = ConsentEvent(company_id=call.company_id, call_id=call_id, consent_type=purpose, purpose=purpose, status='withdrawn', collection_method='api', withdrawn_at=datetime.utcnow())
    db.add(row)
    log_audit(db, call.company_id, actor='seller', action='consent.withdrawn', entity_type='consent_event', entity_id=purpose, payload={'call_id': call_id, 'consent_type': purpose})
    db.commit(); db.refresh(row)
    return {'id': row.id, 'consent_type': row.consent_type, 'status': row.status}


@app.get('/api/calls/{call_id}/processing-permissions')
def call_processing_permissions(call_id: int, db: Session = Depends(get_db)):
    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(404, 'Call not found')
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
def add_turn(call_id: int, req: TurnRequest, db: Session = Depends(get_db)):
    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(404, 'Call not found')
    if call.consent_state != 'granted':
        raise HTTPException(409, 'Consent gate: call analysis is disabled until consent is granted')
    style = analyze_language(req.text) if req.speaker == 'prospect' else {}
    turn = Turn(call_id=call_id, style_snapshot=style, lexical_complexity=style.get('complexity_score') if style else None, **req.model_dump())
    db.add(turn); db.commit(); db.refresh(turn)
    return {'id': turn.id, 'style_snapshot': style}


@app.post('/api/copilot/suggest')
def copilot(req: SuggestRequest, db: Session = Depends(get_db)):
    if req.call_id is not None:
        call = db.get(Call, req.call_id)
        if not call:
            raise HTTPException(404, 'Call not found')
        if call.consent_state != 'granted':
            raise HTTPException(409, 'Consent gate: live analysis disabled for this call')
    result = suggest(req.utterance, req.recent_context, req.reaction_snapshot)
    row = Suggestion(
        call_id=req.call_id,
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
    db.add(row); db.commit(); db.refresh(row)
    return {**result, 'suggestion_id': row.id}


@app.post('/api/suggestions/{suggestion_id}/feedback')
def suggestion_feedback(suggestion_id: int, req: SuggestionFeedbackRequest, db: Session = Depends(get_db)):
    row = db.get(Suggestion, suggestion_id)
    if not row:
        raise HTTPException(404, 'Suggestion not found')
    row.rating = req.rating; row.used = req.used
    db.commit()
    return {'ok': True, 'rating': row.rating, 'used': row.used}


@app.post('/api/calls/{call_id}/complete')
def complete_call(call_id: int, req: CompleteCallRequest, db: Session = Depends(get_db)):
    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(404, 'Call not found')
    call.ended_at = datetime.utcnow(); call.outcome = req.outcome; call.meeting_booked = req.meeting_booked; call.meeting_held = req.meeting_held; call.qualified_opportunity = req.qualified_opportunity; call.revenue = req.revenue
    db.commit()
    return {'ok': True}


@app.get('/api/calls/{call_id}/review')
def call_review(call_id: int, db: Session = Depends(get_db)):
    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(404, 'Call not found')
    turns = db.scalars(select(Turn).where(Turn.call_id == call_id).order_by(Turn.started_ms)).all()
    return build_call_review(turns, call)


@app.get('/api/calls/{call_id}/reaction')
def call_reaction(call_id: int, db: Session = Depends(get_db)):
    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(404, 'Call not found')
    turns = db.scalars(select(Turn).where(Turn.call_id == call_id, Turn.speaker == 'prospect').order_by(Turn.started_ms)).all()
    if len(turns) < 2:
        return {'baseline': {}, 'events': [], 'message': 'Need at least two prospect turns.'}
    baseline = build_baseline(turns)
    return {'baseline': baseline, 'events': [{'turn_id': t.id, **reaction_delta(baseline, t)} for t in turns[1:]]}


@app.get('/api/calls/recent/list')
def recent_calls(limit: int = 12, db: Session = Depends(get_db)):
    company_id = _demo_company_id(db)
    rows = db.scalars(select(Call).where(Call.company_id == company_id).order_by(Call.started_at.desc()).limit(limit)).all()
    return [{'id': c.id, 'seller': c.seller.name, 'prospect_company': c.prospect_company, 'prospect_role': c.prospect_role, 'started_at': c.started_at.isoformat(), 'outcome': c.outcome, 'meeting_booked': c.meeting_booked, 'meeting_held': c.meeting_held} for c in rows]


@app.get('/api/manager/overview')
def manager_overview(db: Session = Depends(get_db)):
    company_id = _demo_company_id(db)
    company = db.get(Company, company_id)
    decision = can_process(db, 'employee_analytics', tenant_id=company_id, country_code=company.country_code)
    log_audit(db, company_id, actor='manager', action='employee_analytics.accessed', entity_type='company', entity_id=str(company_id), payload=decision.as_dict())
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


@app.get('/api/integrations')
def integrations_status():
    return {
        'hubspot': hubspot.status(),
        'google_calendar': google_calendar.status(),
        'salesforce': salesforce.status(),
        'twilio': {'provider': 'twilio', 'connected': bool(settings.twilio_account_sid and settings.twilio_auth_token)},
        'openai_realtime': openai_status(),
    }


@app.post('/api/integrations/hubspot/sync')
async def sync_hubspot():
    return {'meetings': await hubspot.recent_meetings(), 'deals': await hubspot.recent_deals()}


@app.post('/api/integrations/google-calendar/sync')
async def sync_google():
    return await google_calendar.upcoming_events()


@app.get('/api/integrations/openai-realtime/blueprint')
def openai_realtime_blueprint():
    return session_blueprint()


@app.post('/api/experiments')
def create_experiment(req: CreateExperimentRequest, db: Session = Depends(get_db)):
    company_id = _demo_company_id(db)
    experiment = Experiment(company_id=company_id, key=req.key, hypothesis=req.hypothesis, primary_metric=req.primary_metric, variants=req.variants)
    db.add(experiment); db.commit(); db.refresh(experiment)
    return {'id': experiment.id, 'key': experiment.key, 'status': experiment.status}


@app.post('/api/experiments/{experiment_id}/assign/{call_id}')
def assign_experiment(experiment_id: int, call_id: int, db: Session = Depends(get_db)):
    experiment = db.get(Experiment, experiment_id); call = db.get(Call, call_id)
    if not experiment or not call:
        raise HTTPException(404, 'Experiment or call not found')
    variant = assign_variant(call_id, experiment.key, list(experiment.variants.keys()))
    row = ExperimentAssignment(experiment_id=experiment.id, call_id=call.id, variant_key=variant)
    db.add(row); db.commit(); db.refresh(row)
    return {'assignment_id': row.id, 'variant': variant}


@app.post('/api/policy/resolve')
def policy_resolve(req: PolicyResolveRequest, db: Session = Depends(get_db)):
    tenant_id = req.tenant_id if req.tenant_id is not None else _demo_company_id(db)
    decision = can_process(
        db, req.action, tenant_id=tenant_id, call_id=req.call_id, country_code=req.country_code,
        prospect_type=req.prospect_type, campaign_type=req.campaign_type, speaker_mode=req.speaker_mode,
    )
    db.commit()
    return decision.as_dict()


@app.get('/api/policy/jurisdictions/{country}')
def policy_jurisdiction(country: str):
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
def network_learning_opt_in(req: NetworkLearningOptRequest, db: Session = Depends(get_db)):
    company_id = _demo_company_id(db)
    company = set_network_learning_opt_in(db, company_id=company_id, opt_in=True, reason=req.reason, evidence_ref=req.evidence_ref)
    return {'company_id': company.id, 'network_learning_opt_in': company.network_learning_opt_in}


@app.post('/api/network-learning/withdraw')
def network_learning_withdraw(req: NetworkLearningOptRequest, db: Session = Depends(get_db)):
    company_id = _demo_company_id(db)
    company = set_network_learning_opt_in(db, company_id=company_id, opt_in=False, reason=req.reason, evidence_ref=req.evidence_ref)
    return {'company_id': company.id, 'network_learning_opt_in': company.network_learning_opt_in}


@app.get('/api/admin/feature-flags')
def list_feature_flags(db: Session = Depends(get_db)):
    company_id = _demo_company_id(db)
    rows = db.scalars(select(TenantFeatureFlag).where(TenantFeatureFlag.company_id == company_id)).all()
    return [
        {
            'id': r.id, 'feature_key': r.feature_key, 'jurisdiction': r.jurisdiction, 'campaign_type': r.campaign_type,
            'enabled': r.enabled, 'updated_by': r.updated_by, 'reason': r.reason, 'updated_at': r.updated_at.isoformat(),
        }
        for r in rows
    ]


@app.post('/api/admin/feature-flags')
def upsert_feature_flag(req: FeatureFlagRequest, db: Session = Depends(get_db)):
    company_id = _demo_company_id(db)
    row = set_feature_flag(
        db, company_id=company_id, feature_key=req.feature_key, enabled=req.enabled,
        jurisdiction=req.jurisdiction, campaign_type=req.campaign_type, actor=req.actor, reason=req.reason,
    )
    return {'id': row.id, 'feature_key': row.feature_key, 'enabled': row.enabled, 'jurisdiction': row.jurisdiction, 'campaign_type': row.campaign_type}


@app.post('/api/admin/compliance-signoffs')
def upsert_compliance_signoff(req: ComplianceReviewSignoffRequest, db: Session = Depends(get_db)):
    company_id = _demo_company_id(db)
    row = record_review_signoff(
        db, company_id=company_id, action=req.action, jurisdiction=req.jurisdiction,
        acknowledged_by=req.acknowledged_by, reason=req.reason, reference=req.reference,
    )
    return {'id': row.id, 'action': row.action, 'jurisdiction': row.jurisdiction, 'acknowledged_by': row.acknowledged_by}


@app.get('/api/audit/export')
def audit_export(limit: int = 100, db: Session = Depends(get_db)):
    company_id = _demo_company_id(db)
    rows = db.scalars(
        select(AuditEvent).where(AuditEvent.company_id == company_id).order_by(AuditEvent.created_at.desc()).limit(min(limit, 500))
    ).all()
    return [
        {'id': r.id, 'actor': r.actor, 'action': r.action, 'entity_type': r.entity_type, 'entity_id': r.entity_id, 'payload': r.payload, 'created_at': r.created_at.isoformat()}
        for r in rows
    ]


@app.websocket('/ws/twilio-media')
async def twilio_media(ws: WebSocket):
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
def demo_review_call(db: Session = Depends(get_db)):
    seller = db.scalar(select(Seller).where(Seller.name == 'Haydar'))
    if not seller:
        raise HTTPException(404, 'Demo seller not found')
    call = db.scalar(select(Call).where(Call.seller_id == seller.id).order_by(Call.started_at.desc()))
    return {'call_id': call.id}
