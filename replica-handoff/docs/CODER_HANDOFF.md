# Coder Handoff — Build Order

## Objective

Turn this MVP into a pilot that one real seller can use during live outbound calls.

## Sprint 1 — Production skeleton

### Backend
- PostgreSQL instead of SQLite
- Alembic migrations
- tenant/user auth
- RBAC
- proper audit events
- structured logging
- error tracking

### Frontend
- split static demo into real app (React/Next/Vue acceptable)
- WebSocket/SSE channel for live suggestions
- seller live screen
- post-call review screen
- manager screen

### Done when
- login works
- tenant isolation is tested
- seller can create/open a call and manager can see allowed team data

## Sprint 2 — Real audio ingestion

- integrate phone/softphone provider
- signed WebSocket connection
- receive media frames
- stream audio into ASR
- persist interim/final transcript events
- store exact timing telemetry

### Done when
A real consented phone conversation produces timestamped speaker turns in REPLICA.

**Status**: the full pipeline shape is implemented and proven against a faithful
protocol-level simulation (real WebSocket, real signature verification, real
mu-law-encoded audio, real signal-energy VAD, real turn detection, the real central
processing path, real measured latencies) — see `docs/DECISIONS.md` ADR-037..042 and
`tests/test_streaming_pipeline_e2e.py`. What remains, honestly, before this "Done
when" is met by an ACTUAL phone call: a live Twilio account/phone number wired to
this endpoint, and a real ASR vendor implementing the `ASRProvider` seam
(`app/streaming/asr.py`) in place of `SimulatedASRProvider`. Neither is reachable
from this development environment.

## Sprint 3 — Low-latency copilot

Implement:
- early intent/event classifier on interim transcript
- Fast Path response cache/playbook
- LanguageSync profile updated every Prospect turn
- optional Smart Path with larger model
- UI push

### Definition of Done
- RSL measured end-to-end
- P50 target ≤500 ms after detected turn end
- P95 target ≤800 ms after detected turn end
- one primary recommendation, not a list
- seller can rate/use suggestion with one click

## Sprint 4 — Audio features / Reaction Delta

Extract robust telephone-suitable features first:
- WPM
- pause duration
- response latency
- overlap/interruption
- basic pitch/F0/range
- relative loudness change

Avoid strong psychological labels.

### Done when
Every Prospect turn can be compared to a within-call baseline and the result is stored as a measured/derived delta.

## Sprint 5 — Post-call + Outcomes

- generate call review from transcript + events
- sync HubSpot/Salesforce
- sync calendar/meeting provider
- map call → held meeting → opportunity → revenue

### Done when
A pilot dashboard can trace at least one call through a downstream outcome.

## Sprint 6 — Experiment layer

- experiment creation
- deterministic/random assignment
- variant exposure logging
- primary metric aggregation
- confidence/sample-size reporting

### Done when
A customer can run one controlled opener or wording experiment and see a correctly labelled result.

## Sprint 7 — Pilot hardening

- deletion/retention jobs
- consent withdrawal path
- uptime monitoring
- backpressure/retry
- rate limit handling
- pilot export report

## Acceptance test scenarios

1. Prospect: "Keine Zeit" → short permission/relevance response.
2. Prospect: "Schicken Sie eine Mail" → qualify email request.
3. Prospect: "Wir haben einen Anbieter" → discovery, no competitor attack.
4. Prospect uses technical vocabulary → response may use more precise terminology.
5. Prospect uses simple/direct language → response short/plain.
6. Consent declined → no stored analysis.
7. CRM shows meeting held → call outcome updates.
8. Seller in first 60 product days → manager view surfaces ramp-up context.
9. Manager view contains no automated firing/ranking output.
10. Suggestion latency is measured from end-of-turn to browser render.

## What not to build yet

- autonomous mass dialer
- custom foundation model
- custom TTS model
- emotion classifier
- giant analytics dashboard

The pilot succeeds or fails on live usefulness and downstream outcomes, not feature count.

---

# Mandatory Global Product / Compliance Layer

Before production implementation, read `GLOBAL_PRODUCT_COMPLIANCE_SPEC.md` in full.

This is not optional polish. The following must be architecture-level capabilities:

- jurisdiction policy resolution before calls
- purpose-specific consent state machine
- autonomous voice feature flag default OFF
- employee analytics guardrails
- no workplace emotion inference
- cross-tenant raw-data isolation
- Network Intelligence aggregation thresholds and publication delay
- auditability for consent, data access, model version and exports

Use `config/jurisdictions.yaml` only as a conservative starting configuration. It is not a substitute for legal review.

## Additional Sprint 0 — Compliance-capable foundations

Implement before real pilot traffic:

1. `jurisdiction_policy` service
2. purpose-specific consent events
3. campaign classification (`cold_marketing`, `existing_customer`, `requested_callback`, `inbound`, `follow_up`)
4. speaker mode (`human`, `ai_voice`)
5. processing permission resolver
6. feature flags per tenant/country/campaign
7. audit log for every override

### Done when
A developer cannot accidentally enable autonomous marketing calls or recording globally through one environment variable.

## Additional Network Intelligence acceptance criteria

- raw cross-tenant transcripts never returned to customers
- minimum-company aggregation enforced server-side
- publication delay enforced server-side
- sensitive commercial fields rejected from global benchmark pipeline
- tenant opt-in revocation stops future contribution
- every benchmark stores company count, observation count and time window
