from __future__ import annotations
from collections import Counter
from datetime import datetime
from .sales_brain import classify_sales_event


def _avg(values):
    clean = [v for v in values if v is not None]
    return round(sum(clean) / len(clean), 1) if clean else None


def build_call_review(turns: list, call) -> dict:
    seller_turns = [t for t in turns if t.speaker == 'seller']
    prospect_turns = [t for t in turns if t.speaker == 'prospect']
    avg_seller = _avg([len(t.text.split()) for t in seller_turns]) or 0
    avg_prospect = _avg([len(t.text.split()) for t in prospect_turns]) or 0
    avg_seller_wpm = _avg([t.words_per_minute for t in seller_turns])
    avg_prospect_wpm = _avg([t.words_per_minute for t in prospect_turns])
    objections = Counter(classify_sales_event(t.text) for t in prospect_turns)

    strengths: list[str] = []
    improvements: list[str] = []
    missed: list[str] = []

    if avg_seller <= 18:
        strengths.append('Deine Antworten waren im Schnitt kurz genug für einen Cold Call.')
    else:
        improvements.append('Deine Turns waren teilweise lang. Kürzere Antworten geben dem Prospect mehr Raum.')

    questions = sum(1 for t in seller_turns if '?' in t.text)
    if questions >= 2:
        strengths.append('Du hast mehrfach mit Fragen gearbeitet statt nur zu präsentieren.')
    elif questions == 1:
        strengths.append('Du hast Discovery genutzt; eine weitere Folgefrage hätte zusätzlichen Kontext liefern können.')
    else:
        improvements.append('Es fehlten offene Fragen. Baue früher Discovery ein.')

    if objections['existing_supplier'] and not any(('aktuell' in t.text.lower() or 'wichtig' in t.text.lower() or '?' in t.text) for t in seller_turns):
        missed.append('Beim bestehenden Anbieter lag eine Chance, Entscheidungskriterien zu erfragen.')
    if objections['price']:
        missed.append('Beim Preis sollte zuerst der erwartete Nutzen beziehungsweise das Entscheidungskriterium geklärt werden.')
    if call.meeting_booked:
        strengths.append('Das Gespräch führte zu einem konkreten nächsten Schritt.')
    elif len(prospect_turns) >= 3:
        strengths.append('Der Prospect blieb mehrere Gesprächswechsel aktiv; Gesprächsfortführung war vorhanden.')

    next_focus = (improvements or missed or ['Im nächsten Call eine zusätzliche Discovery-Frage vor dem Pitch stellen.'])[0]
    return {
        'call_id': call.id,
        'outcome': call.outcome,
        'summary': f'{len(turns)} Gesprächsbeiträge. Verkäufer Ø {avg_seller} Wörter/Turn, Prospect Ø {avg_prospect} Wörter/Turn.',
        'strengths': strengths[:3],
        'improvements': improvements[:3],
        'missed_opportunities': missed[:2],
        'next_call_focus': next_focus,
        'metrics': {
            'seller_avg_turn_words': avg_seller,
            'prospect_avg_turn_words': avg_prospect,
            'seller_avg_wpm': avg_seller_wpm,
            'prospect_avg_wpm': avg_prospect_wpm,
            'prospect_turns': len(prospect_turns),
            'meeting_booked': call.meeting_booked,
            'meeting_held': call.meeting_held,
            'qualified_opportunity': call.qualified_opportunity,
        },
        'evidence_note': 'Coaching hints are decision support, not an automated employment decision.',
    }


def manager_analysis(seller, calls: list, team_calls: list) -> dict:
    now = datetime.utcnow()
    tenure_days = max((now - seller.hired_at).days, 1)
    product_days = max((now - seller.product_started_at).days, 1)
    total = len(calls)
    booked = sum(1 for c in calls if c.meeting_booked)
    held = sum(1 for c in calls if c.meeting_held)
    opps = sum(1 for c in calls if c.qualified_opportunity)
    rate = booked / max(total, 1)
    team_rate = sum(1 for c in team_calls if c.meeting_booked) / max(len(team_calls), 1)

    ordered = sorted(calls, key=lambda c: c.started_at)
    split = max(1, len(ordered) // 2)
    earlier, recent = ordered[:split], ordered[split:]
    earlier_rate = sum(1 for c in earlier if c.meeting_booked) / max(len(earlier), 1)
    recent_rate = sum(1 for c in recent if c.meeting_booked) / max(len(recent), 1)
    trend = 'improving' if recent_rate > earlier_rate + 0.02 else 'declining' if recent_rate + 0.02 < earlier_rate else 'stable'

    context: list[str] = []
    if product_days < 90:
        context.append(f'Ramp-up-Kontext: erst {product_days} Tage mit dem aktuellen Produkt.')
    if rate < team_rate and trend == 'improving':
        context.append('Ergebnis unter Teamniveau, aber jüngste Entwicklung positiv.')
    elif rate < team_rate:
        context.append('Ergebnis unter Teamniveau; Gesprächs- und Lead-Kontext vor Personalurteilen prüfen.')
    else:
        context.append('Ergebnis aktuell mindestens auf Teamniveau.')

    return {
        'seller_id': seller.id,
        'seller': seller.name,
        'tenure_days': tenure_days,
        'product_tenure_days': product_days,
        'calls': total,
        'meeting_rate': round(rate * 100, 1),
        'team_meeting_rate': round(team_rate * 100, 1),
        'held_meetings': held,
        'qualified_opportunities': opps,
        'trend': trend,
        'context': context,
        'manager_note': 'REPLICA liefert Kontext und Coaching-Signale, keine Kündigungs-, Eignungs- oder Rankingentscheidung.',
    }
