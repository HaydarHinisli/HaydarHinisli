# REPLICA API Contract

FastAPI exposes Swagger automatically at `/docs`.

## Auth (Sprint 1)

Every endpoint below except `POST /api/auth/login`, `GET /api/health` and `GET /`
requires `Authorization: Bearer <token>`. Get a token via login, then pass it on every
request. `system_admin` is a cross-tenant role and is called out explicitly where it
applies; every other role is implicitly scoped to its own tenant and can never read or
write another tenant's data (see `docs/DECISIONS.md` Sprint 1 ADRs).

### Correlation headers (Provider-Ready Gate)
Every response carries `X-Request-ID` (unique per HTTP call) and `X-Trace-ID` (see
`docs/DECISIONS.md` ADR-033). A caller that already has a `trace_id` for the turn it
is about to process (e.g. because it just called a related endpoint for the same
utterance) should send it via the `X-Trace-Id` request header, or the `trace_id`
field on `POST /api/copilot/suggest`, so both requests' `Suggestion` rows and log
lines can be correlated end-to-end; otherwise one is generated and echoed back.

### `POST /api/auth/login`
Body: `{"email": "...", "password": "..."}`. Returns `{"access_token", "token_type": "bearer", "user": {"id", "email", "role", "company_id"}}`.
`401` on wrong credentials, `403` if the account is deactivated.

### `GET /api/auth/me`
Returns the current identity. Any authenticated role.

### `POST /api/admin/users` — `tenant_admin`
Creates a user in the caller's own tenant. Body: `{"email", "password" (min 8 chars), "role"}`.
`role` is one of `seller`, `manager`, `tenant_admin`, `compliance_admin` (creating a
`system_admin` via this endpoint is rejected — that role has no tenant to assign).

### `POST /api/admin/users/{user_id}/deactivate` / `.../activate` — `tenant_admin`
Deactivation takes effect immediately, even against an already-issued, unexpired token.

## Roles

`seller`, `manager`, `tenant_admin`, `compliance_admin`, `system_admin`. Each endpoint
below states which roles may call it. `system_admin` never has an implicit home tenant;
tenant-scoped admin endpoints accept an explicit `company_id`, which every other role is
rejected for using unless it matches their own tenant (`403`).

## Calls — `seller`, `manager`, `tenant_admin`

### `POST /api/calls`
Body adds (Sprint 1, all optional): `campaign_type` (default `cold_b2b`), `prospect_type`
(`b2b`/`b2c`/`unknown`, default `unknown`), `speaker_mode` (default
`human_with_replica_assist`), `jurisdiction_country` (defaults to the tenant's
`Company.country_code` when omitted). These populate the context every sensitive action
on this call is evaluated against — see `GET .../processing-permissions` below.

### `POST /api/calls/{call_id}/consent`
Body: `{"state":"granted"}` (`granted`, `declined`, `withdrawn`). Legacy convenience
endpoint: writes `ConsentEvent` rows for **both** `live_copilot_processing` and
`transcription` purposes at once (see `docs/DECISIONS.md` ADR-016). No longer the
enforcement point itself — see `POST .../turns` and `POST /api/copilot/suggest`.

### `POST /api/calls/{call_id}/turns`
Stores a measured/transcribed turn. Sprint 1: gated by
`can_process(db, 'transcribe', ...)` using the call's own jurisdiction/campaign/
speaker_mode/consent context — returns `403` with the full policy decision
(`action`, `result`, `reason`, `policy_reference`) when not `allowed`. The old
`409 Consent gate` response is gone (`docs/DECISIONS.md` ADR-020). Sprint 1.5: a
`speaker: "seller"` turn also updates the call's `ConversationState` bookkeeping
(`last_seller_action`, `opening_completed`, `pitch_delivered`) — it does not change
`current_phase` (see ADR-027) — and writes one `ConversationStateEvent` history row.

Provider-Ready Gate (ADR-031): optional `turn_id`, `utterance_id`, `stream_id`,
`provider_event_id` fields identify the real ASR turn this call represents. A repeat
delivery with the same `turn_id` (same call, same `'transcribe'` action) is **not**
stored again — the response is the original turn's payload plus `"duplicate": true`.
Omitting `turn_id` (today's manual/demo flows) synthesizes one from the call's
current turn count, so nothing breaks before Sprint 2's real ASR pipeline exists.

### `POST /api/calls/{call_id}/complete`
Stores business outcome.

### `GET /api/calls/{call_id}/review`
Returns compact post-call coaching.

### `GET /api/calls/{call_id}/reaction`
Returns baseline + relative reaction deltas for Prospect turns.

### `GET /api/calls/{call_id}/conversation-state`
Sprint 1.5. Returns the call's persisted phase-transition state: `current_phase`,
`previous_phase`, `turn_index`, `smalltalk_turns`, `business_transition_started`,
`opening_completed`, `discovery_started`, `pitch_delivered`, `price_discussed`,
`active_objection`, `resolved_objections`, `last_seller_action`,
`last_prospect_event`, `updated_at`. Created on first access if it doesn't exist yet.

### `GET /api/calls/recent/list`

## Copilot — `seller`, `manager`, `tenant_admin`

### `POST /api/copilot/suggest`
Input:
```json
{
  "call_id": null,
  "utterance": "Wir haben bereits einen Anbieter.",
  "recent_context": [],
  "reaction_snapshot": {},
  "turn_index": null,
  "turn_id": null,
  "utterance_id": null,
  "stream_id": null,
  "provider_event_id": null,
  "trace_id": null
}
```
- `call_id` set → gated by `can_process(db, 'live_assist', ...)` for that call; `403`
  with the policy decision when not `allowed`. Sprint 1.5: also advances and persists
  the call's `ConversationState` (`docs/DECISIONS.md` ADR-026/ADR-027) — phase
  decisions understand transitions across the whole call, not just this utterance —
  and writes one `ConversationStateEvent` history row.
- `call_id` omitted → **sandbox/practice mode**: no real prospect, no policy gate, no
  persisted state, only auth/RBAC apply (`docs/DECISIONS.md` ADR-015). The resulting
  suggestion is still tenant-scoped, so feedback on it can never cross tenants. No
  turn-dedup claim applies here either — there is no real turn to deduplicate.
- `turn_index` is only used in sandbox mode (optional; inferred as
  `len(recent_context)` when omitted). Call-scoped requests ignore it — the persisted
  `ConversationState.turn_index` is authoritative there.
- Provider-Ready Gate (ADR-031): for call-scoped requests, `turn_id` (+ optional
  `utterance_id`/`stream_id`/`provider_event_id`) identifies the real ASR turn. A
  repeat delivery with the same `turn_id` (same call, `'live_assist'` action) is
  **not** reprocessed — the response is the original suggestion plus
  `"duplicate": true`, and the conversation state does not advance a second time.
  Omitted `turn_id` synthesizes one from the call's current `turn_index`.
- `trace_id` (ADR-033): reuse the `trace_id` from a related call for the same
  utterance (e.g. this utterance's own `POST .../turns` call) to correlate them; if
  omitted, the request's own `X-Trace-ID` is used. Always echoed back in the response
  and stored on the resulting `Suggestion` row.

Output includes `suggestion`, `strategy`, `do_not`, `reason`, `confidence`,
`language_policy`, `latency_ms`, `evidence_level`, `phase` (one of
`greeting, rapport_smalltalk, transition, opening, discovery, pitch, objection,
negotiation, closing, wrap_up`), `smalltalk` (`{smalltalk_appropriate,
prospect_wants_business, suggest_brief_reaction, suggest_follow_up_question,
suggest_transition_now}`), `trace_id`, and (when call-scoped) `policy_decision` and
`conversation_state` (same shape as `GET .../conversation-state` below).

### `POST /api/suggestions/{id}/feedback`
```json
{"rating":"good","used":true}
```

## Manager — `manager`, `tenant_admin`

### `GET /api/manager/overview`
Returns seller context with tenure/product tenure and trend. This endpoint must stay
decision-support only. Gated by `can_process(db, 'employee_analytics', ...)`: returns
`403` with the policy decision if the tenant's jurisdiction requires a compliance
review signoff that has not been recorded yet (`POST /api/admin/compliance-signoffs`).
The seeded demo tenant already has one.

## Compliance

See `docs/GLOBAL_PRODUCT_COMPLIANCE_SPEC.md` and `docs/DECISIONS.md` for the policy
model behind these endpoints.

### `POST /api/policy/resolve` — `tenant_admin`, `compliance_admin`, `system_admin`
Body: `{"action": "live_assist", "tenant_id": null, "call_id": null, "country_code": "DE", "prospect_type": "unknown", "campaign_type": "cold_b2b", "speaker_mode": "human_with_replica_assist"}`
`tenant_id` is the `resolve_tenant_id` cross-tenant field for `system_admin` (required
for that role, forbidden as "someone else's tenant" for every other role).
Known actions: `record_audio`, `transcribe`, `live_assist`, `employee_analytics`,
`autonomous_call`, `network_learning`, `emotion_inference` (always denied).
Returns `{"action", "result", "reason", "policy_reference"}` where `result` is one of
`allowed`, `denied`, `requires_consent`, `requires_legal_review`. Every call is audited.

### `GET /api/policy/jurisdictions/{country}` — any authenticated role
Returns the resolved jurisdiction policy record (falls back to the `default` block for
unknown countries, with `is_default_fallback: true`). No tenant data involved.

### `GET /api/calls/{call_id}/processing-permissions` — `seller`, `manager`, `tenant_admin`, `compliance_admin`
Returns the `record_audio`/`transcribe`/`live_assist` decisions for that call's stored
jurisdiction/campaign/speaker-mode context.

### `POST /api/calls/{call_id}/consents` — `seller`, `manager`, `tenant_admin`
Purpose-bound consent ledger entry. Body: `{"consent_type": "transcription", "status": "granted", "purpose": "...", "jurisdiction": "DE", "consent_text_version": "v1", "collection_method": "api", "evidence_ref": ""}`.
`consent_type` is one of `call_recording`, `transcription`, `live_copilot_processing`, `customer_private_learning`, `cross_customer_network_learning`.

### `POST /api/calls/{call_id}/consents/{purpose}/withdraw` — `seller`, `manager`, `tenant_admin`
Records a withdrawal event for that purpose.

### `POST /api/network-learning/opt-in` / `.../withdraw` — `tenant_admin`, `compliance_admin`, `system_admin`
Tenant-level Network Intelligence opt-in/withdraw. Body: `{"reason": "...", "evidence_ref": "...", "company_id": null}` (`company_id` is the `system_admin` cross-tenant field).

### `GET`/`POST /api/admin/feature-flags` — `tenant_admin`, `compliance_admin`, `system_admin`
List/upsert a `TenantFeatureFlag` (`feature_key`, `enabled`, optional `jurisdiction`,
`campaign_type`, `reason`, `company_id`). Can only make a policy-allowed action more
restrictive; it never overrides a policy-denied action (see ADR-009). The acting
identity is always the authenticated caller (`current_user.email`), never a
client-supplied string.

### `POST /api/admin/compliance-signoffs` — `tenant_admin`, `compliance_admin`, `system_admin`
Records a `ComplianceReviewSignoff` (`action`, `jurisdiction`, `reason`, `reference`,
`company_id`). `acknowledged_by` is always the authenticated caller. Logs a
`policy.override` audit event with the previous and new decision.

### `GET /api/audit/export` — `tenant_admin`, `compliance_admin`, `system_admin`
Returns the most recent audit events for the tenant (consent changes, policy decisions,
overrides, feature-flag changes, employee-analytics access, network-learning opt-in/out).
`company_id` query param is the `system_admin` cross-tenant field.

## Provider webhooks (unauthenticated — verified by provider signature instead)

### `POST /webhooks/twilio/call-status`
Twilio's call-status-callback. **No `Authorization` header** — authenticated solely by
the `X-Twilio-Signature` header, verified via Twilio's own official
`RequestValidator` (`docs/DECISIONS.md` ADR-029/ADR-036). Missing/invalid signature,
or an unresolvable auth token, → `403`, fail-closed, never processed. The signed URL
is the configured `REPLICA_PUBLIC_BASE_URL` + the request path + query string
(exactly as Twilio's own algorithm requires) — never a fallback to the raw incoming
request URL, so a reverse proxy or a misconfigured base URL cannot silently produce a
false accept.

Two independent hardening layers (`docs/DECISIONS.md` ADR-035):
- **Duplicate detection**: identity is `(CallSid, SequenceNumber)` when Twilio sends
  one, else `(CallSid, CallStatus)`. A delivery whose identity was already claimed is
  a duplicate — not reprocessed, response is `{"ok": true, "duplicate": true}`.
- **Ordering**: a delivery that is NOT a duplicate can still describe an older point
  in time than what has already been applied (out-of-order/delayed delivery). Such an
  event is durably recorded (its `WebhookDelivery` claim already persisted it) but
  NOT applied — response is `{"ok": true, "applied": false}` — and a
  `call.status.<status>.stale` audit event is logged instead of the normal
  `call.status.<status>` one. A normally-applied, non-duplicate delivery returns
  `{"ok": true, "applied": true}`.

No match on `external_call_id` → the delivery is still claimed/ordered, just not
correlated to a `Call` (no audit event is logged in that case, since there is no
tenant to attribute it to).

## Integrations — `tenant_admin`

- `GET /api/integrations`
- `POST /api/integrations/hubspot/sync`
- `POST /api/integrations/google-calendar/sync`
- `GET /api/integrations/openai-realtime/blueprint`

## Experiments — `tenant_admin`, `manager`

### `POST /api/experiments`
Creates an experiment.

### `POST /api/experiments/{experiment_id}/assign/{call_id}`
Deterministically assigns a call to a variant.

## Streaming

### `WS /ws/twilio-media`
Twilio Media Streams ingestion (Sprint 2, `docs/DECISIONS.md` ADR-037..042). **No
`Authorization` header** — authenticated solely by `X-Twilio-Signature` at the
handshake (verified BEFORE accepting the connection), exactly like the call-status
webhook, via the same official `RequestValidator`. Missing/invalid signature, or an
unresolvable auth token → connection closed (code 1008), never accepted. Production
connections must arrive over `wss` (`REPLICA_ENV=production` gates enforcement,
since local/dev has no TLS-terminating proxy in front of it).

Expects Twilio's standard `connected`/`start`/`media`/`stop` message sequence,
`tracks="both_tracks"`. The `start` event's `customParameters.replica_call_id` (set
via a `<Parameter>` on the `<Stream>` TwiML noun) is used to resolve the REPLICA
`Call`; falling back to matching `callSid` against `Call.external_call_id` when not
set. No resolvable call → connection closed immediately (no tenant/policy context to
evaluate against).

Per-message processing: `inbound` (prospect) and `outbound` (seller/agent) tracks are
tracked completely separately (identity/sequence diagnostics, voice-activity
detection, ASR) — see `docs/DATA_MODEL.md`'s `TurnLatencyTrace` and
`docs/DECISIONS.md` ADR-038 for the diagnostics this surfaces (missing/duplicate/
out-of-order chunks, audio gaps, reconnects, backpressure), logged as structured
warnings, never merged into or misread as ASR/SalesBrain behavior. A detected final
turn (a track's own voice-activity detector transitioning from speaking to silent)
is the ONLY thing that reaches `app/services/turn_pipeline.process_final_turn()` —
interim transcripts, however many fire per utterance, never create a `Turn`,
`Suggestion`, or `ConversationStateEvent` row (ADR-042). Every final turn also
persists a `TurnLatencyTrace` row (see `docs/DATA_MODEL.md`).

This endpoint has no synchronous HTTP response; its effects are observable via
`GET /api/calls/{call_id}/review`, `GET /api/calls/{call_id}/conversation-state`, and
the `TurnLatencyTrace`/`ConversationStateEvent` tables (no dedicated read endpoint
for those two yet — direct DB/audit tooling only, matching this sprint's scope of
proving the pipeline shape rather than adding new product-facing read APIs).
