# REPLICA API Contract

FastAPI exposes Swagger automatically at `/docs`.

## Calls

### `POST /api/calls`
Create a call shell.

### `POST /api/calls/{call_id}/consent`
Body:
```json
{"state":"granted"}
```
Valid states: `granted`, `declined`, `withdrawn`.

### `POST /api/calls/{call_id}/turns`
Stores a measured/transcribed turn. Analysis is blocked unless consent is `granted`.

### `POST /api/calls/{call_id}/complete`
Stores business outcome.

### `GET /api/calls/{call_id}/review`
Returns compact post-call coaching.

### `GET /api/calls/{call_id}/reaction`
Returns baseline + relative reaction deltas for Prospect turns.

## Copilot

### `POST /api/copilot/suggest`
Input:
```json
{
  "call_id": null,
  "utterance": "Wir haben bereits einen Anbieter.",
  "recent_context": [],
  "reaction_snapshot": {}
}
```
Output includes:
- suggestion
- strategy
- do_not
- reason
- confidence
- language_policy
- latency_ms
- evidence_level

### `POST /api/suggestions/{id}/feedback`
```json
{"rating":"good","used":true}
```

## Manager

### `GET /api/manager/overview`
Returns seller context with tenure/product tenure and trend. This endpoint must stay decision-support only.
Since Sprint 0 it is gated by `can_process(db, 'employee_analytics', ...)`: returns `403`
with the policy decision (`result`, `reason`, `policy_reference`) if the tenant's
jurisdiction requires a compliance review signoff that has not been recorded yet
(`POST /api/admin/compliance-signoffs`). The seeded demo tenant already has one.

## Compliance (Sprint 0)

See `docs/GLOBAL_PRODUCT_COMPLIANCE_SPEC.md` and `docs/DECISIONS.md` (Sprint 0 ADRs) for
the policy model behind these endpoints.

### `POST /api/policy/resolve`
Body: `{"action": "live_assist", "tenant_id": null, "call_id": null, "country_code": "DE", "prospect_type": "unknown", "campaign_type": "cold_b2b", "speaker_mode": "human_with_replica_assist"}`
Known actions: `record_audio`, `transcribe`, `live_assist`, `employee_analytics`, `autonomous_call`, `network_learning`, `emotion_inference` (always denied).
Returns `{"action", "result", "reason", "policy_reference"}` where `result` is one of
`allowed`, `denied`, `requires_consent`, `requires_legal_review`. Every call is audited.

### `GET /api/policy/jurisdictions/{country}`
Returns the resolved jurisdiction policy record (falls back to the `default` block for
unknown countries, with `is_default_fallback: true`).

### `GET /api/calls/{call_id}/processing-permissions`
Returns the `record_audio`/`transcribe`/`live_assist` decisions for that call's stored
jurisdiction/campaign/speaker-mode context.

### `POST /api/calls/{call_id}/consents`
Purpose-bound consent ledger entry. Body: `{"consent_type": "transcription", "status": "granted", "purpose": "...", "jurisdiction": "DE", "consent_text_version": "v1", "collection_method": "api", "evidence_ref": ""}`.
`consent_type` is one of `call_recording`, `transcription`, `live_copilot_processing`, `customer_private_learning`, `cross_customer_network_learning`.

### `POST /api/calls/{call_id}/consents/{purpose}/withdraw`
Records a withdrawal event for that purpose.

### `POST /api/network-learning/opt-in` / `POST /api/network-learning/withdraw`
Tenant-level Network Intelligence opt-in/withdraw. Body: `{"reason": "...", "evidence_ref": ""}`.

### `GET /api/admin/feature-flags` / `POST /api/admin/feature-flags`
List/upsert a `TenantFeatureFlag` (`feature_key`, `enabled`, optional `jurisdiction`,
`campaign_type`, `reason`). Can only make a policy-allowed action more restrictive; it
never overrides a policy-denied action (see ADR-009).

### `POST /api/admin/compliance-signoffs`
Records a `ComplianceReviewSignoff` (`action`, `jurisdiction`, `acknowledged_by`,
`reason`, `reference`). Logs a `policy.override` audit event with the previous and new
decision.

### `GET /api/audit/export`
Returns the most recent audit events for the tenant (consent changes, policy decisions,
overrides, feature-flag changes, employee-analytics access, network-learning opt-in/out).

## Integrations

- `GET /api/integrations`
- `POST /api/integrations/hubspot/sync`
- `POST /api/integrations/google-calendar/sync`
- `GET /api/integrations/openai-realtime/blueprint`

## Experiments

### `POST /api/experiments`
Creates an experiment.

### `POST /api/experiments/{experiment_id}/assign/{call_id}`
Deterministically assigns a call to a variant.

## Streaming

### `WS /ws/twilio-media`
Accepts Twilio Media Stream JSON events. The current MVP counts/validates stream metadata only. The production version routes payloads into ASR/audio-feature workers.
