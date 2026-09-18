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

### TurnLatencyTrace (Sprint 2/2B/3A, refined by ADR-051)
End-to-end pipeline timing for one final turn processed through the Twilio Media
Streams pipeline (`app/streaming/pipeline.py` → `app/services/turn_pipeline.
process_final_turn()`). One row per final turn. Wall-clock `_at` columns are for
audit/cross-system correlation only; every server-side `_ms` duration (except
`wallclock_rsl_estimate_ms`, see below) is computed from monotonic clock readings
taken in-process. See `docs/DECISIONS.md` ADR-041/051.

- company_id / call_id / turn_id / trace_id / speaker
- **asr_provider / is_synthetic** (Sprint 2B, ADR-045): which `ASRProvider`
  produced this row and whether it is a `SimulatedASRProvider` development
  measurement (`is_synthetic=True`, the default) or a real one — query this before
  ever reporting a number, so a dev measurement can never be presented as real.
- t_audio_received_at, t_asr_interim_at, t_asr_final_at, t_turn_end_detected_at,
  **t_turn_end_detected_monotonic** (ADR-051 — a raw monotonic float, the ONE
  deliberate exception to "never persist a monotonic value", needed later to
  compute `server_render_ack_latency_ms`) plus
  **t_turn_end_detected_monotonic_runtime_id** (ADR-052 — a per-process-start id
  that must match the CURRENT process's own id before that computation happens
  at all; a mismatch — restart, host change, or a misconfigured multi-instance
  deployment routing the Render-ACK elsewhere — means comparability is
  unverifiable and the value is never computed, not just discarded as an
  after-the-fact heuristic; see `docs/DEPLOYMENT.md`),
  t_provider_endpoint_detected_at (Sprint 2B, ADR-046 — the ASR provider's OWN
  endpointing signal, comparison-only, never authoritative),
  t_salesbrain_started_at, t_salesbrain_finished_at, t_suggestion_persisted_at,
  **t_push_enqueued_at** (renamed from `t_suggestion_pushed_at`, ADR-051 — set
  when the Suggestion is handed to `LiveSuggestionHub`, regardless of whether a
  browser is connected at that moment), **t_ws_send_completed_at** (ADR-051 —
  once every currently-connected subscriber's WebSocket send has completed,
  isolating hub-handoff latency from network/event-loop latency),
  **t_browser_received_at / t_ui_rendered_at** (Sprint 3A, ADR-048 — set ONLY by
  the browser's own `POST /api/suggestions/{id}/render-ack`; never estimated
  server-side), **t_render_ack_received_at** (ADR-051 — server wall-clock moment
  that same HTTP request was processed, distinct from `t_ui_rendered_at`)
- audio_to_interim_ms, audio_to_final_ms (ASR latency), turn_detection_latency_ms,
  provider_endpoint_vs_turn_end_ms (Sprint 2B, ADR-046: our VAD turn-end minus the
  provider's own endpointing — positive means ours fired later),
  salesbrain_latency_ms (internal Fast-Path engine latency — **not** RSL),
  suggestion_persist_latency_ms (persisted → push_enqueued),
  **ws_send_latency_ms** (ADR-051: push_enqueued → ws_send_completed —
  server-internal/monotonic, hub/event-loop scheduling latency only),
  **client_render_latency_ms** (Sprint 3A — the browser's own monotonic
  `performance.now()` delta between receiving and painting the suggestion; a
  browser-local diagnostic, never merged with anything server-side),
  **wallclock_rsl_estimate_ms** (renamed from `real_rsl_ms`, ADR-051 —
  `t_ui_rendered - t_turn_end_detected`; stays null until a real Render-ACK
  exists, never approximated. A genuine cross-machine WALL-CLOCK delta, hence
  "estimate" — the browser and server share no monotonic clock, unlike every
  other `_ms` column above),
  **server_render_ack_latency_ms** (ADR-051 — `render_ack_received -
  turn_end_detected`, computed entirely server-side from two monotonic readings
  on the same process; a robust UPPER BOUND that deliberately includes the
  Render-ACK's own HTTP round trip),
  **clock_offset_estimate_ms / clock_rtt_estimate_ms / clock_uncertainty_ms**
  (ADR-051 — an NTP-style browser↔server clock-sync estimate from ping/pong
  samples exchanged over `/ws/live/{call_id}`, `app/services/clock_sync.py`;
  prepared for later use, not yet used to correct `wallclock_rsl_estimate_ms`)

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
