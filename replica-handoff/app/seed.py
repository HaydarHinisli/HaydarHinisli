from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy import select
from .auth.security import hash_password
from .db import SessionLocal
from .models import Company, ComplianceReviewSignoff, Seller, Call, Turn, Meeting, Deal, Experiment, User

# Local/demo credential only — never used outside REPLICA_DEMO_MODE. Production
# tenants are created via POST /api/admin/users with a real, unique password.
DEMO_PASSWORD = 'replica-demo-2026'


def seed_demo() -> None:
    db = SessionLocal()
    try:
        if db.scalar(select(Company).limit(1)):
            return
        company = Company(name='REPLICA Pilot GmbH', country_code='DE', network_learning_opt_in=False)
        db.add(company)
        db.flush()
        # Sprint 0: DE employee_analytics tier is "high_risk_controls" (requires a
        # recorded compliance review signoff, see app/compliance/policy_engine.py).
        # The demo pilot tenant acknowledges this once here so /api/manager/overview
        # keeps working out of the box; a real tenant must record this via
        # POST /api/admin/compliance-signoffs after an actual review.
        db.add(ComplianceReviewSignoff(
            company_id=company.id,
            action='employee_analytics',
            jurisdiction='DE',
            acknowledged_by='demo-admin@replica-pilot.example',
            reason=(
                'Pilot tenant acknowledges GLOBAL_PRODUCT_COMPLIANCE_SPEC.md §6 high-risk '
                'employee-analytics controls: documented human oversight, access logging, '
                'retention configuration and manager acknowledgement that outputs are decision '
                'support only, never an automated employment decision.'
            ),
            reference='seed-demo-signoff-employee-analytics-de',
        ))
        now = datetime.utcnow()

        password_hash = hash_password(DEMO_PASSWORD)
        seller_users = {
            'Haydar': User(company_id=company.id, email='haydar@replica-pilot.example', password_hash=password_hash, role='seller'),
            'Mara': User(company_id=company.id, email='mara@replica-pilot.example', password_hash=password_hash, role='seller'),
            'Jonas': User(company_id=company.id, email='jonas@replica-pilot.example', password_hash=password_hash, role='seller'),
        }
        db.add_all(seller_users.values())
        db.add(User(company_id=company.id, email='manager@replica-pilot.example', password_hash=password_hash, role='manager'))
        db.add(User(company_id=company.id, email='admin@replica-pilot.example', password_hash=password_hash, role='tenant_admin'))
        db.add(User(company_id=company.id, email='compliance@replica-pilot.example', password_hash=password_hash, role='compliance_admin'))
        # system_admin is a cross-tenant superuser and therefore belongs to no company.
        db.add(User(company_id=None, email='sysadmin@replica.example', password_hash=password_hash, role='system_admin'))
        db.flush()

        sellers = [
            Seller(company_id=company.id, user_id=seller_users['Haydar'].id, name='Haydar', hired_at=now-timedelta(days=55), product_started_at=now-timedelta(days=42), role='SDR'),
            Seller(company_id=company.id, user_id=seller_users['Mara'].id, name='Mara', hired_at=now-timedelta(days=420), product_started_at=now-timedelta(days=300), role='SDR'),
            Seller(company_id=company.id, user_id=seller_users['Jonas'].id, name='Jonas', hired_at=now-timedelta(days=170), product_started_at=now-timedelta(days=160), role='SDR'),
        ]
        db.add_all(sellers)
        db.flush()
        outcome_pattern = [
            (True,True,True),(False,False,False),(False,False,False),(True,False,False),(False,False,False),
            (True,True,False),(False,False,False),(True,True,True),(False,False,False),(True,True,True),
            (False,False,False),(True,True,False),(False,False,False),(False,False,False),(True,True,True),
        ]
        demo_call_id = None
        for sidx, seller in enumerate(sellers):
            for i in range(18):
                b, h, o = outcome_pattern[(i+sidx*2) % len(outcome_pattern)]
                if seller.name == 'Haydar' and i < 8:
                    b = i in (2,7); h = b; o = False
                if seller.name == 'Haydar' and i >= 8:
                    b = i in (9,11,14,16,17); h = b and i != 16; o = h and i in (11,17)
                c = Call(
                    company_id=company.id,
                    seller_id=seller.id,
                    prospect_company=f'Prospect {sidx+1}-{i+1}',
                    prospect_role='Geschäftsführer' if i % 2 == 0 else 'Head of Sales',
                    segment='B2B SaaS',
                    offer_key='replica_pilot',
                    campaign_key='demo',
                    campaign_type='cold_b2b',
                    jurisdiction_country='DE',
                    started_at=now-timedelta(days=18-i),
                    ended_at=now-timedelta(days=18-i)+timedelta(minutes=5),
                    consent_state='granted',
                    consented_at=now-timedelta(days=18-i),
                    outcome='meeting' if b else 'no_meeting',
                    meeting_booked=b,
                    meeting_held=h,
                    qualified_opportunity=o,
                    revenue=15000 if o and i % 3 == 0 else 0,
                )
                db.add(c)
                db.flush()
                if i == 17 and seller.name == 'Haydar':
                    demo_call_id = c.id
                    turns = [
                        ('seller','Guten Tag, ich mache es kurz. Darf ich sagen, warum ich anrufe?',0,152,330,-22.1,126,42),
                        ('prospect','Ja, aber bitte kurz. Ich habe gleich einen Termin.',4200,179,410,-20.8,138,51),
                        ('seller','Klar. Wir helfen Vertriebsteams dabei, aus ihren Telefonaten mehr qualifizierte Termine zu machen.',7600,166,360,-21.5,128,47),
                        ('prospect','Wir haben dafür schon eine Lösung und sind eigentlich zufrieden.',12300,171,490,-21.2,136,49),
                        ('seller','Was ist Ihnen bei Ihrer aktuellen Lösung am wichtigsten?',16900,149,410,-21.7,127,43),
                        ('prospect','Dass meine Leute weniger Zeit mit Nacharbeit verlieren.',21200,161,350,-20.9,139,54),
                        ('seller','Wie viel Zeit geht dafür heute ungefähr drauf?',25200,147,340,-21.3,125,41),
                        ('prospect','Das ist unterschiedlich, aber teilweise schon eine Stunde am Tag.',29500,154,520,-21.4,134,45),
                    ]
                    for idx, (sp, tx, start_ms, wpm, latency, loud, pitch, pitch_range) in enumerate(turns):
                        db.add(Turn(
                            call_id=c.id, speaker=sp, text=tx, started_ms=start_ms, ended_ms=start_ms+2600,
                            asr_confidence=0.95, words_per_minute=wpm, response_latency_ms=latency,
                            avg_loudness_dbfs=loud, avg_pitch_hz=pitch, pitch_range_hz=pitch_range,
                            style_snapshot={'demo': True, 'turn_index': idx},
                        ))
                    db.add(Meeting(company_id=company.id, call_id=c.id, external_id='demo-meeting-1', source='demo', title='Discovery mit Prospect', starts_at=now+timedelta(days=2), held=False, outcome='scheduled'))
                    db.add(Deal(company_id=company.id, call_id=c.id, external_id='demo-deal-1', source='demo', stage='qualified', amount=15000, closed_won=False))

        db.add(Experiment(
            company_id=company.id,
            key='opener_length_v1',
            hypothesis='Kürzere Opener erhöhen die Gesprächsfortführung im ersten 30-Sekunden-Fenster.',
            status='draft',
            primary_metric='conversation_30s_rate',
            variants={'short': {'target_words': 12}, 'standard': {'target_words': 22}},
        ))
        db.commit()
    finally:
        db.close()
