from __future__ import annotations

WEIGHTS = {
    'conversation_progress': 0.10,
    'qualified_interest': 0.30,
    'meeting_booked': 0.40,
    'meeting_held': 0.70,
    'qualified_opportunity': 1.00,
    'closed_won': 5.00,
}


def call_reward(*, meeting_booked: bool, meeting_held: bool, qualified_opportunity: bool, closed_won: bool = False) -> float:
    score = 0.0
    if meeting_booked:
        score += WEIGHTS['meeting_booked']
    if meeting_held:
        score += WEIGHTS['meeting_held']
    if qualified_opportunity:
        score += WEIGHTS['qualified_opportunity']
    if closed_won:
        score += WEIGHTS['closed_won']
    return round(score, 2)
