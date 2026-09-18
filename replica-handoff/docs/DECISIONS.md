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

---

## Sprint 0 — Compliance-capable foundations (2026-09-18)

The following ADRs record where the Sprint 0 implementation had to make a concrete
engineering choice that `GLOBAL_PRODUCT_COMPLIANCE_SPEC.md`, `CODER_HANDOFF.md` and
`config/jurisdictions.yaml` describe only at the level of intent, plus the deliberate
scope boundary between "new compliance infrastructure" and "existing hot paths".

## ADR-007 — Sprint 0 enforcement scope: new capabilities are gated, existing hot
paths are not (yet)
Status: accepted

The task explicitly protected the working baseline ("Live-Copilot-Funktionalität und
die aktuell funktionierende Baseline bitte nicht verschlechtern"). `record_audio`,
`transcribe` and `live_assist` are fully implemented in `policy_engine.py` and exposed
via new endpoints (`POST /api/policy/resolve`, `GET /api/calls/{id}/processing-permissions`),
but `POST /api/calls/{id}/turns` and `POST /api/copilot/suggest` still use the existing
`Call.consent_state` gate rather than `can_process()`. Reason: demo/seed calls and any
future tenant without a `jurisdiction_country`/purpose-consent history would otherwise
start failing closed (`requires_legal_review`) on every existing call, which is exactly
what the smoke test after implementation showed for a freshly created call. Wiring
`can_process()` into these two endpoints is deferred to Sprint 1, once real per-call
jurisdiction capture and an auth/tenant context exist to populate it correctly.

`employee_analytics` is the one existing endpoint (`GET /api/manager/overview`) that
Sprint 0 *does* hard-gate with `can_process()`, because it was explicitly named as a
fail-closed function and its own DE tier is satisfiable by seeding one
`ComplianceReviewSignoff` for the pilot tenant — so the baseline keeps working while a
tenant without that signoff is genuinely blocked (see `test_tenant_isolation_review_signoff_does_not_leak`).

Consequence: the new endpoints prove the policy engine and consent ledger work and are
independently tested; production-grade enforcement of the live-call hot path is
explicit Sprint 1/2 work, not silently assumed to already exist.

## ADR-008 — Action-to-jurisdiction-field mapping
Status: accepted

`jurisdictions.yaml` has no dedicated field per `can_process` action, so Sprint 0 maps:
- `record_audio` → `recording` (persistent audio storage; the stricter gate)
- `transcribe`, `live_assist` → `human_copilot` (transient processing that enables
  copilot assistance; transcription without storage is treated as part of "a human
  seller gets AI assistance", not as "recording")
- `employee_analytics` → `employee_analytics`
- `autonomous_call` → `autonomous_marketing_call`
- `network_learning` → `network_intelligence`

Consequence: a jurisdiction that is strict about `recording` but permissive about
`human_copilot` (e.g. Germany: `consent_and_legal_review` vs `enabled_with_conditions`)
can allow live transcription/assist under ordinary consent while still requiring a
recorded compliance review before any persistent audio recording.

## ADR-009 — Two distinct override mechanisms, not one
Status: accepted

`TenantFeatureFlag` (pure kill-switch, tenant × jurisdiction × campaign_type) and
`ComplianceReviewSignoff` (tenant × action × jurisdiction acknowledgement) are modeled
as separate tables with separate semantics:
- A feature flag can only ever move a decision *more* restrictive. It can disable an
  otherwise-allowed action; it can never turn a policy-`denied` action on.
- A review signoff can only resolve a `requires_legal_review` tier; it has no effect on
  a `denied` tier.

This keeps "an admin cannot activate a policy-forbidden feature" true by construction:
`evaluate()` returns `DENIED` for the `denied` tier before it ever looks at flags or
signoffs. Verified by `test_feature_flag_cannot_override_hard_policy_denial`.

## ADR-010 — `autonomous_call` defaults to denied everywhere, independent of jurisdiction
Status: accepted

Several jurisdictions' `autonomous_marketing_call` value (e.g. GB/CA `consent_only`)
would otherwise resolve toward `ALLOWED` once a purpose existed. Multiple docs state the
product default must be OFF in every jurisdiction regardless. Sprint 0 implements this as
`DEFAULT_DENY_ACTIONS = {'autonomous_call'}`: even where the jurisdiction tier is not a
hard `denied`, the action stays `DENIED` until a tenant explicitly enables it via a
`TenantFeatureFlag` — and that flag is still capped by the jurisdiction tier per ADR-009.

## ADR-011 — Policy catalog is cached in-process; no hot reload
Status: accepted (tech debt)

`jurisdiction_policy.get_policy_catalog()` uses `functools.lru_cache`, so a change to
`config/jurisdictions.yaml` requires a process restart to take effect. Acceptable for a
single-process pilot; a DB-backed `jurisdiction_policy` table with an admin UI (as
sketched in `GLOBAL_PRODUCT_COMPLIANCE_SPEC.md` §3) is the Sprint 1+ replacement.

## ADR-012 — `prospect_type` and `speaker_mode` are captured but not yet policy-branching
Status: superseded by ADR-013/ADR-014 (Sprint 1)

`PolicyContext` carries `prospect_type` (b2b/b2c/unknown) and `speaker_mode` for context
and audit-trail completeness, but `evaluate()` does not yet branch on them — the current
`jurisdictions.yaml` schema has no B2B/B2C-specific values to branch on. Extending the
yaml schema with such overrides (e.g. stricter consumer-call rules) is a Sprint 1+
candidate once real campaigns need it, rather than inventing untested tiers now.

---

## Sprint 1 — Production skeleton (2026-09-18)

Postgres + Alembic migrations, a real multi-tenant model, JWT auth, RBAC enforced at
the API layer, structured request logging, and wiring the Sprint 0 policy engine into
the live-call hot path (`turns`, `copilot/suggest`) instead of the legacy consent gate.

## ADR-013 — `speaker_mode` becomes load-bearing, not descriptive
Status: accepted

`live_assist` and `transcribe` now require `speaker_mode` in
`{human_seller, human_with_replica_assist, hybrid}`; `autonomous_call` requires
`{ai_agent, hybrid}`. A call marked as a human seller can never be evaluated as an
autonomous-agent call just because a tenant enabled the `autonomous_call` feature flag,
and vice versa — these are different consent/disclosure regimes, not the same action
under different labels. Mismatches return `DENIED` with `policy_reference:
"speaker_mode_mismatch"`, distinguishable from a jurisdiction-law denial.

One pre-existing Sprint 0 test (`test_autonomous_voice_allowed_once_tenant_enables_and_jurisdiction_permits`)
had to be updated to set `speaker_mode='ai_agent', prospect_type='b2b'` — its scenario
was always "an autonomous agent call", it just hadn't needed to say so explicitly before
this ADR made the field load-bearing. The assertion (`ALLOWED`) is unchanged; only the
input context was completed to match what it was already describing.

## ADR-014 — `prospect_type='unknown'` fails closed for the two highest-risk actions
Status: accepted

`record_audio` and `autonomous_call` — persistent audio capture and fully autonomous
outbound speech — now require a known `prospect_type` (`b2b` or `b2c`) before they can
resolve to anything but `DENIED` (`policy_reference: "insufficient_context"`). This is
Sprint 1's literal implementation of "ohne den erforderlichen Kontext sollen sensible
Funktionen fail-closed reagieren": missing call metadata is treated the same as a
missing permission, not silently defaulted to the more permissive B2B assumption.
`live_assist`/`transcribe` are not gated this way — those already fail closed on
missing jurisdiction/consent context, and gating them on `prospect_type` too would have
blocked the sandbox-suggest and ordinary consented-call flows for no compliance benefit.

## ADR-015 — Sandbox copilot mode (`call_id=None`) is not policy-gated
Status: accepted

`POST /api/copilot/suggest` without a `call_id` is a practice/exploration mode: no real
prospect is on the line, so there is no prospect consent to obtain and no jurisdiction
to resolve. It still requires authentication and the same seller/manager/tenant_admin
RBAC as every other copilot action, and the resulting `Suggestion` row is tenant-scoped
(`company_id`) so feedback on it can never be read or rated cross-tenant. This is a
distinct, clearly-scoped product surface, not a bypass of the real, call-scoped
`live_assist` gate — see ADR-020 for why the call-scoped path has no such exemption.

## ADR-016 — The legacy consent endpoint grants two purposes at once
Status: accepted

`POST /api/calls/{id}/consent` (the original single-field `consent_state` endpoint)
now writes **two** `ConsentEvent` rows per call — `live_copilot_processing` and
`transcription` — because that is what its one boolean gate has always covered in the
UI/API contract since the MVP. This is additive convenience, not a second, weaker path:
`can_process()` never reads `Call.consent_state`, only the `ConsentEvent` ledger (see
ADR-019), so this endpoint has to populate that ledger correctly to remain useful.
`POST /api/calls/{id}/consents` (plural) remains available for recording any single
purpose independently, including ones this endpoint doesn't cover
(`call_recording`, `customer_private_learning`, `cross_customer_network_learning`).

## ADR-017 — Schema is versioned via Alembic; no more "delete replica.db"
Status: accepted

`Base.metadata.create_all()` is gone from `app/main.py`'s startup path, replaced by
`app/migrate.py:run_migrations()` calling `alembic upgrade head` programmatically on
every process start (idempotent, safe to repeat — see `app/migrate.py` docstring for
why this is acceptable for a single-instance pilot but not a multi-instance production
deploy). The initial migration (`migrations/versions/dae87f6612b3_initial_schema.py`)
was hand-written to mirror `app/models.py` exactly rather than trusted blindly from
autogenerate output, then verified with `alembic revision --autogenerate` reporting
"No new upgrade operations detected" (zero drift) and a full upgrade/downgrade cycle
against SQLite. A second migration (`11deec5ac162_add_suggestions_company_id`) adds the
new `Suggestion.company_id` column from ADR-015. Both were verified end-to-end against
a real local PostgreSQL 16 instance in this sprint (see the Sprint 1 report), not only
SQLite — `docker-compose.yml`'s `postgres` service uses the same migration path.

`migrations/env.py` resolves `sqlalchemy.url` from `get_settings().replica_database_url`
(not a hardcoded `alembic.ini` value) and passes `fileConfig(..., disable_existing_loggers=False)`
— the default `True` was found, during this sprint's own testing, to silently disable
the `replica.access` structured-logging logger the moment migrations ran, since it
already existed by then. Fixed and covered by `tests/test_migrations.py`.

## ADR-018 — Pilot-grade auth: PBKDF2 + JWT, not bcrypt + OAuth
Status: accepted (tech debt, tracked)

Password hashing uses stdlib `hashlib.pbkdf2_hmac` (260k iterations) instead of
bcrypt/argon2 to avoid a new native/compiled dependency; sessions are stateless JWTs
(`PyJWT`, HS256) rather than server-side, revocable sessions. Both are adequate for a
single-tenant pilot behind the existing `REPLICA_JWT_SECRET`/`REPLICA_JWT_EXPIRES_MINUTES`
settings, but neither is final production hardening — full OAuth/OIDC and a revocable
session store were already listed as open gaps in `README.md` "Produktionslücken"
before this sprint and remain so. `is_active` is checked on every request (not only at
login), so deactivating a user takes effect immediately even against an unexpired token.

## ADR-019 — `Call.consent_state` is now display-only; enforcement is `ConsentEvent`-only
Status: accepted

`Call.consent_state`/`consented_at` remain in the schema (dashboards, existing seed
data, the `POST /api/calls` response) but no endpoint gates behavior on them anymore.
`can_process()` only ever reads the purpose-bound `ConsentEvent` ledger. This closes the
gap ADR-007 (Sprint 0) deliberately left open: Sprint 0 kept `consent_state` as the real
gate for `turns`/`copilot/suggest` specifically to avoid breaking the then-unauthenticated
demo; Sprint 1 removes that legacy gate once real per-call jurisdiction/consent context
and auth exist (see ADR-020).

## ADR-020 — The live-call hot path now runs through `can_process()`; no legacy bypass
Status: accepted — resolves Sprint 0 ADR-007's deferred scope

`POST /api/calls/{id}/turns` (action `transcribe`) and `POST /api/copilot/suggest` with
a `call_id` (action `live_assist`) call `can_process()` and return `403` with the full
decision (`result`, `reason`, `policy_reference`) when not `ALLOWED`. The `409 Consent
gate` response the MVP used is gone. This was safe to do in Sprint 1 (where it would
have risked breaking the still-unauthenticated demo in Sprint 0) because: (a) every
`Call` now has real `jurisdiction_country`/`campaign_type`/`prospect_type`/`speaker_mode`
fields populated at creation time (defaulting `jurisdiction_country` from the tenant's
`Company.country_code`), and (b) the legacy consent endpoint populates the
`ConsentEvent` ledger `can_process()` actually reads (ADR-016). Verified end-to-end
(`tests/test_live_copilot_policy.py`): blocked before consent, allowed after, blocked
again after withdrawal — with no code path that skips the resolver for a real call.

## ADR-021 — The static demo frontend logs in for real; no auth bypass for `REPLICA_DEMO_MODE`
Status: accepted

`app/static/index.html` now calls `POST /api/auth/login` with the seeded
`admin@replica-pilot.example` / `replica-demo-2026` tenant_admin account before making
any other API call, and attaches the resulting bearer token to every subsequent
`fetch()`. The alternative — auto-authenticating unauthenticated requests as a fixed
demo identity when `REPLICA_DEMO_MODE=true` — was rejected: it is a bypass by another
name, and the task explicitly ruled out "Demo- oder Legacy-Bypässe im späteren
Pilotbetrieb". The demo password is intentionally public; it only ever works against a
tenant seeded by `seed_demo()` and is not a credential for any real tenant.
