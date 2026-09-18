# REPLICA API Contract

FastAPI exposes Swagger automatically at `/docs`.

## Auth (Sprint 1)

Every endpoint below except `POST /api/auth/login`, `GET /api/health` and `GET /`
requires `Authorization: Bearer <token>`. Get a token via login, then pass it on every
request. `system_admin` is a cross-tenant role and is called out explicitly where it
applies; every other role is implicitly scoped to its own tenant and can never read or
write another tenant's data (see `docs/DECISIONS.md` Sprint 1 ADRs).

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
`409 Consent gate` response is gone (`docs/DECISIONS.md` ADR-020).

### `POST /api/calls/{call_id}/complete`
Stores business outcome.

### `GET /api/calls/{call_id}/review`
Returns compact post-call coaching.

### `GET /api/calls/{call_id}/reaction`
Returns baseline + relative reaction deltas for Prospect turns.

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
  "turn_index": null
}
```
- `call_id` set → gated by `can_process(db, 'live_assist', ...)` for that call; `403`
  with the policy decision when not `allowed`.
- `call_id` omitted → **sandbox/practice mode**: no real prospect, no policy gate, only
  auth/RBAC apply (`docs/DECISIONS.md` ADR-015). The resulting suggestion is still
  tenant-scoped, so feedback on it can never cross tenants.
- `turn_index` (the prospect's turn number within the call, 0-based) is optional; when
  omitted it is inferred as `len(recent_context)`. It feeds SalesBrain's conversation-
  phase detection (see `docs/PRODUCT_SPEC.md` Flow A, `docs/DECISIONS.md` ADR-022) —
  mainly to avoid suggesting a smalltalk follow-up question past the first exchange.

Output includes `suggestion`, `strategy`, `do_not`, `reason`, `confidence`,
`language_policy`, `latency_ms`, `evidence_level`, `phase` (one of
`greeting, rapport_smalltalk, transition, opening, discovery, pitch, objection,
negotiation, closing, wrap_up`), `smalltalk` (`{smalltalk_appropriate,
prospect_wants_business, suggest_brief_reaction, suggest_follow_up_question,
suggest_transition_now}`), and (when call-scoped) `policy_decision`.

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
Accepts Twilio Media Stream JSON events. Authenticated via Twilio's own
request/signature verification (see `docs/INTEGRATIONS.md`), not a REPLICA user bearer
token. The current MVP counts/validates stream metadata only. The production version
routes payloads into ASR/audio-feature workers.
