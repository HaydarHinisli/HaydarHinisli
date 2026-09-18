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
from .models import AuditEvent, Call, Company, Experiment, ExperimentAssignment, Meeting, Seller, Suggestion, Turn
from .schemas import CompleteCallRequest, ConsentRequest, CreateCallRequest, CreateExperimentRequest, SuggestRequest, SuggestionFeedbackRequest, TurnRequest
from .seed import seed_demo
from .services.copilot import suggest
from .services.experiments import assign_variant
from .services.language_sync import analyze_language
from .services.reaction_delta import build_baseline, reaction_delta
from .services.review import build_call_review, manager_analysis
from .integrations import google_calendar, hubspot, salesforce
from .integrations.openai_realtime import status as openai_status, session_blueprint
from .integrations.twilio_stream import TwilioStreamState

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
    db.add(AuditEvent(company_id=call.company_id, actor='seller', action=f'consent.{req.state}', entity_type='call', entity_id=str(call.id)))
    db.commit()
    return {'ok': True, 'consent_state': call.consent_state}


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
    sellers = db.scalars(select(Seller).where(Seller.company_id == company_id)).all()
    all_calls = db.scalars(select(Call).where(Call.company_id == company_id)).all()
    return {'demo_data': settings.replica_demo_mode, 'sellers': [manager_analysis(s, [c for c in all_calls if c.seller_id == s.id], all_calls) for s in sellers]}


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
