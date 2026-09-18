# REPLICA Data Model — Cold Call Genome

## 1. Purpose

A call is not just an audio file. REPLICA stores a structured genome that connects conversation behavior with business outcome.

## 2. Core entities

### Company
- tenant boundary
- network-learning opt-in

### Seller
- company
- role
- hired_at
- product_started_at

`hired_at` and `product_started_at` are context variables, not a performance score.

### Call
- seller
- prospect company/role/segment
- offer/campaign
- consent state
- outcome flags
- external call ID

### Turn
Text/time:
- speaker
- text
- start/end timestamps
- ASR confidence

Acoustic/interaction:
- words_per_minute
- response_latency_ms
- pause_before_ms
- overlap_ms
- loudness dBFS
- pitch
- pitch range

Language:
- lexical complexity
- style snapshot

### Suggestion
- what REPLICA recommended
- strategy
- reason
- do-not
- confidence
- language policy
- reaction snapshot
- latency
- seller feedback
- used/not used
- `trace_id` (Provider-Ready Gate): correlates this suggestion with the request(s)
  that produced it end-to-end — see `docs/DECISIONS.md` ADR-033.

### ConversationState (Sprint 1.5)
One row per Call. Lets SalesBrain understand phase transitions across the whole
running call (`greeting -> rapport_smalltalk -> transition -> opening -> discovery`,
objections layered on top) instead of reclassifying each prospect sentence in
isolation. See `app/services/conversation_state.py` for the state machine and
`docs/DECISIONS.md` ADR-026/ADR-027 for the design rationale.

- current_phase / previous_phase
- turn_index
- smalltalk_turns
- business_transition_started
- opening_completed
- discovery_started
- pitch_delivered
- price_discussed
- active_objection
- resolved_objections
- last_seller_action
- last_prospect_event

### ConversationStateEvent (Provider-Ready Gate)
Append-only history — one row per *processed* turn (prospect or seller) — kept
alongside (never instead of) the single mutable `ConversationState` row above. Lets
post-call review, coaching, the Experiment Engine and the future Cold Call Genome
reconstruct how a call actually developed, not just its current state. See
`docs/DECISIONS.md` ADR-030.

- company_id / call_id / turn_index / speaker (`seller` | `prospect`)
- from_phase / to_phase
- event_type (`phase_change`, `objection_raised`, `utterance`, `seller_action`)
- objection_type
- sales_action
- trigger
- created_at

### ProcessedTurnEvent (Provider-Ready Gate)
Exactly-once processing guard for real turns, scoped to `(call_id, action, turn_id)`
via a unique constraint. Not a business record on its own — purely infrastructure so
a webhook retry, reconnect, or duplicate final transcript can never trigger a second
state transition or a second Copilot run for the same real utterance. See
`docs/DECISIONS.md` ADR-031.

- company_id / call_id / action (`transcribe` | `live_assist`) / turn_id
- utterance_id / stream_id / provider_event_id (correlation only, not the uniqueness key)
- result_ref (the first claim's result, returned to a later duplicate instead of reprocessing)
- processed_at

### WebhookDelivery (Provider-Ready Gate)
Idempotency ledger for inbound provider webhooks, scoped to `(provider, event_type,
external_id)` via a unique constraint. See `docs/DECISIONS.md` ADR-029.

- provider / event_type / external_id
- company_id (nullable — set only when the delivery could be correlated to a tenant)
- received_at / payload_summary

### CallProviderStatus (Provider-Ready Gate hardening)
Materialized "latest applied" provider call status — one row per `(provider,
external_call_id)`, kept separate from `WebhookDelivery` above (which only answers
"have I seen this exact event before") and from `Call`'s own seller-driven business
outcome fields. What `is_newer_event()` compares an incoming Twilio status event
against, so a late/out-of-order event can be recognized and not applied without
discarding the fact that it arrived. See `docs/DECISIONS.md` ADR-035.

- provider / external_call_id
- call_id (nullable — correlated once a matching `Call` is resolved)
- last_status / last_sequence_number
- updated_at

### Meeting
- external provider ID
- source
- scheduled time
- held/not held

### Deal
- CRM deal/opportunity stage
- amount
- closed won

### Experiment
- hypothesis
- variants
- primary metric
- assignment

### AuditEvent
- consent changes
- exports
- data deletion
- integration actions

## 3. Evidence levels

Every derived claim should carry one of:

1. `measured` — timestamp, pause, audio metric
2. `derived` — WPM, lexical complexity
3. `observed_association` — correlation across calls
4. `experimentally_supported` — randomized/controlled test
5. `replicated` — repeated across periods/segments

The UI should never display an association as if it were causal.

## 4. Prospect language profile

Do not store labels such as education/intelligence.
Store observable preferences only:
- sentence length
- jargon usage
- preferred terminology
- directness
- clarification requests
- answer length

## 5. Reaction Delta

Build a within-call baseline for the Prospect and compare later turns:
- WPM delta
- response latency delta
- turn length delta
- loudness delta
- pitch-range delta

These describe conversation changes. They do not prove emotion.

## 6. Data lineage

Every model-facing training sample should preserve:
- source call ID
- tenant ID
- consent / allowed-use state
- transformation version
- model/prompt version
- evidence level
- removal/deletion lineage
