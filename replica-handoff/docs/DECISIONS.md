# Product / Architecture Decisions

## ADR-001 — Copilot before autonomous caller
Status: accepted

Reason:
- fastest way to validate usefulness
- human remains in control
- generates high-quality preference data
- avoids making the product dependent on TTS quality for first validation

## ADR-002 — Fast Path before Smart Path
Status: accepted

Reason:
- live cold calls cannot wait for long reasoning
- common objections can be handled by a classifier + playbook
- smart reasoning is optional refinement

## ADR-003 — Observable signals, not emotion labels
Status: accepted

Store:
- pause
- WPM
- response latency
- overlap
- pitch change
- word choice

Do not claim:
- anger
- fear
- intelligence
- personality

## ADR-004 — Held meetings/opportunities over booking vanity metrics
Status: accepted

Booking more low-quality meetings is not success. Downstream outcomes receive more weight.

## ADR-005 — Private Learning default
Status: accepted

A customer tenant does not automatically contribute raw calls/transcripts to global training.

## ADR-006 — Manager context, not employee ranking
Status: accepted

REPLICA may show ramp-up, trends and coaching areas. It must not output a termination recommendation or an automated good/bad employee ranking.
