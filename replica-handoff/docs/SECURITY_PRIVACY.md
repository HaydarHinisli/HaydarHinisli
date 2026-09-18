# Security, Privacy and Learning Modes

This is a product/engineering checklist, not legal advice. A real pilot should receive legal/privacy review for the deployment jurisdiction and exact use case.

## 1. Consent gate

Current MVP blocks stored call analysis unless `consent_state == granted`.
Production should record:
- consent timestamp
- consent text/version
- purpose
- actor/source
- withdrawal
- retention rule

## 2. Tenant isolation

Production requirements:
- every data row carries company/tenant scope where appropriate
- RBAC: seller / manager / admin
- Postgres RLS or equivalent
- provider tokens encrypted per tenant
- no cross-tenant query path in ordinary application code

## 3. Private Learning by default

Default:
- customer calls improve only that customer's REPLICA layer
- no raw audio/transcript enters global training automatically

Optional Network Intelligence:
- separate opt-in
- clearly defined data class
- aggregated/anonymized where feasible
- auditable export lineage

## 4. Employee analytics guardrails

REPLICA must not implement:
- termination recommendation
- suitability score
- hidden employee ranking
- automated high-impact employment action

Manager analytics should expose:
- current outcomes
- development trend
- ramp-up/product tenure
- coaching opportunity
- uncertainty / sample size

Human management remains responsible for employment decisions.

## 5. Data minimization

Prefer:
- derived metrics over indefinite raw audio retention
- pseudonymous Prospect IDs where identity is not required
- configurable raw-audio deletion window
- configurable transcript retention

## 6. Auditability

Audit at minimum:
- consent changes
- exports
- data deletion
- network-learning opt-in changes
- admin integration changes
- model/prompt version used for a review

## 7. Secrets

Production:
- secret manager / vault
- OAuth refresh tokens encrypted
- no provider secrets in browser
- rotate credentials
- signed webhooks

**Provider-Ready Gate status** (`docs/DECISIONS.md` ADR-028): `app/secrets.py`
provides the resolution seam (`SecretsProvider` protocol, `get_secrets_provider()`,
`redact_secret()`) so every *new* secret-consuming call site resolves through one
function instead of scattering `os.environ` reads — today's only implementation reads
env vars, and `REPLICA_SECRETS_BACKEND` set to anything else fails loudly
(`NotImplementedError`) rather than silently. A real vault/secrets-manager backend is
still an open gap — implementing one only requires a new class behind the same
protocol. `app/config.py`'s `Settings` (loaded from `.env`) remains the source of
truth for `twilio_auth_token` etc. until that backend exists — see ADR-028 for why.

Webhook signatures (this gate): `POST /webhooks/twilio/call-status` is verified via
Twilio's own official `RequestValidator` (`app/webhooks/security.py`), fail-closed on
any missing/invalid/unresolvable signature — see ADR-029/ADR-036. Delivery
idempotency (`app/webhooks/idempotency.py`) prevents a retried delivery from being
reprocessed, and out-of-order/stale status events are detected and not applied
without being silently dropped (`app/webhooks/call_status.py` — see ADR-035).

---

## 8. Jurisdiction enforcement

Production must call a policy resolver before:
- recording
- live AI audio processing where legally relevant
- autonomous AI speech
- employee manager analytics
- Network Intelligence contribution

Unresolved policy => fail closed for autonomous marketing and recording.

## 9. No workplace emotion inference

Do not implement emotional-state labels for sellers/employees. Store measurable communication features only.

## 10. Network Intelligence / competition safety

Cross-tenant learning must be isolated behind an aggregation service.

Engineering defaults:
- minimum 10 companies per benchmark cell; configurable upward
- prefer >=20 for commercially sensitive performance benchmarks
- 90-day minimum publication delay for cross-company commercial benchmark data
- blacklist named-customer, named-competitor, current/future price and future strategy fields

These defaults are policy controls, not legal safe harbours.
