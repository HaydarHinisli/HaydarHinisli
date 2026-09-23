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

---

## SalesBrain conversation-phase / smalltalk feature (2026-09-18)

## ADR-022 — Phase detection can only ever specialize the two generic fallback events
Status: accepted

`app/services/sales_brain.py` adds ten conversation phases
(`greeting, rapport_smalltalk, transition, opening, discovery, pitch, objection,
negotiation, closing, wrap_up`) and prospect-anchored smalltalk analysis
(`analyze_smalltalk`). The priority order in `decide()` is deliberate and load-bearing
for backward compatibility:

1. If `classify_sales_event()` returns one of the six specific objection/exit events
   (`time_pressure, email_exit, no_interest, existing_supplier, price, authority`),
   phase is unconditionally `'objection'` and the response comes from the existing,
   tested `PLAYBOOK[event]` — exactly as before this feature existed. New phase
   detection is never even consulted for these events.
2. Only the two generic fallback events (`discovery`, `question`) are checked against
   `detect_special_phase()` for a more specific moment (greeting/smalltalk/transition/
   negotiation/closing/wrap_up) before falling back to their own `PLAYBOOK` entry.

Consequence: adding phase awareness can only make a *generic* response more specific;
it can never change the response to an already-specific objection. Verified by
`tests/test_sales_brain_phases.py`'s three regression tests
(`existing_supplier`/`time_pressure`/`price` objections asserted unchanged) plus all
pre-existing `tests/test_core.py` assertions, none of which needed modification.

`event == 'question'` maps to `phase == 'pitch'` (a prospect question typically arises
while the seller is presenting/explaining) rather than exposing `'question'` as a
phase name, since the product brief's phase list doesn't include it.

## ADR-023 — `'opening'` is not auto-detected from prospect text alone
Status: accepted (tech debt, tracked)

`'opening'` remains in `CONVERSATION_PHASES` for schema completeness (it's a real,
named phase in the product brief) but `detect_special_phase()` never returns it. It is
naturally the seller's own next move right after `'transition'` — "briefly explain why
I'm calling, then move to discovery" — and a stateless, single-utterance heuristic
(matching the rest of the Fast Path's design) has no reliable signal to distinguish "the
seller is opening" from "the seller is doing discovery" purely from the prospect's
current turn. Correctly modeling `'opening'` needs call-level phase state carried
across turns (e.g. "we know the previous phase was `transition`, so the next seller
turn is `opening`"), which requires the per-call turn sequence Sprint 2's real audio
ingestion introduces. Tracked as a Sprint 2+ follow-up, not silently dropped.

## ADR-024 — Smalltalk anchors are read, never invented
Status: accepted

`analyze_smalltalk()` only flags `smalltalk_appropriate=True` when the **prospect's own
current utterance** contains a recognizable personal/non-business anchor
(`SMALLTALK_MARKERS`: meeting, weekend, weather, "gerade unterwegs", etc.). It never
looks at prior calls, CRM data, or assumed context — matching the product brief's
"Persönliche Gesprächsanker sollen nur verwendet werden, wenn sie vom Prospect selbst im
aktuellen Gespräch eingebracht wurden" verbatim. `suggest_follow_up_question` is also
capped to the first exchange (`turn_index <= 1`); from the second prospect turn with a
smalltalk anchor onward, `suggest_transition_now` becomes `True` instead, so smalltalk
is never artificially prolonged (`tests/test_sales_brain_phases.py::test_smalltalk_follow_up_not_suggested_after_first_exchange`).

## ADR-025 — Phase/smalltalk fields are response-only, not yet persisted
Status: accepted (tech debt, tracked)

`decide()`'s new `phase` and `smalltalk` fields flow through `suggest()` into the
`POST /api/copilot/suggest` response, but `Suggestion` (the DB row) gains no new
columns for them in this task — consistent with `event`, which was already
response-only and never persisted before this feature existed. Persisting phase
history per call (for post-call review, e.g. "spent too long in rapport_smalltalk
before transitioning") is a reasonable Sprint 2+ addition once Cold Call Genome
storage (`docs/DATA_MODEL.md` §2 Turn/Suggestion) is revisited for real call data,
not invented speculatively here.

---

## Sprint 1.5 — Conversation State Foundation (2026-09-18)

`ConversationState` (`app/models.py`, `app/services/conversation_state.py`) resolves
ADR-025's tracked gap by giving SalesBrain call-level memory: phase decisions now
understand transitions (`greeting -> rapport_smalltalk -> transition -> opening ->
discovery`, objections layered on top) instead of reclassifying each prospect
utterance from a blank slate.

## ADR-026 — State refines the stateless phase resolution; it never re-implements it
Status: accepted

`app/services/conversation_state.apply_prospect_turn()` reuses
`sales_brain.classify_sales_event()`, `detect_special_phase()`, `analyze_smalltalk()`
and the new `build_response()` helper (extracted from `decide()` in this sprint,
pure refactor — see the `sales_brain.py` history) rather than duplicating any
classification logic. The state machine only adds three things on top:
1. A **business-anchor override**: a smalltalk-flavored utterance that also mentions
   something business-relevant (new office, a stated problem/challenge, growth,
   headcount, ...) resolves straight to `'discovery'` (with `discovery_started=True`)
   instead of `'rapport_smalltalk'` — the product brief's explicit requirement that a
   relevant anchor inside smalltalk must not be discarded as "just rapport".
2. A **front-phase regression guard**: once the call has passed a point in
   `greeting -> rapport_smalltalk -> transition -> opening -> discovery`, a new
   utterance that superficially reads as an earlier phase (e.g. a stray smalltalk-like
   aside in the middle of discovery) cannot move the call backward — it resumes at the
   furthest phase implied by the state's own flags (`_resume_phase()`), never at
   `'greeting'`. Objection/negotiation/closing/wrap_up are not part of this ordered
   progression and can interleave freely, since they are reactions to specific
   content, not call-stage markers.
3. **Objection lifecycle bookkeeping**: `active_objection` / `resolved_objections`
   track which objection (if any) is currently open and which have been moved past —
   switching to a different objection resolves the previous one; repeating the same
   objection does not duplicate the resolved list; `price_discussed` persists once set,
   independent of whether the price objection is later resolved.

The MVP smalltalk default from ADR-024 (push toward transition after the first plain
exchange) is preserved as exactly that — a default — and is the first thing the
business-anchor override supersedes, per the task's explicit instruction not to model
it as a hard rule that would ignore a relevant anchor.

## ADR-027 — Only prospect turns advance the phase machine; seller turns are bookkeeping
Status: accepted

`POST /api/copilot/suggest` (call-scoped) is the single place a `ConversationState` row
advances its phase, via `apply_prospect_turn()` — this mirrors the existing product
architecture where REPLICA reacts to what the *prospect* says next, and avoids the
double-counting risk of two separate endpoints (`/turns` and `/copilot/suggest`)
independently reclassifying the same utterance if both happened to be called for it.
`POST /api/calls/{id}/turns` with `speaker='seller'` calls `apply_seller_turn()`
instead, which only updates `last_seller_action` / `opening_completed` /
`pitch_delivered` bookkeeping and never touches `current_phase` — consistent with
`'opening'` remaining not independently phase-classified (ADR-023), since it is a
seller-side action layered onto the prospect-driven phase machine.

This endpoint split is itself a known simplification of the MVP's historical
turns/suggest separation (`docs/CODER_HANDOFF.md` Sprint 3 already anticipates
`Turn Detector -> FAST PATH` as one pipeline step). Sprint 2's real turn-end detection
naturally collapses it: once there is exactly one internal call per detected prospect
turn, the "which endpoint owns state advancement" question disappears together with
the two-endpoint design that raised it.

New `GET /api/calls/{call_id}/processing-permissions`-style read endpoint,
`GET /api/calls/{call_id}/conversation-state`, exposes the persisted state directly
(same RBAC as other call-scoped endpoints, same 404-not-403 tenant scoping) — mainly
for debugging and for Sprint 2+ manager/coaching views that may want to show phase
history, without requiring every consumer to replay `/copilot/suggest` calls.

## ADR-028 — Secrets resolution goes through a seam, not scattered `os.environ` reads
Status: accepted

`app/secrets.py` introduces a `SecretsProvider` protocol and `get_secrets_provider()`
before Sprint 2 needs any real provider credential beyond Twilio's static
account SID/auth token (OpenAI Realtime, future STT/TTS vendors, ...). Today's only
implementation, `EnvSecretsProvider`, reads `os.environ` — functionally identical to
reading `os.environ` directly — but every *new* secret-consuming call site (the Twilio
webhook signature check, ADR-029) goes through the seam from day one, so switching to
a real secrets manager (Vault, AWS Secrets Manager, ...) later touches one function,
not every call site. `REPLICA_SECRETS_BACKEND` selects the backend (default `'env'`);
any other value raises `NotImplementedError` loudly at resolution time rather than
silently falling back — a misconfigured backend must be a visible failure, not a
quiet no-op, consistent with this project's fail-closed default everywhere else.

Known deviation (documented per the standing instruction to flag any divergence from
the spec/handoff docs): `app/config.py`'s pydantic-settings `Settings` object remains
the source of truth for `twilio_auth_token` and friends, loaded from `.env` at
process start — it does **not** yet route through `get_secrets_provider()`, because
pydantic-settings reads `.env` directly into its own model rather than exporting those
values into `os.environ`, so `EnvSecretsProvider.get()` would miss a value that is only
ever set via `.env`. The Twilio webhook handler therefore resolves the auth token as
`get_secrets_provider().get('TWILIO_AUTH_TOKEN', settings.twilio_auth_token)` — the
seam is consulted first (so a real backend, or an explicitly exported env var, takes
priority), falling back to the already-correctly-loaded `Settings` value. Fully routing
`Settings` itself through the seam is deferred to whenever a real secrets backend is
actually implemented, since a `Settings`-level change affects every configured value,
not just secrets, and is out of scope for this gate. `redact_secret()` exists for the
day log lines need to reference a secret's presence without ever printing it in full.

## ADR-029 — Webhook authenticity and delivery idempotency (Twilio call-status)
Status: accepted

`POST /webhooks/twilio/call-status` is REPLICA's first inbound provider webhook.
Twilio cannot present one of our bearer tokens, so the *only* authentication
available is Twilio's own request-signing scheme: HMAC-SHA1 over the exact URL plus
sorted, concatenated POST parameters, keyed with the account's auth token, compared
via `hmac.compare_digest` (`app/webhooks/security.py`, per Twilio's documented
algorithm — see `docs/PROVIDER_REFERENCES.md`). A missing header, a missing/
unresolvable auth token, or a mismatched signature all fail closed with `403` —
there is no "process anyway" fallback, matching this project's consent/policy gates
everywhere else. The signed URL is reconstructed from
`settings.replica_public_base_url`, not `request.url`, because a TLS-terminating
reverse proxy in front of the app can hand Starlette an `http://` URL for a request
Twilio actually made over `https://`, which would make every signature check fail.

Idempotency is a second, independent concern layered on top: Twilio retries a
webhook delivery on anything other than a fast `2xx`, so the same `(CallSid,
CallStatus)` pair can legitimately arrive more than once and must not be
double-processed (e.g. double-writing an audit event). `claim_webhook_delivery()`
(`app/webhooks/idempotency.py`) claims `(provider, event_type, external_id)` via the
`webhook_deliveries` table's unique constraint — insert-then-catch-`IntegrityError`,
the same race-safe pattern used for turn deduplication (ADR-031) — rather than a
read-then-write check, which would have a race window between two near-simultaneous
retries. A duplicate delivery still returns `200 {"ok": true, "duplicate": true}` so
Twilio stops retrying, per Twilio's own guidance.

Known tech debt: the endpoint is `async def` (required to `await request.form()`)
but performs synchronous SQLAlchemy calls, briefly blocking the event loop. Acceptable
for Twilio's low-frequency status callbacks; revisit (e.g. `run_in_threadpool`, or an
async DB driver) if webhook volume grows meaningfully before Sprint 2's real media
streaming work supersedes this shape entirely.

## ADR-030 — Conversation-state history is an append-only ledger beside the fast state; `apply_turn()` unifies both speakers
Status: accepted

`ConversationStateEvent` (new table `conversation_state_events`) records one row per
*processed* turn — prospect or seller — alongside (never instead of) the single
mutable `ConversationState` row from Sprint 1.5. The fast row answers "what is the
call's state right now"; the history answers "how did it get here", which post-call
review, coaching, the Experiment Engine and the eventual Cold Call Genome all need and
which a single overwritten row structurally cannot provide. Writing it costs exactly
one extra `INSERT` in the DB-aware endpoint layer (`app/main.py`'s
`_record_state_event()`) — the pure state machine in
`app/services/conversation_state.py` is completely unaware the history table exists,
so it stays exactly as fast (and exactly as unit-testable in isolation) as before this
gate, per the explicit instruction that this history must not slow the live state
machine.

To make that possible without recomputing anything, `apply_prospect_turn()` and
`apply_seller_turn()` now each return a `transition` dict (`from_phase`, `to_phase`,
`event_type`, `objection_type`, `sales_action`, `trigger`) shaped exactly like a
`ConversationStateEvent` row, computed as a byproduct of logic the state machine
already runs — no new classification work. A new `apply_turn(state, speaker, text,
language_policy)` dispatcher unifies both speakers behind one call: it returns
`(new_state, transition, decision)`, where `decision` is the SalesBrain suggestion
payload for a prospect turn or `None` for a seller turn (bookkeeping only, nothing to
surface). `suggest_with_state()` (`app/services/copilot.py`) now calls `apply_turn()`
instead of `apply_prospect_turn()` directly, and `POST /api/calls/{id}/turns`'
seller-turn branch calls it instead of the old bare `apply_seller_turn()` — both call
sites get a `transition` for history-writing "for free" from the same call that
already computed everything else.

## ADR-031 — Event/Turn Identity & Deduplication: idempotent, effectively-once processing per real turn
Status: accepted

Once Sprint 2 introduces streaming ASR, the same real spoken turn can legitimately
reach REPLICA's endpoints more than once: a webhook/provider retry, a websocket
reconnect mid-utterance, a provider re-sending a "final" transcript it already sent,
or an interim revision that looks like a new event. None of these may trigger a
second state transition or a second Copilot suggestion for the same turn — that would
double-count `turn_index`, corrupt phase progression, and show the seller two
suggestions for one thing the prospect said once.

Terminology, made precise here after an initial pass used "exactly once" loosely
(corrected in this hardening round, see ADR-034): REPLICA cannot guarantee
"exactly-once delivery" — nothing sitting behind HTTP/webhooks can, a provider is
always free to call more than once for the same real turn. What it does guarantee is
**idempotent, effectively-once processing**: the persisted effect of a real turn is
applied exactly once per successful attempt, and a failed attempt leaves zero trace
(ADR-034's transaction-boundary guarantee is what makes that true, not this table by
itself). This ledger enforces the *idempotency* half of that; ADR-034 explains why a
crash can never leave a turn stuck in a half-processed state.

`ProcessedTurnEvent` (new table `processed_turn_events`) is the single choke point
enforcing this, scoped to `(call_id, action, turn_id)` via a unique
constraint — the same insert-then-catch-`IntegrityError` claim pattern as webhook
idempotency (ADR-029), reused because it is the identical problem ("have I already
claimed this token") under concurrent access. `app/services/turn_identity.py`
exposes `claim_turn()` (returns `(claimed, row)`) and `record_result()` (stores what
the claim produced, so a later duplicate can return the *original* result instead of
reprocessing or erroring). `turn_id` is REPLICA's own idempotency key; `utterance_id`
/ `stream_id` / `provider_event_id` are carried through for correlation and debugging
but are deliberately **not** part of the uniqueness boundary, since a provider may
legitimately reuse or omit them across interim/final ASR revisions — only `turn_id`
is required to be provider-stable.

Both `POST /api/calls/{id}/turns` (action `'transcribe'`) and `POST
/api/copilot/suggest` (action `'live_assist'`) now call `claim_turn()` before doing
any work; a duplicate claim short-circuits to the cached `result_ref` with
`"duplicate": true` in the response instead of reprocessing. Uniqueness is
deliberately scoped *per action*, not globally per turn: today's two-endpoint MVP
split means the same real utterance is legitimately claimed once for `'transcribe'`
and once for `'live_assist'` — see ADR-032 for why that split still exists and how it
is expected to disappear. Callers that don't yet have a real provider-stable
`turn_id` (today's manual UI and demo flows) get one synthesized from `(call_id,
action, current turn count)` via `synthesize_turn_id()`, so nothing breaks before a
real ASR pipeline exists to supply a better one.

## ADR-032 — Sprint 2 forward-compatibility: seller bookkeeping and the two-endpoint split are MVP simplifications, not architecture
Status: accepted

Two shortcuts remain deliberately in place after this gate, both flagged explicitly
so Sprint 2 does not have to rediscover them the hard way:

1. **Seller turns only affect bookkeeping.** `apply_seller_turn()` (via `apply_turn()`,
   ADR-030) updates `last_seller_action` / `opening_completed` / `pitch_delivered` and
   returns a `transition` whose `from_phase` always equals `to_phase` — it never
   drives `current_phase` itself (ADR-023, ADR-027). This is today's MVP
   simplification, not a permanent constraint: the `transition` dict already reports
   `sales_action` precisely (e.g. `'pitch'`, `'closing'`, `'discovery_question'`), so a
   future revision can let a specific seller action legitimately drive a real phase
   transition (e.g. a deliberate discovery→pitch handoff) by branching on
   `sales_action` inside `apply_seller_turn()` — without changing its signature, its
   callers, or the `ConversationStateEvent` schema that already has a column for it.
2. **`/turns` and `/copilot/suggest` remain two independent state-writers.** Both
   claim turns via `ProcessedTurnEvent` under different `action` values (ADR-031) and
   both can independently call into `apply_turn()`, which is exactly the "two
   endpoints reclassifying the same utterance" risk ADR-027 already named. This gate
   does not collapse that split — doing so requires the real ASR pipeline's turn-end
   detection, which is Sprint 2's job — but it ensures nothing about today's design
   depends on the split persisting: once Sprint 2 has one real "final turn" event, it
   should call `apply_turn()` exactly once through a single processing path, and nothing
   in `app/services/conversation_state.py` needs to change for that to happen.

## ADR-033 — `trace_id` correlates a turn across requests; it is not `request_id`
Status: accepted

`RequestContextMiddleware` already assigned a `request_id` per HTTP request (Sprint
1). That is insufficient for Sprint 2: a single real prospect turn is processed by
*two* separate HTTP calls under today's split (`POST /calls/{id}/turns`, then `POST
/copilot/suggest` — see ADR-032), each of which would get its own unrelated
`request_id`, making it impossible to correlate them in logs or in the `Suggestion`
row that resulted. `trace_id` is the answer: a caller that already has one (e.g. the
ASR pipeline, or a first call's own response) passes it via the `X-Trace-Id` request
header or the `trace_id` field on `TurnRequest`/`SuggestRequest`; otherwise
`RequestContextMiddleware` generates one and echoes it back via the `X-Trace-Id`
response header so the caller can pick it up and reuse it for the next call in the
same turn's flow. `Suggestion.trace_id` (new column) persists whichever trace_id
produced that suggestion, so a later real end-to-end RSL measurement (`t_turn_end` ->
`t_ui_rendered`, still explicitly NOT implemented — see ADR-021/022's latency-baseline
caveats) has a join key across the pipeline once Sprint 2 exists. This is deliberately
a thin, additive mechanism: it does not change what gets logged beyond adding one
field, and it does not yet drive any behavior — it is purely for correlation.

## ADR-034 — Turn processing transaction boundary: atomic, idempotent, effectively-once — not "exactly-once"
Status: accepted

Provider-Ready Gate finalization hardening. The concern this ADR answers: could a
turn be claimed (via `ProcessedTurnEvent`/`claim_turn()`, ADR-031) and then lost —
i.e. the claim persists, but the process crashes before the ConversationState update,
`ConversationStateEvent`, or `Suggestion`/`Turn` row is written, so a retry is
discarded as "already handled" even though nothing useful actually happened?

**It cannot, by construction.** Every turn-processing endpoint (`POST
/api/calls/{id}/turns`, `POST /api/copilot/suggest`) uses exactly one SQLAlchemy
`Session` for the whole request (`app/db.py`'s `get_db()` dependency) and calls
`db.commit()` exactly once, at the very end of its success path — after the claim,
the ConversationState update, the `ConversationStateEvent` insert, and the
`Turn`/`Suggestion` insert have all been queued on that same session. Concretely, in
`copilot()`: `claim_turn()` -> `suggest_with_state()` (pure, no DB) ->
`_apply_state_to_row()` -> `_record_state_event()` -> `Suggestion(...)` -> `db.add()`
-> `record_result()` -> **one** `db.commit()`. `add_turn()` follows the identical
shape. Nothing in between commits independently — `log_audit()` explicitly documents
that it does not commit, matching this pattern.

This has two consequences under failure:
1. **A crash or unhandled exception before that commit rolls back everything
   together**, including the claim. `get_db()`'s `finally: db.close()` runs during
   stack unwinding regardless of how the exception propagates, and SQLAlchemy's
   `Session.close()` rolls back any open transaction; a `Session.commit()` that
   itself fails partway also triggers an automatic rollback. Either way, the DB ends
   up as if the request had never started. A retry with the same `turn_id` sees no
   existing `ProcessedTurnEvent` row and reprocesses the turn from scratch — proven by
   `tests/test_turn_processing_atomicity.py`'s crash-injection tests (crash
   immediately after claim, and crash after the ConversationState/history mutation
   but before the final commit — both leave zero rows in `Turn`/`Suggestion`/
   `ConversationStateEvent`/`ProcessedTurnEvent`, and a subsequent retry succeeds
   fully, including the state advancing exactly once).
2. **Only a fully committed attempt is ever treated as "already done."** A retry
   after a successful commit correctly finds the claim and returns the cached
   `result_ref` without reprocessing (existing dedup tests, reconfirmed here).

**Terminology, precisely** (the original Provider-Ready Gate report over-claimed
"exactly once" in several places, corrected here and in ADR-031's revised heading):
REPLICA does not and cannot guarantee **exactly-once delivery** — Twilio, a websocket
reconnect, or any HTTP client can always call an endpoint more than once for the same
real turn, and no server-side design changes that. What the transaction boundary
above guarantees is **idempotent, effectively-once processing**: the persisted
*effect* of a real turn is applied exactly once per successful attempt, and a failed
attempt is indistinguishable from "never attempted" — never half-applied, never
silently double-applied. This is the correct name for the guarantee (option A from
the hardening spec: atomic processing within one transaction), not the retry/state
model of option B (`pending`/`completed`/`failed` rows) — a separate `pending` state
was judged unnecessary because the DB transaction itself already provides the
all-or-nothing guarantee that a `pending` row would otherwise have to simulate.

**A second, independent bug found and fixed while verifying this** (via a
parallel-claim test that races two concurrent first-turns for the same call): both
`claim_turn()` (ADR-031) and `claim_webhook_delivery()` (ADR-029) originally called a
full `db.rollback()` when losing a concurrency race on their own unique constraint.
A full `Session.rollback()` discards *everything* pending in that session's
transaction, not just the failed insert — so a losing request that had already
queued unrelated work earlier in the same request (e.g. an `AuditEvent` from an
earlier `can_process()` call) would silently lose that work too. Both are now fixed
to catch the race inside a SAVEPOINT (`db.begin_nested()`), which undoes only the
failed insert and leaves everything else in the session intact. The same latent bug
existed in `_load_or_create_conversation_state_row()` (a plain get-or-create with no
race handling at all — a genuine unhandled `IntegrityError` under concurrency, not
just a wasted rollback) and is fixed the same way. All three race paths are covered
by real multi-threaded tests (not mocked), since a single in-process
check-then-insert race needs actual concurrent DB sessions to reproduce.

## ADR-035 — Twilio call-status events: duplicate identity vs. out-of-order/stale detection are separate concerns
Status: accepted

Twilio's status-callback delivery is at-least-once and **not** guaranteed in order.
Two distinct failure modes were being conflated in the original Provider-Ready Gate
webhook, and are now handled as two separate, composable layers:

**1. Event identity (is this the same event again?).** `CallSid` alone is not a
unique event identifier — a single call legitimately produces several *different*
status events over its lifetime (`queued` -> `ringing` -> `in-progress` ->
`completed`), so `external_id = CallSid` would wrongly treat all of them as retries of
the first. The fix: `external_id` incorporates Twilio's own `SequenceNumber` when
present (`f'{CallSid}:{SequenceNumber}'`) — the authoritative per-event id Twilio
itself assigns — falling back to `f'{CallSid}:{CallStatus}'` when a particular
status-callback configuration doesn't include one. Known limitation of that fallback,
documented rather than silently assumed away: without `SequenceNumber`, a call that
legitimately repeats the identical `CallStatus` twice would collide and the second
occurrence would be (incorrectly) treated as a duplicate delivery of the first. This
identity still feeds the existing `WebhookDelivery` ledger/`claim_webhook_delivery()`
(ADR-029) unchanged — a claimed duplicate is still recognized and skipped there.

**2. Ordering (is this event, even though new, actually about the past?).** A
delivery can fail the identity check above (i.e. it's genuinely new, never seen
before) and *still* describe an older point in time than what's already been applied
— e.g. a delayed `in-progress` arriving after `completed` was already processed,
because of retry/network jitter rather than a duplicate send. `app/webhooks/
call_status.py`'s `is_newer_event()` decides this, checked against a new
`CallProviderStatus` row (one per `(provider, external_call_id)`, kept deliberately
separate from `WebhookDelivery` and from `Call`'s own seller-driven business-outcome
fields — a materialized "latest applied technical status", nothing else):
1. No prior applied event for this call -> always apply (nothing to regress).
2. Both the incoming and the last-applied event carry a `SequenceNumber` -> compare
   numerically; Twilio's own order is authoritative, overriding the status values
   themselves.
3. Otherwise, once ANY terminal status (`completed`/`busy`/`failed`/`no-answer`/
   `canceled`) has been applied, it is a one-way door — nothing that follows is ever
   considered newer, sequence-number-less or not.
4. Otherwise, a coarse status-progression rank (`queued/initiated` < `ringing` <
   `in-progress/answered`) is the last-resort fallback, existing only to stop an
   out-of-order non-terminal event from misordering non-terminal progress when no
   better signal is available.

**Duplicate vs. stale, defined precisely:** a **duplicate** is a delivery whose
identity (per #1) has already been claimed — it is never reprocessed at all, and the
response is `{"duplicate": true}`. A **stale** event is a delivery that is NOT a
duplicate (new identity) but loses the ordering check (per #2) — it IS durably
recorded (the `WebhookDelivery` claim already persisted it before the ordering check
even runs, so it is never silently dropped), but it is NOT applied to
`CallProviderStatus`, and it is separately audit-logged with a `.stale` action suffix
and `"applied": false` in its payload — see `tests/test_call_status_ordering.py`'s
`test_stale_event_is_still_durably_recorded_not_silently_dropped`. This answers the
hardening spec's explicit question ("werden stale Events gespeichert, ignoriert oder
separat protokolliert?") directly: **stored AND separately logged, never silently
ignored.** The response body also reports `"applied": false` so a caller/operator
inspecting delivery logs can see the distinction without a DB query.

`get_or_create_provider_status()` uses the same SAVEPOINT-based race-safe
get-or-create pattern as `claim_turn()`/`claim_webhook_delivery()` (ADR-034) for the
(rare) case of two concurrent first-sightings of the same provider call.

## ADR-036 — Twilio signature verification delegates the cryptographic check to the official RequestValidator
Status: accepted

The original Provider-Ready Gate implementation hand-rolled the HMAC-SHA1 computation
directly in `app/webhooks/security.py`. That is functionally correct but puts REPLICA
on the hook for independently tracking every edge case Twilio's own algorithm
handles — multi-value POST parameters, the port-inclusive vs. port-stripped URL
variants Twilio's own validator checks (some Twilio infrastructure signs with an
explicit port, some without), and any future adjustment Twilio makes to the
algorithm itself. `app/webhooks/security.py` now delegates the actual cryptographic
comparison to `twilio.request_validator.RequestValidator` (the official `twilio`
PyPI package, added to `requirements.txt`) — REPLICA's own code no longer computes
or compares an HMAC digest at all; `compute_twilio_signature()` and
`verify_twilio_signature()` are now thin wrappers whose entire body is a call into
the library, kept only so the rest of the codebase (and its tests) have a stable,
REPLICA-owned import surface rather than depending on `twilio.request_validator`
everywhere.

What stays REPLICA's own responsibility, entirely in `app/main.py`'s
`twilio_call_status()` (unchanged by this switch): resolving the right secret
(`get_secrets_provider()`, ADR-028), constructing the correct public-facing request
URL, tenant/provider context, logging/audit, and fail-closed error handling
(`verify_twilio_signature()` returning `False` for a missing signature or
unresolvable token, never raising or falling back to "process anyway").

**A real correctness gap was found and fixed while doing this**, not merely a
refactor: the URL passed to the validator previously used only
`{public_base_url}{request.url.path}`, silently dropping any query string. Twilio's
signature covers "the full URL... from the protocol through the end of the query
string" — a status-callback URL configured with query parameters (common, e.g. to
carry an internal call reference) would have had its signature verification
permanently and silently broken. Fixed to
`{public_base_url}{request.url.path}?{request.url.query}` (query string included only
when present). There is still, deliberately, no fallback path: an incorrectly
configured `REPLICA_PUBLIC_BASE_URL` fails closed (403) rather than falling back to
reconstructing the URL from `request.url`, which would defeat the entire reverse-proxy
protection ADR-029 established — see `tests/test_signature_hardening.py`'s
`test_endpoint_rejects_when_configured_public_base_url_is_wrong`.

## ADR-037 — Twilio Media Streams WebSocket: the same fail-closed posture as the HTTP webhook, applied to a handshake instead of a request
Status: accepted

Sprint 2's real-time audio ingestion (`/ws/twilio-media`) opens a second inbound
channel from Twilio that the Provider-Ready Gate's webhook hardening (ADR-029/036)
never covered — a real gap the user flagged explicitly before Sprint 2 began. The
same two principles apply, adapted to a WebSocket handshake instead of a POST request:

1. **Signature verification before `accept()`.** Twilio signs the Media Streams
   connection request the same way it signs webhooks
   (`app/streaming/media_stream_security.verify_media_stream_signature()`, reusing
   the exact same official `RequestValidator` seam as ADR-036 — no second
   cryptographic implementation). The check runs, and can reject the connection,
   *before* `websocket.accept()` is ever called, so an unauthenticated caller is
   refused at the handshake, never accepted and then dropped. **Documented
   assumption, not independently verifiable from this environment**: Twilio's
   Media Streams connection has no POST body, so the parameters signed are the
   request's query-string parameters (empty if none) — this must be confirmed
   against a real Twilio Media Streams connection before pilot go-live; it is not
   silently assumed correct forever, just today, in an environment with no live
   Twilio account to test against.
2. **wss-only in production.** `is_secure_transport()` checks `X-Forwarded-Proto`
   first (a TLS-terminating reverse proxy reports its own, often plain, connection
   to REPLICA on `websocket.url.scheme` — the identical caveat as ADR-029/036's HTTP
   URL reconstruction), falling back to the scheme itself. Enforcement is gated on
   `REPLICA_ENV=production` — local/dev/test runs have no TLS-terminating proxy in
   front of them at all and must keep working over plain `ws://`; production must
   never be flexible about this.

A third fail-closed gate exists only for this streaming path: **call resolution**.
Twilio's `start` event is matched to a REPLICA `Call` via
`customParameters.replica_call_id` (set via a `<Parameter>` on the `<Stream>` TwiML
noun — unambiguous) or, failing that, `Call.external_call_id == callSid` (the same
correlation the status-callback webhook already uses). No match means REPLICA has no
tenant/jurisdiction/consent context to evaluate policy against — the connection is
closed immediately rather than processed under an unknown or default context,
consistent with every other fail-closed gate in this codebase since Sprint 0.

## ADR-038 — Media stream track separation and identity/sequence diagnostics are real signal processing, not simulated
Status: accepted

Two things needed to be true simultaneously for Sprint 2's pipeline to be honest
rather than merely working: inbound (prospect) and outbound (seller/agent) audio
must never be merged before any processing that depends on knowing who is speaking,
and the diagnostics that detect transport problems must be REAL, not asserted.

`app/streaming/media_stream_session.py`'s `MediaStreamSession` keeps a completely
separate `TrackDiagnostics` per track (`inbound`/`outbound`) from the first `media`
event onward — there is no code path where the two tracks' bytes are combined.
Sequence/identity bookkeeping is real arithmetic against Twilio's own per-track
`media.chunk` counter and per-connection `sequenceNumber`, not a placeholder:
`observe_chunk()` distinguishes a genuine gap (`missing_before`) from an exact
repeat (`duplicate`) from a never-seen-but-lower number (`out_of_order`), each with
its own counter — verified in `tests/test_streaming_media_session.py` against
constructed sequences engineered to hit exactly one of those three cases each.
`observe_timestamp()` flags a real audio gap from Twilio's own in-stream
`media.timestamp` jumping further than a couple of nominal frame durations — a
distinct signal from a sequence-number anomaly, since a reordering is not
necessarily lost audio time. `observe_processing_lag()` computes backpressure as the
growing distance between wall-clock processing time and the nominal in-stream audio
timestamp — a consumer that cannot keep up with real-time delivery shows this
growing, not constant (verified with an explicit test asserting monotonically
increasing lag under simulated slow processing). A new `start` event for an
already-known call with a *different* `streamSid` is treated as a reconnect: counted,
and per-track sequence state is reset (a fresh stream restarts its own chunk
numbering), so a reconnect does not manufacture spurious "missing chunk" noise
against the old stream's numbering.

Voice-activity detection (`app/streaming/vad.py`) is genuine signal energy, not a
heuristic on metadata: `app/streaming/mulaw.py` implements the standard ITU-T G.711
mu-law decode algorithm from scratch (verified byte-for-byte identical to the stdlib
`audioop.ulaw2lin` reference for all 256 possible byte values — see
`tests/test_streaming_dsp.py`), specifically to avoid depending on `audioop`, which
is deprecated and scheduled for removal (Python 3.13, PEP 594) — a stdlib dependency
this codebase would otherwise have to rip out again soon. `VoiceActivityDetector`
computes RMS over the actually-decoded samples and applies a fixed threshold plus a
hangover window (absorbing a natural mid-utterance pause without ending the turn).
What IS a deliberate simplification, flagged as tech debt: a fixed energy threshold
rather than an adaptive noise floor — acceptable to prove the pipeline shape, not
acceptable as-is for real telephony line noise variance in a pilot.

## ADR-039 — Turn detection: prospect/seller/overlap/speaker-change/turn-end as distinct signals; overlap is flagged, not adjudicated
Status: accepted

`app/streaming/turn_detector.py`'s `TurnDetector` is the component the Sprint 2
requirements named explicitly: REPLICA must be able to tell "prospect is speaking"
from "seller is speaking" from "both are speaking (overlap)" from "the active
speaker just changed" from "a turn just ended" as separately observable facts, not
one blended signal derived after the fact. `on_vad_update()` returns all of these as
independent booleans per call, and `on_turn_ended()` resolves a track's own
finalized utterance into exactly one `TurnEvent`.

Deliberate scope limit: who "held the floor" during genuine overlap (talking over
each other) is not algorithmically adjudicated in this sprint. Each track's
utterance still finalizes independently once THAT track's own VAD detects silence;
overlap is only flagged (`had_overlap=True` on both resulting `TurnEvent`s from an
overlapping exchange — see `tests/test_streaming_turn_detector.py`'s
`test_each_track_finalizes_independently_even_when_overlapping`), never resolved
into a single winning turn. Building a real barge-in/floor-holding model is
substantial, separate work (arguably a research problem on its own) and was
explicitly out of scope for proving Sprint 2's target pipeline shape
(Twilio call -> separated channels -> ASR -> turn detection -> one final turn ->
ConversationState -> SalesBrain -> Suggestion) — flagged here rather than silently
deferred.

## ADR-040 — process_final_turn(): the one central path Sprint 2 was asked to build toward
Status: accepted

The Provider-Ready Gate's ADR-032 predicted this explicitly: "once Sprint 2 has one
real 'final turn' event, it should call `apply_turn()` exactly once through a single
processing path." `app/services/turn_pipeline.process_final_turn()` is that path —
the *only* function `app/streaming/pipeline.py`'s `MediaStreamPipeline` calls to turn
a detected final utterance into persisted state, and the only call site of
`apply_turn()`/`suggest_with_state()` anywhere in the streaming stack.

It deliberately does NOT touch or replace the existing HTTP endpoints. `add_turn()`
and `copilot()` in `app/main.py` keep their existing two-independently-claimed-action
behavior (`'transcribe'` / `'live_assist'`) byte for byte — verified by the full,
unmodified existing test suite passing unchanged. Changing that HTTP wire contract
was out of scope for this sprint; `process_final_turn()` is a new, additional path
for the new ingestion route, claiming a distinct action value (`'final_turn'`) so its
`ProcessedTurnEvent` dedup ledger entries can never collide with the HTTP paths'.
Within that one path, transcription and live-assist remain two independently
policy-gated actions (unchanged from ADR-031/032's reasoning) — a prospect turn
whose `'transcribe'` is allowed but `'live_assist'` is not still gets its transcript
persisted, just no phase advance or `Suggestion` — collapsed into one function call
rather than one blanket permission.

To make this extraction possible without duplicating the state-loading logic
`add_turn()`/`copilot()` already had, the DB-aware `ConversationState`
load/apply/history-record helpers moved from `app/main.py` into
`app/services/conversation_state_store.py` (pure relocation, zero behavior change —
same test suite, unchanged, confirms it) so both the HTTP layer and the new
streaming layer share one implementation instead of two copies drifting apart.

Atomicity: `process_final_turn()` follows the exact same single-Session,
single-commit discipline as the HTTP endpoints (ADR-034) — policy check, the
`ProcessedTurnEvent` claim, the `Turn` row, the ConversationState update +
`ConversationStateEvent`, and (for a prospect turn) the `Suggestion` row all share
one transaction. A crash before that commit rolls everything back together, exactly
as documented in ADR-034 for the HTTP paths.

## ADR-041 — End-to-end latency instrumentation: monotonic for math, wall-clock for audit, real Fast-Path latency never called RSL
Status: accepted

`app/services/latency_trace.LatencyTrace` marks each of the nine named pipeline
stages (`audio_received`, `asr_interim`, `asr_final`, `turn_end_detected`,
`salesbrain_started`, `salesbrain_finished`, `suggestion_persisted`,
`suggestion_pushed`, `ui_rendered` — matching docs/ARCHITECTURE.md §8 and the Sprint
2 requirements exactly) with BOTH a `time.monotonic()` reading and a
`datetime.utcnow()` reading, per the explicit instruction to keep both. Every
duration/latency number persisted (`TurnLatencyTrace`'s `*_ms` columns) is computed
exclusively from the monotonic readings — immune to NTP adjustments or system clock
changes, which would otherwise silently corrupt a latency measurement mid-call. The
wall-clock `*_at` columns exist purely for audit/tracing correlation across systems
and logs; they are never used in latency arithmetic. Monotonic values themselves are
never persisted (a monotonic clock's epoch is arbitrary per-process and meaningless
after the process exits or on a different machine) — only the deltas, which is what
is actually meaningful.

`salesbrain_latency_ms` (`salesbrain_started` -> `salesbrain_finished`, bracketing
precisely the `suggest_with_state()`/`apply_turn()` call inside
`process_final_turn()`, not the surrounding DB work) is the same internal Fast-Path
engine latency measured since Sprint 1 (ADR-021/022) — now measured inside a real
pipeline instead of a synthetic benchmark, but still explicitly NOT real RSL, and
never reported as such anywhere in code, tests, or this report. `real_rsl_ms`
(`turn_end_detected` -> `ui_rendered`) is the actual product metric and stays `NULL`
until a real UI render acknowledgement exists — Sprint 2 has no UI push mechanism at
all (that is explicitly Sprint 3's deliverable per `docs/CODER_HANDOFF.md`), so
`suggestion_pushed`/`ui_rendered`/`real_rsl_ms` are left unmarked rather than
approximated. Marking them with a fabricated timestamp would manufacture a fake RSL
number, exactly what "never call internal latency real RSL" forbids — see
`tests/test_streaming_pipeline_e2e.py`'s
`test_latency_trace_stages_are_recorded_in_correct_monotonic_order`, which asserts
`real_rsl_ms is None` as a hard requirement, not an oversight.

## ADR-042 — Streaming ASR seam: interim transcripts are structurally incapable of triggering final-turn side effects
Status: accepted

`app/streaming/asr.py` introduces `ASRProvider`/`ASRStreamHandle` (the same seam
pattern as `SecretsProvider`, ADR-028) with exactly one implementation,
`SimulatedASRProvider` — not real speech recognition, and honestly labelled as such:
an utterance the caller didn't pre-register via `script` comes back as an
unmistakably fake placeholder string (`PLACEHOLDER_TEXT`), never something that
could pass for a plausible-but-wrong transcript. No live ASR vendor is reachable
from this environment; the seam exists so a real one (Deepgram, Google STT, Twilio
Voice Intelligence, OpenAI Realtime transcription, ...) drops in later without
touching turn detection or the central processing path.

The requirement this ADR is really about: an interim transcript must never itself
produce a final ConversationState transition, a Cold Call Genome event, or a
duplicate Suggestion. This is enforced structurally, not by convention —
`MediaStreamPipeline._on_interim()` (`app/streaming/pipeline.py`) is the ENTIRE
interim-transcript code path, and it has no DB session, no reference to
`process_final_turn`, and no reference to `apply_turn` anywhere in its call stack; it
can only ever update an in-memory preview value. There is exactly one call site of
`process_final_turn()` in the whole pipeline module, reached only from
`_handle_silence()`, itself only reachable when a track's OWN `VoiceActivityDetector`
transitions from speaking to silent. `tests/test_streaming_pipeline_e2e.py`'s
`test_interim_transcripts_create_no_side_effects_before_turn_end` proves this at the
full-stack level: a full second of continuous simulated speech (dozens of interim
events) produces zero `Turn`/`Suggestion`/`ConversationStateEvent` rows until the
track actually falls silent, at which point exactly one of each appears.

## ADR-043 — Track-to-speaker mapping is resolved, never hardcoded, and scoped to one explicit call topology
Status: accepted

Sprint 2B closes a real gap the user flagged explicitly: Sprint 2's `TurnDetector`
had `TRACK_TO_SPEAKER = {inbound: 'prospect', outbound: 'seller'}` baked in as a
module constant. That is a transport-level assumption dressed up as a business
fact — Twilio's `inbound`/`outbound` labels mean "audio arriving at Twilio from the
far end" / "audio Twilio sends to the far end", which only maps to
`prospect`/`seller` for ONE specific call topology (REPLICA's own defined outbound
cold-calling flow: the seller calls the prospect via Twilio and the seller's own
voice is bridged onto that same leg). A different topology — inbound lead response,
a conference bridge, a warm transfer — would silently mislabel every turn under the
old hardcoded mapping, with no error and no way to notice.

`app/streaming/speaker_mapping.py` makes this an explicit, injectable step:
`SpeakerRoleResolver` (a `Protocol`) with exactly one implementation,
`OutboundSalesFlowResolver`, whose name and `TOPOLOGY_NAME` attribute state the
scope restriction directly rather than leaving it implicit. `TurnDetector` now
takes a `speaker_role_resolver` (defaulting to
`get_default_speaker_role_resolver()`, i.e. today's only supported topology) instead
of importing the constant — a future topology gets its own resolver class and a way
to select it, never a second hardcoded dict competing with the first. This is a
pure refactor for today's behavior (verified: the full pre-existing
`tests/test_streaming_turn_detector.py` suite passes unmodified against the new
default) whose entire purpose is to make the NEXT topology change a one-class
addition instead of a silent mislabelling risk.

**Explicit restriction, stated once here as the canonical reference**: REPLICA's
real-time pipeline supports exactly one call topology today — one prospect leg
(`inbound`) and one seller/agent leg (`outbound`) bridged directly onto a single
outbound call REPLICA/the seller initiated, no additional parties. Any other
topology is unverified and must not be assumed to work without a new resolver and
new field testing.

## ADR-044 — Streaming ASR seam goes async: real providers and the simulator do not share a synchronous request/response shape
Status: accepted

`app/streaming/asr.py`'s original (Sprint 2) `ASRStreamHandle.feed_audio()` returned
an `ASREvent | None` synchronously, on the assumption that a result is available
immediately after feeding one chunk — true for `SimulatedASRProvider` (no real I/O)
but false for any real streaming vendor: Deepgram's transcripts arrive over an
independent, asynchronous WebSocket connection, decoupled in time from when audio
chunks are sent. Retrofitting this after building `DeepgramASRProvider` would have
violated the explicit instruction that Sprint 2B's architecture "so vorbereitet sein
[soll], dass wir später nur Credentials/Deployment-Konfiguration ergänzen müssen und
keine Kernlogik mehr umbauen müssen" (prepared so only credentials/deployment config
remain to add later, not core-logic rework) — so the protocol was redesigned now,
before Deepgram wiring, not after.

New shape: `async def feed_audio(payload, *, is_speaking)` (push, never blocks on a
result), `async def poll_events() -> list[ASREvent]` (non-blocking drain of whatever
arrived since the last call), `async def finalize() -> ASREvent | None` (called only
by our own VAD-driven silence detection; for a real provider this actively prompts
the provider to flush and waits briefly), `async def close()`. `is_speaking` stays a
parameter for protocol-compatibility with `SimulatedASRProvider` (which has no other
way to know when a "speaker" starts/stops) — a real provider's handle accepts and
ignores it, since the provider does its own voice-activity handling internally.

`SimulatedASRProvider`'s observable behavior is unchanged (interim events grow
word-by-word while "speaking", finalize returns the full accumulated text) — only
its plumbing became `async def`, verified by the full pre-existing ASR test suite
passing against the same assertions, now driven via `asyncio.run()` (no new pytest
plugin dependency added for this — see `tests/test_streaming_asr.py`).
`app/streaming/pipeline.py`'s `consume_media()`/`consume_stop()` are `async def` now
too, and `MediaStreamPipeline` gained an async `create()` factory (construction
needs to `await asr_provider.start_stream()` per track) — `app/main.py`'s WebSocket
loop awaits all of it.

## ADR-045 — Deepgram adapter: implemented per documented protocol, never verified against a live account, fails closed to the simulator
Status: accepted

Sprint 2B's explicit, narrow goal for this item was "jetzt Code, Adapter,
Konfiguration, Tests und Dokumentation... vorbereiten" — NOT to claim a working
integration, since no Deepgram account/API key exists in this environment. Read this
ADR alongside `app/streaming/deepgram_provider.py`'s own extensive docstring, which
carries the same caveat at the point of use.

`DeepgramASRProvider`/`DeepgramStreamHandle` implement the `ASRProvider`/
`ASRStreamHandle` protocol (ADR-044) against Deepgram's publicly documented
streaming API: `wss://api.eu.deepgram.com/v1/listen` (EU region, per the explicit
request — `api.deepgram.com` otherwise), `model=nova-3`, `language=de`,
`interim_results=true`, `mip_opt_out=true`, plus the audio-format parameters
Deepgram needs to interpret Twilio's own default format correctly
(`encoding=mulaw&sample_rate=8000&channels=1` — necessary for correctness, not
optional). `Authorization: Token <key>` on the WebSocket handshake. Keyterm
prompting (`keyterm=...`, repeatable) is wired as a constructor parameter
(`keyterms`) but populated with nothing today — "technisch vorbereiten", per the
request, for company/product/competitor terms once decided. Reconnection uses a
short bounded backoff (`0.5s, 1.5s, 3.0s`) and degrades gracefully — a failed
connection, or one that drops mid-stream, logs and returns empty results rather than
raising into the pipeline; one track's ASR failing must never crash the whole call's
turn processing or the other track.

Turn-end authority is unchanged (ADR-039/042): `finalize()` is called ONLY by our
own VAD detecting silence, never by Deepgram's own signals. When called, it sends
Deepgram's documented `Finalize` control message (flush now, without closing the
connection) and waits up to `1.5s` for the resulting final transcript before
returning whatever has accumulated — bounded, because a slow/unresponsive external
service must never block the pipeline indefinitely. `close()` sends the documented
`CloseStream` control message.

`app/streaming/asr.get_asr_provider()` selects the provider from
`REPLICA_ASR_PROVIDER` (default `'simulated'`, needs no credentials).
`REPLICA_ASR_PROVIDER=deepgram` without `DEEPGRAM_API_KEY` set logs a loud error and
**falls back to `SimulatedASRProvider`** rather than attempting an unauthenticated
connection — fail-safe, consistent with this codebase's fail-closed posture
everywhere else, and exactly what makes it safe to merge this adapter into the
default branch before real credentials exist: nothing changes for anyone who hasn't
configured Deepgram.

**What "tested" means here, precisely**: `tests/test_streaming_deepgram_provider.py`
runs the adapter against a small local WebSocket server
(`tests/test_streaming_deepgram_provider.py::FakeDeepgramServer`) that speaks the
same documented message shapes (`Results`, `UtteranceEnd`, `Finalize`,
`CloseStream`). This proves the ADAPTER's own logic — URL construction, message
parsing, event mapping into `ASREvent`, the Finalize round-trip, graceful
degradation on connect failure and mid-stream disconnect — is internally correct
against that assumed protocol shape. **It does not prove the real Deepgram service
behaves exactly as assumed.** That verification is explicitly open — see the Sprint
2B report — and requires a real `DEEPGRAM_API_KEY` and a real audio stream, neither
of which exist in this environment.

`TurnLatencyTrace.asr_provider`/`.is_synthetic` (new columns, this ADR) make it
impossible to later confuse a `SimulatedASRProvider` row with a
`DeepgramASRProvider` row when querying historical data — every row states which
produced it, defaulting to the honest `'simulated'`/`True` so a caller that forgets
to pass them explicitly never accidentally mislabels a dev measurement as real.

## ADR-046 — Provider-native endpointing is captured for comparison, never authoritative
Status: accepted

Deepgram (like most streaming ASR vendors) does its own voice-activity/endpointing
and surfaces it as `speech_final: true` on a `Results` message, or via a separate
`UtteranceEnd` message when configured. The Sprint 2B requirements are explicit that
our existing fixed-threshold VAD (`app/streaming/vad.py`) stays the sole authority
for turn-end decisions until real test calls justify a change — "nicht vorschnell
ersetzen" (not replaced prematurely) — but that we should be ABLE to measure how it
compares.

`ASREvent.provider_speech_final` (new field, ADR-044) carries this signal through
from the adapter. `app/streaming/pipeline.py`'s `consume_media()` marks a new
`provider_endpoint_detected` stage on the turn's `LatencyTrace`
(`app/services/latency_trace.py`, ADR-041) the first time it sees
`provider_speech_final=True` for the in-progress utterance — using THAT event's own
timestamp, not the moment we happened to poll for it. `TurnLatencyTrace` persists
both `t_provider_endpoint_detected_at` (wall-clock) and
`provider_endpoint_vs_turn_end_ms` (`t_turn_end_detected - t_provider_endpoint_detected`,
monotonic-derived: positive means our VAD fired after Deepgram's own endpointing,
negative means before). Nothing about turn detection itself reads this value — it
exists purely so that, once real test calls exist, this comparison can be pulled
straight out of the data (per requirement 4: "erst anhand dieser Messungen
entscheiden") instead of requiring new instrumentation at that point.

## ADR-047 — Unidirectional media streaming: REPLICA only listens, enforced structurally and by TwiML configuration
Status: accepted

The current REPLICA assist MVP never sends audio into a call — no autonomous or
bidirectional voice capability exists yet, and none is in scope here. Twilio Media
Streams has two distinct TwiML shapes: `<Connect><Stream>`, which REPLACES the
call's own bidirectional media path (for a voice agent that needs to talk back), and
`<Start><Stream>`, which opens a PARALLEL, listen-only side-channel while the call's
normal audio continues untouched. REPLICA's required configuration is `<Start>
<Stream url="wss://.../ws/twilio-media" track="both_tracks"><Parameter
name="replica_call_id" value="..." /></Stream></Start>` — documented in
`docs/INTEGRATIONS.md` — never `<Connect><Stream>`.

This was already true of every line of code written in Sprint 2 (the WebSocket
handler only ever calls `receive_text()`; there was never a `send_text()`/
`send_bytes()` call anywhere in the media-stream code path), so Sprint 2B's
contribution is making that guarantee explicit and verified rather than merely
incidental: `tests/test_streaming_pipeline_e2e.py`'s
`test_media_stream_never_sends_audio_back_to_twilio` monkeypatches
`WebSocket.send_text`/`send_bytes`/`send_json` to raise, then runs a full
golden-path simulated call through the real endpoint end to end — proving no code
path attempts to send, rather than merely observing that none currently does.

## ADR-048 — Live Suggestion Push + Render-ACK: WS auth over the message channel, wall-clock RSL, browser is the only source of `t_ui_rendered`
Status: accepted

Sprint 3A needs the last technical stretch for a real end-to-end RSL measurement:
a persisted Suggestion pushed to the seller's browser, and a real (not estimated)
timestamp for when it was actually painted.

**Push transport and auth.** `app/services/live_push.LiveSuggestionHub` is an
in-process, call_id-scoped WebSocket registry; `/ws/live/{call_id}`
(`app/main.py`) is the browser-facing endpoint. Unlike the Twilio media stream
(authenticated via `X-Twilio-Signature` before `accept()`, since Twilio can set
custom headers), a browser WebSocket client cannot set a custom `Authorization`
header on the handshake, and a bearer token in the URL query string risks being
captured in reverse-proxy/CDN access logs. The endpoint therefore accepts the
connection, then requires the FIRST message to be `{"type": "auth", "token":
"<JWT>"}` within a short timeout — functionally the same fail-closed posture
(unauthenticated connections are never left open or processed), carried over the
WS message channel instead of HTTP headers. Tenant isolation is enforced twice
redundantly: once when the endpoint registers a subscriber (only ever with the
company_id it verified from that subscriber's own JWT), and again inside
`LiveSuggestionHub.publish_suggestion()` itself before every send — a bug in
either place alone still cannot cause a cross-tenant delivery. A wrong-tenant or
nonexistent `call_id` both just close the connection with the same code, mirroring
`_get_call_or_404()`'s "never distinguishable" posture.

**Handoff, not delivery confirmation.** `t_suggestion_pushed_at` is marked the
moment `app/streaming/pipeline.py`'s `_process_turn()` calls
`hub.publish_suggestion(...)` — not when (or whether) a browser actually receives
it. Zero connected subscribers is a legitimate outcome (the seller's tab isn't
open yet), not a failed handoff; the persisted Suggestion genuinely was handed to
the live-delivery layer either way. This matches the requirement's own wording
("übergeben an den Live-Delivery-Layer", not "empfangen").

**Reconnect and no-duplicate-display.** No backlog/replay queue of everything
missed while disconnected — a reconnecting client's very next message is a `sync`
frame carrying only the MOST RECENT suggestion for that call (guidance is
inherently "latest wins" once a conversation has moved on; a full backlog is
tracked tech debt, not needed for Sprint 3A's narrow scope). The browser
(`app/static/live.html`) dedupes by `suggestion_id`: a `sync` resending the
suggestion already on screen is a no-op, never a re-render or a second Render-ACK.

**Render-ACK is a separate, reliable HTTP POST, not a WS message.** `POST
/api/suggestions/{id}/render-ack` carries the browser's own measurements — deliberately
NOT sent back over the same WebSocket, so a momentarily flaky live-push connection
can never silently swallow the one signal Sprint 3A most needs. The ACK carries
two independent timestamp pairs, never mixed: `client_received_perf_ms`/
`client_rendered_perf_ms` (the browser's own `performance.now()`, monotonic,
browser-local) produce `client_render_latency_ms` — "how long did the browser take
to paint it", a pure client-side diagnostic. `client_received_epoch_ms`/
`client_rendered_epoch_ms` (`Date.now()`, wall-clock) are converted to
`t_browser_received_at`/`t_ui_rendered_at` and used for `real_rsl_ms =
t_ui_rendered_at - t_turn_end_detected_at` — a WALL-CLOCK delta, the only
comparison possible between this server and the browser, since they are different
processes (usually different machines) with no shared monotonic clock. This is
explicitly allowed by the brief ("Wall-Clock kann zusätzlich für
Korrelation/Audit vorhanden sein") and inherits ordinary NTP clock-skew risk
between the two machines as a documented limitation, not an oversight.
`real_rsl_ms` stays NULL until this endpoint actually fires for a given trace —
never approximated, never backfilled from the pipeline side.

`app/static/live.html` measures `client_rendered_*` via a double
`requestAnimationFrame` after the DOM update — a standard, low-overhead
approximation for "actually painted" without the added complexity of the Paint
Timing API; documented as an approximation, not treated as pixel-exact.

## ADR-049 — Twilio EU region/edge (`ie1`/`dublin`) never silently falls back to the SDK's own `us1` default
Status: accepted

The Twilio Python SDK's `Client(...)` defaults to the `us1` region/edge when
`region`/`edge` are omitted from its constructor — exactly the silent US1 fallback
the pilot's EU data-residency requirement forbids. REPLICA does not yet call
Twilio's REST API anywhere (it only RECEIVES webhooks and Media Streams, which
target `REPLICA_PUBLIC_BASE_URL` and have no Twilio-region concept of their own),
so there is no existing call site to fix — but Sprint 3A prepares the seam now so
a later feature that DOES call Twilio's REST API (e.g. originating a call) cannot
reintroduce the mistake by omission.

`app/integrations/twilio_rest.get_twilio_rest_client()` is the single factory for
any future Twilio REST client construction; it raises `ValueError` rather than
constructing a client if `TWILIO_REGION`/`TWILIO_EDGE` are not both explicitly
configured (`app/config.py` defaults them to `ie1`/`dublin` already for the EU
pilot) — the same fail-closed posture as `app/secrets.py` and
`app/webhooks/security.py` use for credential resolution elsewhere in this
codebase. Deepgram's own EU configuration (`api.eu.deepgram.com`, `region='eu'`
default, ADR-045) already satisfied this same requirement from Sprint 2B onward;
this ADR is Twilio catching up to the same standard, prepared ahead of the
feature that will need it, per the explicit instruction not to wait for
credentials before doing the preparation work.

## ADR-050 — Audio path checked: no unnecessary transcoding exists on the ASR path
Status: accepted (verification only, no code change)

Sprint 3A asked whether the current pipeline unnecessarily transcodes audio
before handing it to the streaming ASR provider, given that Twilio Media Streams
already deliver G.711 mu-law at 8kHz and Deepgram's streaming API accepts raw
mu-law directly (`encoding=mulaw&sample_rate=8000`, already how
`app/streaming/deepgram_provider._build_url()` configures the connection).

Verified by reading, not by changing anything: `app/streaming/media_stream_
session.py`'s `consume_media()` base64-decodes the wire payload into raw mu-law
bytes (`payload_bytes`) and does nothing else to it. `app/streaming/pipeline.py`'s
`consume_media()` then does exactly the two things the brief describes as the
efficient shape, in parallel, from that SAME `payload_bytes` value:
1. Feeds it directly to `self.asr_handles[track].feed_audio(chunk_info
   ['payload_bytes'], ...)` — `DeepgramStreamHandle.feed_audio()`
   (`app/streaming/deepgram_provider.py`) sends these bytes over the WebSocket
   completely unmodified (`await self._connection.send(payload)`). Raw Twilio
   mu-law reaches Deepgram with zero transcoding in between.
2. Separately calls `self.vads[track].process_chunk(chunk_info['payload_bytes'])`
   — `VoiceActivityDetector.process_chunk()` (`app/streaming/vad.py`) decodes
   that SAME mu-law payload to linear PCM (`app/streaming/mulaw.decode()`) purely
   to compute RMS energy for local turn detection. This decode is necessary (VAD
   needs real signal energy) and is local, in-process, negligible-cost integer
   arithmetic — not a network-facing transcode, and it never touches what is sent
   to Deepgram.

No unnecessary transcoding exists today; no code change was made. The pipeline
already matches the "raw mu-law → ASR, and in parallel mu-law → PCM decode →
local VAD" shape the brief asked to verify.

## ADR-051 — Fix-Sprint after Sprint 3A: cross-clock RSL honesty, split push timestamps, WS Origin allowlist, deployment topology documented
Status: accepted

Before the first real provider test call, a small measurement/security fix pass
addressed four gaps found in Sprint 3A's own Live Suggestion Push / Render-ACK
work — none of them new features, all of them precision/safety corrections on
what Sprint 3A already built.

**1. Cross-clock RSL was named too confidently.** Sprint 3A's `real_rsl_ms`
compared a server wall-clock timestamp against a browser `Date.now()` timestamp
— two different machines with no shared clock — and called the result "the
actual product metric" without qualifying it as an estimate. Renamed to
`wallclock_rsl_estimate_ms` (same computation: `t_ui_rendered -
t_turn_end_detected`), so the name itself now states the caveat. Added, computed
entirely server-side from two `time.monotonic()` readings on the SAME process
(never crosses a clock boundary): `server_render_ack_latency_ms` — a robust
UPPER BOUND that deliberately includes the Render-ACK HTTP round trip. Together
these give two honestly-different numbers instead of one falsely-precise one:
an estimate with unknown clock-skew error, and a bound that is monotonic-exact
but intentionally pessimistic. `t_turn_end_detected_monotonic` is now the one
deliberate exception to this codebase's "never persist a monotonic value" rule
(see `app/models.py`'s `TurnLatencyTrace` docstring) — needed to compute the
upper bound when the Render-ACK arrives as a separate, later request; a negative
computed delta (the signature of a process restart in between) is discarded
rather than persisted as a nonsensical negative latency.

Also prepared, not yet used: `app/services/clock_sync.py`'s
`estimate_clock_sync()`, a pure NTP-style four-timestamp offset/RTT/uncertainty
calculation. `/ws/live/{call_id}` now answers a `{"type":"ping",
"t1_client_send_ms":...}` message with `{"type":"pong", "t2_server_recv_ms":...,
"t3_server_send_ms":...}`; `app/static/live.html` fires a handful of these right
after connecting and attaches the raw four-timestamp samples to its next
Render-ACK. The SERVER computes the offset/RTT/uncertainty from these raw
values (`SuggestionRenderAckRequest.clock_sync_samples`) — deliberately not
trusting a client-computed aggregate, so there is one shared, unit-tested
implementation rather than parallel client/server arithmetic that could drift
apart. Persisted as `clock_offset_estimate_ms`/`clock_rtt_estimate_ms`/
`clock_uncertainty_ms`, purely for later analysis — nothing in this codebase yet
uses them to correct `wallclock_rsl_estimate_ms`, per explicit instruction that
a genuinely clock-corrected RSL is future work once this data exists.

**2. Push-timestamp terminology conflated two moments.** Sprint 3A's
`t_suggestion_pushed_at` was set the instant `LiveSuggestionHub.
publish_suggestion()` was CALLED, which is "handed to the hub", not necessarily
"actually sent over the wire". Renamed to `t_push_enqueued_at` and added
`t_ws_send_completed_at` (set once every currently-connected subscriber's
`send_json()` call has completed) plus a new `ws_send_latency_ms` duration
column — separating hub/event-loop-scheduling latency from network/browser
latency, exactly the "Hub-, Netzwerk- und Browser-Latenz getrennt
diagnostizieren" requirement. `t_render_ack_received_at` (server wall-clock,
set when the Render-ACK HTTP request is processed) is now also distinct from
`t_ui_rendered_at` (the BROWSER's own reported render moment) — five genuinely
different points in the pipeline where Sprint 3A had three.

**3. WebSocket Origin allowlist.** `/ws/live/{call_id}`'s first-message JWT
auth (ADR-048) proves WHO is connecting; it says nothing about WHERE the
connecting page is served from. `app/services/ws_origin.py` adds an `Origin`
header check against a configurable allowlist (`REPLICA_ALLOWED_WS_ORIGINS`),
checked immediately after `accept()`, before even the auth-message wait. Fails
closed outside local dev: an empty/unset allowlist in `production`/`staging`
(or any env value other than `local`) rejects EVERY origin, never "allow
everything" — a real deployment must explicitly configure its actual origin(s).
Local dev keeps working unchanged (no Origin header exists in most local/test
setups, and there is no real reverse-proxy/origin story to validate against
there anyway — the same reasoning `app/streaming/media_stream_security.
is_secure_transport()` already uses for wss enforcement). The existing
first-message JWT auth is unchanged and remains the primary defense; this is a
second, independent layer on top, not a replacement.

**4. LiveSuggestionHub's single-instance scope, made an explicit deployment
requirement, not just a code comment.** The hub was already documented in its
own module docstring as in-process/single-instance; `docs/DEPLOYMENT.md` (new)
states this as an operational REQUIREMENT for the pilot deployment topology
(single instance, or call_id-sticky routing if multiple processes are ever
used) rather than leaving it as something only a developer reading
`live_push.py` would know. No Redis/NATS/other backplane was built — explicitly
out of scope, per instruction, until it is actually needed.

None of the four points above change SalesBrain, ConversationState, or the
turn-detection/ASR pipeline — this is entirely measurement-precision and
transport-security hardening on top of what Sprint 3A already built, ahead of
the first real Twilio IE1 + Deepgram EU provider test call.

## ADR-052 — Follow-up review of ADR-051: Origin check moved before accept(); monotonic comparability verified, not assumed
Status: accepted

Two corrections to ADR-051's own implementation, raised on review, both fixed
before the first real provider test call.

**1. Origin check now runs before `websocket.accept()`.** ADR-051 added the
`Origin` allowlist check on `/ws/live/{call_id}`, but the original
implementation called `accept()` first and closed immediately afterward if the
origin was disallowed — functionally rejecting the connection, but only after
briefly accepting it. An ASGI WebSocket's headers (including `Origin`) are
available from the connection `scope` immediately, before any accept/close
call — exactly like the Twilio media stream's `X-Twilio-Signature` check, which
already ran before `accept()` from Sprint 2 onward. The check is now ordered to
match: reject-and-`close()` for a disallowed origin happens BEFORE `accept()`,
so a disallowed origin never receives an accepted WebSocket connection at all.
`websocket.close()` is valid to call pre-accept per ASGI — sending
`websocket.close` instead of `websocket.accept` in response to the initial
`websocket.connect` message IS the standard way a server rejects a WebSocket
handshake. Proven by
`tests/test_live_suggestions_ws.py::test_ws_rejects_disallowed_origin_before_accepting_the_connection`,
which structurally distinguishes "rejected at handshake" from "accepted then
closed" (verified to fail under the old, since-fixed ordering before being kept
as a regression guard) — the same proof style already used for the Twilio media
stream's own pre-accept rejection tests.

**2. `server_render_ack_latency_ms` comparability is now VERIFIED, not assumed.**
ADR-051 discarded a negative computed delta as a heuristic sign of a process
restart between turn-end and the Render-ACK, but relied on the pilot's
single-instance/sticky deployment topology (`docs/DEPLOYMENT.md`) as an
*assumption* that `t_turn_end_detected_monotonic` and the Render-ACK's own
`time.monotonic()` reading came from the same runtime — true in the common
case, but not actually checked. `app/services/latency_trace.RUNTIME_BOOT_ID` (a
random id generated once per process start) is now stamped alongside
`t_turn_end_detected_monotonic` (new column
`t_turn_end_detected_monotonic_runtime_id`, migration `d93903408234`); the
Render-ACK endpoint compares it against its OWN process's current
`RUNTIME_BOOT_ID` before computing `server_render_ack_latency_ms` at all. A
mismatch — a restart, a host change, or (in a misconfigured multi-instance
deployment) a different instance receiving the Render-ACK — means comparability
cannot be verified, and the value is simply never computed for that row (never
fabricated from an unverifiable comparison), logged as a warning for
operational visibility. The pre-existing negative-delta check remains as a
secondary defensive net for the case where the ids somehow match but the
comparison is still nonsensical (should not happen, checked anyway). This
directly implements the requirement that a host change, multi-instance
deployment, or incompatible monotonic time base must never silently produce a
latency value — verified structurally, not just documented, and covered by
`tests/test_live_suggestions_ws.py::test_render_ack_discards_server_upper_bound_on_runtime_id_mismatch`.

Neither change touches SalesBrain, ConversationState, or the ASR/turn-detection
pipeline.

## ADR-053 — Speaker-role mapping corrected for the confirmed first-real-test topology: inbound = seller, outbound = prospect
Status: accepted

ADR-043 introduced `OutboundSalesFlowResolver` to make the inbound/outbound-to-
prospect/seller mapping explicit and injectable instead of a hardcoded constant
— exactly so a topology correction like this one could be a one-place fix
instead of a silent, undetectable mislabelling. That correction has now
happened, ahead of the first real test call, before any real data existed to
be affected by it.

**What changed and why.** ADR-043's own prose assumed a call flow where Twilio
originates the call TO the prospect (e.g. via REST API) with the seller bridged
in separately, giving `inbound = prospect`, `outbound = seller`. The actual,
concrete first-test topology is different and now confirmed: the **seller**
calls REPLICA's Twilio number directly (becoming the PARENT call), TwiML then
executes `<Start><Stream track="both_tracks">` followed by `<Dial>` to the
consenting prospect test person's number (creating the DIALED-OUT child leg).
On that parent call's Media Stream, per Twilio's documented track semantics for
a `<Dial>`-bridged call: `inbound` = audio Twilio receives from whoever
originated/is connected on the parent call = the **seller** (the one who
called in); `outbound` = audio Twilio sends onward on that same call, which
once the `<Dial>` leg connects carries the far end's voice = the **prospect**.
This is the exact reverse of ADR-043's original assumption.

**What changed in code**: `OutboundSalesFlowResolver.resolve()`
(`app/streaming/speaker_mapping.py`) now returns `'seller'` for `INBOUND` and
`'prospect'` for `OUTBOUND` — a straight swap of the two return values, nothing
else. `TOPOLOGY_NAME` was bumped from `'outbound_sales_flow_v1'` to
`'outbound_sales_flow_v2'` so any future data can be unambiguously traced to
which mapping direction produced it — moot for existing data since no real
test call has happened yet under either version, but the right discipline
going forward regardless.

**Tests updated to match** (`tests/test_streaming_speaker_mapping.py`,
`tests/test_streaming_turn_detector.py`, `tests/test_streaming_pipeline_e2e.py`):
every test that previously used the `inbound` track to stand in for "the
prospect" (in order to trigger `process_final_turn()`'s prospect-only
Suggestion/live-push path) now uses `outbound` for that role instead, and vice
versa where a test specifically exercised seller-turn bookkeeping. This is a
mechanical consequence of the resolver swap, not a change in what each test
verifies.

**What did NOT change**: the resolver's scope restriction itself (still exactly
one supported topology, still explicitly out of scope for any other call shape
— see ADR-043), the `SpeakerRoleResolver` injection mechanism, `TurnDetector`,
`process_final_turn()`, SalesBrain, or ConversationState. This is a corrected
constant behind an already-existing seam, not a new mechanism.

**Still unverified, stated plainly**: this mapping direction is based on
Twilio's documented Media Streams track semantics for a `<Dial>`-bridged
parent call, reviewed ahead of the first real test — it has never been
confirmed against a live call. The first real test call's own persisted `Turn`
rows (`GET /api/calls/{id}/review`, no new code needed) are the actual
verification step, per `docs/REAL_TEST_SETUP.md`'s preflight checklist: check
which `Turn.speaker` values match who actually said what once real audio has
gone through the pipeline, precisely the kind of field verification ADR-043
itself called for rather than trusting either direction on paper alone.

## ADR-054 — Preflight correction: statusCallback belongs on `<Number>`, not `<Dial>`; call-status webhook now correlates via `ParentCallSid` for a child PSTN leg
Status: accepted

A further pre-deployment review of the finalized TwiML (`docs/REAL_TEST_SETUP.md`
§4) against current official Twilio documentation found the TwiML itself
correct in every respect settled by ADR-053 (`<Start><Stream track="both_tracks">`
topology, `inbound = seller`/`outbound = prospect`, `replica_call_id` via
`<Stream><Parameter>`), but one attribute placement was wrong.

**What was wrong.** The TwiML in `docs/REAL_TEST_SETUP.md` (as of the previous
revision) attached `statusCallback`/`statusCallbackMethod`/`statusCallbackEvent`
to `<Dial>`. For a PSTN call placed via `<Dial><Number>`, Twilio's documented
attribute set for these three attributes belongs on `<Number>` itself, not on
the enclosing `<Dial>` verb — `<Dial>`-level status callbacks describe a
different, more limited event set than a `<Number>`-level one. The TwiML in
§4 has been corrected to:
```xml
<Dial>
  <Number statusCallback="..." statusCallbackMethod="POST"
          statusCallbackEvent="initiated ringing answered completed">
    <PROSPECT_TEST_PERSON_NUMBER>
  </Number>
</Dial>
```

**Why this matters for correlation, and what else it broke.** A
`<Number>`-level statusCallback fires for the DIALED-OUT (Prospect) child call
leg specifically — Twilio delivers `CallSid` as that CHILD leg's own SID, and
additionally sends `ParentCallSid`, pointing back at the original Parent call
(the Seller's call, the one the Media Stream runs on). The existing
`POST /webhooks/twilio/call-status` handler (`app/main.py`) had, until now,
unconditionally correlated the incoming event to a REPLICA `Call` row via
`Call.external_call_id == CallSid` — correct only when the webhook describes
the Parent call itself (e.g. attached directly to a bare `<Dial>` with no
child-level callback), and silently wrong for a `<Number>`-level child-leg
event, where `CallSid` never matches `Call.external_call_id` (which is meant
to hold the Parent call's SID) at all.

**What changed in code.** `twilio_call_status()` now reads `ParentCallSid`
from the incoming form params and correlates via
`ParentCallSid or CallSid` — using `ParentCallSid` when Twilio sends one (the
child-leg case), falling back to the pre-existing direct `CallSid` match when
it does not (the parent-level case, unchanged from before). `CallProviderStatus`
ordering/dedup, by contrast, is intentionally left keyed by the event's own
`CallSid` (unchanged) — a child leg's own status progression
(`initiated`/`ringing`/`answered`/`completed`) is independent of the parent
call's, so tracking it under the child's own SID is correct, not a bug to fix.

**Interaction with the pre-existing correlation gap.** `Call.external_call_id`
is still never written anywhere in this codebase (documented previously in
`docs/REAL_TEST_SETUP.md` and unchanged by this ADR) — so for the very first
test, `call` will still resolve to `None` regardless of this fix, and this
correction has no observable effect until that gap is separately closed. This
fix is nonetheless the correct one to make now: once `external_call_id` is
populated with the Parent call's SID (by whatever future mechanism), this
correlation will work correctly on the first try instead of silently failing
in the same way ADR-053's original speaker-mapping assumption did.

**Tests added** (`tests/test_call_status_ordering.py`):
`test_child_leg_status_callback_correlates_via_parent_call_sid` (a `Call` row
with `external_call_id='CAparent1'`, a status event with
`CallSid='CAchild1', ParentCallSid='CAparent1'`, asserts the event correlates
to that `Call` and `CallProviderStatus` is keyed by `'CAchild1'`) and
`test_parent_level_status_callback_without_parent_call_sid_still_correlates_directly`
(no `ParentCallSid` present — the pre-existing direct-match behavior is
unchanged). Full regression: 272/272 (SQLite and PostgreSQL 16).

**Scope discipline.** This is a one-line correlation-key fix behind an
already-existing endpoint and a doc/TwiML correction — no new endpoint, no new
model, no new webhook event type, per the explicit instruction not to
introduce further features or architecture changes during preflight.

## ADR-055 — First real-provider attempt: genuine Twilio Trial findings, no code changes, session paused at "buy a number"

Status: accepted (informational — records findings and a resume point, not a design decision)

This session attempted the actual first real-provider test (Twilio + Deepgram,
per `docs/REAL_TEST_SETUP.md`) for the first time, live against real Twilio
and Deepgram accounts. It surfaced several genuine, previously-undocumented
or incorrectly-assumed facts about Twilio's Trial account behavior. None of
them required or received a code change — they are dashboard/account-level
facts, recorded here exactly because this project's discipline (see ADR-043,
ADR-053) is to never let a provider assumption stand unverified once reality
disagrees with it.

**What was confirmed, live, correcting this session's own earlier guidance:**

1. **`<Start><Stream>` in custom TwiML IS blocked on a Trial account**, not
   just `<Dial><Number>`. An earlier point in this session had walked this
   back in chat (based on a web search that didn't distinguish "the Media
   Streams API exists" from "the `<Stream>` TwiML verb works in a Trial
   account's own custom TwiML") — that walk-back was never committed to
   `docs/REAL_TEST_SETUP.md` (its §4 already stated the stricter, correct
   claim) and is superseded by this direct account-level confirmation.
   Twilio's own built-in "Try out Voice" trial demo uses a Twilio-owned demo
   number/flow and is unaffected by this — it proves nothing about custom
   TwiML.
2. **Buying ANY phone number requires the Pay-as-you-go upgrade**, regardless
   of destination country — confirmed by repeated, consistent errors ("This
   feature is not available on a Trial account. Please upgrade.") across
   Germany, Ireland, and US number searches.
3. **EU local numbers (Germany, Ireland) additionally require a "Regulatory
   Bundle"** — a compliance/KYC profile with address and identity information
   — even for the "Individual" profile type, even before the account is
   otherwise upgraded. A **US number restricted to Voice capability only**
   (SMS/MMS deselected in the number search) does not trigger this
   requirement, making it the simpler path for a Voice-only pilot test like
   this one's Media Stream use case.
4. **The upgrade flow itself was unreliable during this session**: the
   compliance-profile step repeatedly looped back to its own first screen,
   and a number-purchase attempt returned "An internal server error has
   occurred" from Twilio directly. Both look like Twilio-side account-review
   friction for a brand-new account attempting its first upgrade, not
   anything wrong with REPLICA's configuration — but this is genuinely
   unverified; it could not be resolved within this session.

**What did NOT change.** No source file was edited to work around any of
this — no simulated fallback, no bypass, no new environment variable to
route around the Trial restriction. The explicit instruction for this session
was to configure only, never to build a workaround for a provider account
limitation, and that held throughout.

**What WAS prepared and verified, and remains ready for the next session**
(see `docs/REAL_TEST_SETUP.md` §7 for the full resume checklist): a local
REPLICA server exposed via a Cloudflare quick tunnel (a lighter alternative
to full deployment for a single supervised test, confirmed reachable);
`.env` holding a real `TWILIO_AUTH_TOKEN` and `DEEPGRAM_API_KEY` with
`REPLICA_ASR_PROVIDER=deepgram` (verified loaded via `get_settings()`,
length-only checks — no value ever logged or committed); a TwiML Bin with a
new **solo-verification variant** — `<Start><Stream>` plus a `<Say>`/`<Pause>`,
deliberately without `<Dial>` — that lets the Media Stream, signature
verification, and real Deepgram transcription be verified end-to-end by one
person alone, before a second consenting test person is needed for the full
topology; a `Call` row with consent granted, ready for a `call_id` once a
number exists to attach.

**Secrets handling, stated plainly.** During this session's credential setup,
two Twilio Auth Token values and one Deepgram API key were briefly exposed in
the chat transcript with the operator (via terminal screenshots/copy-paste,
despite explicit guidance to avoid this) — never committed to this
repository or any file in it. The operator was advised each time to rotate
the exposed credential in the respective provider console once the session's
configuration work was confirmed working. This is an operator-side
credential-hygiene note, not a code or architecture finding, recorded here
only so it isn't lost before the rotation happens.

**Next session picks up exactly at**: complete the Twilio Pay-as-you-go
upgrade, buy a Voice-only US number, link it to the existing TwiML Bin, run
the solo verification call, then arrange a consenting Prospect test person
for the full two-person real test — closing Sprint 2B and Sprint 3A together,
per the existing plan.

## ADR-056 — `/live/{call_id}` reclassified as Sprint 3A testharness/debug view; main demo UI is the binding visual direction for the real Seller Frontend

Status: accepted (product/UX decision — no code change in this ADR)

After the Seller Frontend v1 restyle of `app/static/live.html` (previous
session) was reviewed live by the product owner on their own machine, a
product decision was made and is recorded here as binding for future work:

**Decision.** `app/static/live.html` (served at `/live/{call_id}`) is
reclassified from "first real Seller-Frontend" to what it always technically
was underneath the restyle: the Sprint 3A live-push/Render-ACK
**testharness and debug view**. It stays fully in place and keeps receiving
whatever this line of work still needs (it is the one page proving the real
WebSocket push + Render-ACK + clock-sync path end-to-end), but it is
explicitly **not** the design direction for the eventual Seller Frontend.

The product owner finds `app/static/index.html` (the existing full MVP
demo — Dashboard/Live-Copilot/Call-Review/Manager/Integrations tabs)
visually stronger and structurally more appropriate as a product surface.
**The real Seller Frontend, when it is built, should take its visual
language and structure from `index.html`**, combined with the actual
real-time mechanics already proven in Sprint 3A: the `/ws/live/{call_id}`
push, the Render-ACK round trip, and the clock-sync latency measurement
(ADR-048, ADR-051). Concretely, that means the eventual real Live-Copilot
view should look and feel like `index.html`'s "Live Copilot" tab (same
visual system: topbar, `.card`, `.suggestion`, tag row, dark theme), but be
*driven* by the live WebSocket push instead of a synchronous
`POST /api/copilot/suggest` call typed into a textarea.

**What this ADR does NOT do.** No redesign is built here. `live.html` is
unchanged by this ADR; `index.html` is unchanged. This is a documented
direction for a future sprint, not an implementation.

**Consequences for future work:**
- Sprint 3A follow-up work (real live-push, Render-ACK, clock sync) keeps
  targeting `live.html` as its proving ground — that architecture is not in
  question, only its current visual presentation.
- When the real Seller Frontend sprint starts, its starting point is a copy
  of `index.html`'s visual system, not an iteration on `live.html`'s layout.
- `live.html` should from this point on be described to non-developers as
  "the technical debug view", not as a preview of the final product, to
  avoid the exact expectation mismatch this ADR resolves.

**Unrelated finding from the same local test session, recorded for
completeness.** While debugging a failed local connection to
`/live/{call_id}`, the operator asked whether the endpoint intentionally
requires the *specific* seller assigned to the call to connect (as opposed
to any authenticated tenant user). It does not, and never has: the
`/ws/live/{call_id}` handler (`app/main.py`) only checks that the token's
user is active, has a role in `('seller', 'manager', 'tenant_admin',
'system_admin')`, and belongs to the same tenant as the call
(`call.company_id == user.company_id`) — there is no check that
`user.id == call.seller_id` or similar. A `tenant_admin` token for the same
tenant as the call is therefore expected to work exactly like a `seller`
token here; it was never the cause of that session's "Verbindung
unterbrochen" symptom. No code change resulted from this — it's a read of
already-correct, already-tested behavior, not a bug.

## ADR-057 — Root cause found and fixed: `/ws/live/{call_id}` mislabels a malformed token as "invalid or expired"; client reconnected forever on any auth failure

Status: accepted (bug fix, verified against the real running server and a real browser)

Follow-up to ADR-056's unrelated finding: the operator's `/ws/live/56`
connection kept failing even with a fresh JWT that worked immediately
against a REST endpoint, a git branch confirmed up to date, and a call
confirmed to exist. This ADR records the actual root cause, the fix, and the
concrete evidence — this session reproduced the failure against the real
code before changing anything, per this project's standing discipline (ADR-043,
ADR-053, ADR-055) of never fixing a hypothesis it hasn't first confirmed.

**Root cause, confirmed by direct reproduction.** REST authentication never
hits this bug: FastAPI's `HTTPBearer` (`app/auth/dependencies.py`) strips the
`Authorization: Bearer <token>` header's scheme prefix before any app code
sees the token, so `decode_access_token()` there always receives a clean
string. `/ws/live/{call_id}`, however, receives the token as a plain JSON
string value inside the first WebSocket message — nothing strips a
prefix or incidental whitespace before `decode_access_token(token)` was
called directly on it. A token copy-pasted with its `Bearer ` scheme prefix
still attached (an easy mistake — e.g. from copying a `curl -H
"Authorization: Bearer $TOKEN"` example), or with a stray leading/trailing
space or newline, makes PyJWT raise `jwt.exceptions.DecodeError` — a
completely different condition from `ExpiredSignatureError` — but the
handler's `except jwt.InvalidTokenError:` catches both identically and
logged the same generic `"live suggestions: invalid or expired token"`
either way, making the real cause unrecoverable from the log alone.

Reproduced directly against the real server (not a hypothesis): a real JWT
issued via `POST /api/auth/login`, decoded successfully via
`decode_access_token()` when clean, raised `DecodeError: Invalid header
padding` when prefixed with `"Bearer "` or a leading space, and `DecodeError:
Invalid crypto padding` with a trailing newline — all three closed the real
`/ws/live/{call_id}` connection with code 1008 and logged the identical
generic message. This is not necessarily proven to be the operator's exact
keystroke sequence (that state only ever existed in their browser), but it
is a real, 100%-reproducible defect matching every symptom reported: REST
works, a fresh non-expired token still gets "invalid or expired token", and
the client kept reconnecting with the same doomed token indefinitely.

**Second, compounding bug found in the same investigation.** The client's
WebSocket `close` handler (`app/static/live.html`) never inspected the
`CloseEvent.code` — every non-manual close, including the server's policy
rejection (code 1008 — bad/expired token, disallowed origin, wrong tenant),
triggered the same exponential-backoff auto-reconnect as a real network
drop. Since `connect()` always resends whatever is still in the token field,
a rejected token reconnected forever with that exact same rejected token,
which is also why the operator saw the warning logged repeatedly rather
than once.

**Fix.**
1. `app/main.py` (`/ws/live/{call_id}`): the received token is normalized
   (whitespace-stripped; a leading `Bearer ` prefix, case-insensitive, is
   stripped) before `decode_access_token()` is called — matching what
   `HTTPBearer` already does for REST. On rejection, the log now records the
   actual exception class name plus non-secret token-shape metadata (length,
   `.`-segment count, first 12 hex chars of a SHA-256 fingerprint) — enough
   to compare against a locally-computed fingerprint of a known-good token,
   never the token itself.
2. `app/static/live.html`: `sanitizeToken()` applies the same normalization
   client-side before sending (defense in depth — the sent value is clean
   either way). The `close` handler now reads `event.code`; a 1008
   (policy/auth rejection) sets a new, explicit `'auth-error'` connection
   state ("Authentifizierung fehlgeschlagen — bitte Call-ID/Token prüfen und
   neu verbinden", connect form re-shown) instead of scheduling another
   reconnect — any other close code still auto-reconnects exactly as before.
   `'auth-error'` is not an invented conversation state in the sense ADR
   discussion around Seller Frontend v1 ruled out (`"Gespräch läuft"` etc.):
   it is driven by a real, already-existing protocol signal (the server's own
   close code) the client was simply discarding.

**Regression coverage, all passing (288/288 full suite):**
- `tests/test_live_suggestions_ws.py`: a `Bearer `-prefixed token and a
  whitespace-wrapped token are both accepted; a malformed token's rejection
  is logged with the real PyJWT exception class name and non-secret
  fingerprint fields, with neither the malformed nor a valid token ever
  appearing in the log text (`caplog`-asserted).
- `tests/test_seller_frontend_structure.py`: `sanitizeToken()` exists and is
  used before sending; the `close` handler reads `event.code`, treats 1008 as
  terminal (`'auth-error'` before `scheduleReconnect()` in source order,
  never after), and the auth-error message text is present.
- `tests/test_live_ws_browser_e2e.py` (new): a REAL headless-Chromium browser
  (Playwright), driven against a REAL `uvicorn` subprocess (its own isolated
  SQLite DB, real sockets, no ASGI shortcut) — real login, real call
  creation, then for each of a clean/`Bearer`-prefixed/whitespace-wrapped/
  actually-invalid token: open `/live/{call_id}`, paste the token, click
  "Verbinden", and assert on the real rendered `#statusText` and whether the
  connect card is hidden. Verified passing in this session: all three
  malformed-but-real tokens reach "Bereit" with the connect card hidden; the
  actually-invalid token reaches "Authentifizierung fehlgeschlagen" with the
  connect card shown again — never an endless "Wiederverbindung läuft" loop.
  This file `pytest.mark.skipif`s cleanly (not red) wherever Node.js or the
  `playwright` npm package aren't installed — most environments running this
  suite, including the operator's own machine, are not expected to have
  either, and this suite must never require them to get a green `pytest -q`.

**What did NOT change.** No new product feature, no architecture change, no
change to `/ws/twilio-media`, SalesBrain, or Render-ACK. This is a fix to an
input-normalization gap and a reconnect-policy gap, both pre-existing since
Sprint 3A, surfaced by real operator testing.

## ADR-058 — First real test prepared without a purchased Twilio number: REST-placed call to the Seller, same confirmed topology, zero pipeline code changes

Status: accepted (preparation/documentation — no functional code change; one
docstring clarification only)

**New account state, confirmed by the operator:** Pay-as-you-go active, a
real starting balance plus bonus voice minutes, a **Verified Caller ID**
(the operator's own German mobile) instead of a purchased number, and Voice
Geographic Permissions for Germany (+49) enabled at Low Risk (High Risk
intentionally left off). The operator explicitly decided not to buy a
number for this first test.

**The core question this session had to answer before touching anything:**
does REPLICA's already-confirmed, already-tested speaker mapping
(`OutboundSalesFlowResolver`, ADR-053) still hold when the parent call leg is
established by a REST-API `calls.create()` instead of an inbound PSTN call to
a purchased number? The resolver's own docstring explicitly lists "a
REST-API-originated outbound call to the prospect with the seller bridged in
separately" as out of scope — and the operator's own plain-language topology
description ("ausgehender Call → Verbindung zur einwilligenden Testperson")
reads exactly like that out-of-scope case on first pass, which would have
silently inverted both speaker roles (the real prospect labelled `seller`,
whoever got `<Dial>`-ed in labelled `prospect`) and produced zero live
suggestions, since only `prospect`-labelled turns trigger SalesBrain.

**Resolution: it depends only on who is on the parent leg, not on how that
leg was established.** The Media Stream's `inbound`/`outbound` track labels
describe the parent call's connected party (`inbound`) versus whoever gets
`<Dial>`-ed out from it afterward (`outbound`) — nothing about that depends
on whether the parent leg came from an inbound PSTN call or an
outbound-via-REST one. So the REST call must be placed **`To` the Seller**
(the operator's own phone), not `To` the Prospect test person: Twilio calls
the Seller, the Seller answers exactly as if they'd dialed in, and the
already-written, already-correct TwiML (`<Start><Stream>` then
`<Dial><Number>` to the Prospect) runs completely unchanged. This preserves
ADR-053's confirmed topology exactly, with the REST call replacing only the
Seller's own act of dialing in — not the topology itself. Placing the REST
call `To` the Prospect instead (bridging the Seller in separately) remains
genuinely out of scope and was not implemented.

**Answers to the five concrete preparation questions asked this session:**
1. **Is the existing Twilio REST client sufficient?** Yes for authentication/
   region config (`get_twilio_rest_client()`, `app/integrations/
   twilio_rest.py`) — it has simply never been called yet (`.calls.create()`
   appears nowhere in the codebase before this). No new client code needed;
   the one `calls.create()` call itself is a one-off operator action (a
   `python3 -c "..."` snippet in `docs/REAL_TEST_SETUP.md` §4a), not new
   product/API code — REPLICA still does not gain a "place a call" endpoint.
2. **Which env vars were missing?** None at the `Settings` level —
   `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_REGION`, `TWILIO_EDGE`
   already existed (ADR-049). What was actually wrong: `docs/
   REAL_TEST_SETUP.md`'s own claims that `TWILIO_ACCOUNT_SID`/
   `TWILIO_REGION`/`TWILIO_EDGE` were "not read by any code path this test
   depends on" — true for the old bought-number plan, false now that this
   test's call placement actually calls `get_twilio_rest_client()`. Corrected
   in that document's §1.
3. **How to start the call without buying a number?** `client.calls.create(
   to=<Seller phone>, from_=<Verified Caller ID>, url=<TwiML Bin's own public
   Request URL>)` — the same TwiML Bin already documented for the
   bought-number plan, just referenced by its own Twilio-hosted Request URL
   instead of being assigned to a purchased number's "A call comes in"
   webhook. No REPLICA endpoint serves TwiML; Twilio still hosts it.
4. **How does `replica_call_id` reach the Media Stream?** Unchanged —
   `<Parameter name="replica_call_id" value="...">` inside `<Stream>`,
   delivered in the WS `start` event's `customParameters`
   (`app/main.py`'s `_resolve_call_for_media_stream()`). This never depended
   on how the call was initiated.
5. **TwiML / Call API parameters?** TwiML: identical to the already-documented
   two-person variant (`docs/REAL_TEST_SETUP.md` §4, step 5) — zero changes.
   Call API: `to`/`from_`/`url` as in point 3 above; everything else
   (`statusCallback` etc.) already lives inside the TwiML Bin itself, per
   ADR-054.
6. **Speaker/track mapping for this exact topology?** Unchanged from
   ADR-053 — `inbound` (parent leg's connected party = Seller) → `seller`,
   `outbound` (the `<Dial>`-ed party = Prospect) → `prospect`. Documented as
   explicitly still in-scope via a clarifying paragraph added to
   `app/streaming/speaker_mapping.py`'s module docstring (doc-only, no logic
   change — `OutboundSalesFlowResolver.resolve()` itself is untouched, and
   `tests/test_streaming_speaker_mapping.py` still passes unmodified).
7. **Minimal trigger path for the operator?** Create the TwiML Bin → note its
   Request URL → run the existing preflight checklist (login, create call,
   grant consent, open `/live/{id}`) → run the one `calls.create()` snippet
   with `to=` the Seller's own phone. Full detail in `docs/
   REAL_TEST_SETUP.md` §4a (new) and the updated §5 step 6.

**What did NOT change.** No new endpoint, no new Settings field, no change to
`OutboundSalesFlowResolver.resolve()`'s logic, `TurnDetector`, `SalesBrain`,
or the Media Stream/Render-ACK pipeline. The topology preparation itself is
one docstring clarification in `app/streaming/speaker_mapping.py` plus
documentation (`docs/REAL_TEST_SETUP.md` §1/§4/§5/§7) and a one-off operator
command that is never committed — no new endpoint, no new Settings field.

**Incidental real bug found and fixed while re-verifying for this
preparation.** Re-running ADR-057's real-browser E2E test (the one exercising
the actual `/ws/live/{call_id}` handshake, unrelated to today's topology
question) surfaced a genuine, previously-undetected race: `app/static/
live.html`'s `open` handler called `setConnectionState('ready')` as soon as
the raw WebSocket connected and the auth frame was *sent* — not once the
server had actually *validated* it. For a token the server was about to
reject, the browser could flash `'Bereit'` for the window between `open` and
the server's 1008 close arriving, undermining the very point of ADR-057's
`'auth-error'` state. Fixed by adding an explicit `{'type': 'auth_ok'}`
server message (`app/main.py`, sent immediately after every auth/tenant/role
check passes, before entering the receive loop) and moving the client's
`setConnectionState('ready')` call to fire only on receiving `auth_ok` (or
`sync`, which equally proves successful auth) — never on raw `open`. Existing
tests asserting on the first message received after sending `auth` (`tests/
test_live_suggestions_ws.py`'s ping/pong test, `tests/
test_streaming_pipeline_e2e.py`'s live-push assertion) were updated to
consume the new leading `auth_ok` message; a new explicit test
(`test_ws_sends_explicit_auth_ok_immediately_after_successful_auth`) and a
structural guard (`test_ready_state_is_only_set_from_a_real_server_ack_not_on_raw_ws_open`)
cover the fix directly. This was a real defect, not a test artifact — it
also explains why the E2E test appeared to "flake" (~2 of 3 runs) before the
fix: the race window's outcome depended on scheduling, not chance in any
meaningful sense. Full regression after this fix, run four times
consecutively to confirm the race is actually gone rather than just
less likely: **290/290 passing, every time.**

**Secrets discipline for this preparation, stated plainly:** no Twilio
credential, phone number, or TwiML Bin URL was requested from or shared by
the operator in this session — every value in the commands above is a
placeholder the operator fills in locally. The two real phone numbers
involved (Seller's own, Prospect test person's) are not secrets but still
do not belong in any commit, log line, or this document — `docs/
REAL_TEST_SETUP.md` continues to only ever name variable *purposes*, never
values.

## ADR-059 — Prospect test person's number kept out of the Twilio Console entirely, not just out of git

Status: accepted (preparation refinement — no functional code change)

The operator named the actual test person for the first real call: a family
member, not a company test account, using her own mobile number as the
Prospect target. ADR-058's plan already kept that number out of this
repository (the TwiML Bin content is typed directly into the Twilio Console,
never into a file here) — but the Bin approach still leaves it sitting in a
**named, persistent Twilio Console resource** indefinitely. The operator
asked for it not to be hardcoded, committed, or logged; this ADR goes one
step further than strictly asked, since a third party's own number sitting
indefinitely in a dashboard neither of them controls is the same class of
concern as a commit or a log line.

**Decision:** for a real (non-company) test person's number specifically,
replace the TwiML-Bin-based two-person variant with a one-off local script
(`docs/REAL_TEST_SETUP.md` §4a, updated) that builds the same TwiML
**inline** via `twilio.rest.Client.calls.create(twiml=...)` (confirmed
present on the installed SDK's `CallList.create()` signature) instead of
`url=<Bin>`. The number is sourced from `TEST_PROSPECT_NUMBER` (an
environment variable, per the operator's first suggested option) or,
if unset, a `getpass.getpass()` prompt (the operator's second suggested
option, "Eingabefeld beim Start des Testcalls" — realized as a non-echoed
terminal prompt in this one-off script, not a new web form/endpoint, which
would itself be exactly the kind of new product feature this whole
preparation effort has been asked repeatedly not to build). Either way the
value: is validated against a plain E.164 regex before use (rejected inputs
raise `SystemExit` with a static message that never echoes the rejected
value back); is XML-escaped before being embedded in the TwiML string
(`xml.sax.saxutils.escape`); is never passed to `print()`, `logger.*()`, or
written to any file; and only ever exists for the lifetime of that one
Python process. The solo-verification Bin (no `<Dial>`, no third-party
number at all) is unaffected and remains fine to keep as a persistent
Console resource, since it contains no one's personal data.

**Verified before documenting it** (this project's standing discipline,
ADR-043/053/055/057/058): the script's TwiML-construction and E.164-
validation logic was actually run in this session — a valid number produces
byte-for-byte the same `<Start><Stream>`/`<Dial><Number>` shape as the
existing documented Bin content (confirmed via `xml.dom.minidom` parsing),
and an invalid one is rejected without the rejected value ever appearing in
the error message.

**What did NOT change:** no new REPLICA endpoint, no new `Settings` field,
no change to `OutboundSalesFlowResolver`, the Media Stream pipeline, or any
committed test. The script itself is explicitly never committed (`docs/
REAL_TEST_SETUP.md` instructs saving it outside the repository), consistent
with ADR-058's one-off operator script and this whole document's standing
"never a real secret value in this file" rule extended here to a third
party's personal data, not only to REPLICA's own credentials.

## ADR-060 — Browser-based outbound calling (Twilio Voice JS SDK) for the first real test; two new endpoints, one vendored SDK file, three bugs caught by writing tests before shipping

Status: accepted (real implementation — the first ADR in this series that
adds actual product code, explicitly authorized: "Falls ja, bitte den
minimalen Browser-Testpfad implementieren.")

**Change of plan, explicitly requested.** ADR-058/059's REST-`calls.create()`
call-placement path is no longer the mechanism for the first real test. The
operator now wants to place the call live, themselves, from their MacBook's
browser via the Twilio Voice JavaScript SDK (`device.connect()`), with the
Prospect's normal mobile ringing without needing to be a Verified Caller ID.
ADR-058/059's REST path remains documented and working as an alternative
(`docs/REAL_TEST_SETUP.md` §4a); nothing about it was removed.

**What ADR-059 (REST path) still didn't have, confirmed before writing any
code:** no browser calling capability at all — the Twilio Voice JS SDK was
not present anywhere in `app/static/live.html`, there was no server endpoint
to mint a browser Access Token, and no TwiML-generating endpoint existed
(REPLICA had never needed one — Bin-based and REST-inline TwiML both avoid
that). All three needed to be built for real, not just documented.

**Confirmed before writing any implementation code (not assumed):**
- The Twilio Python SDK already installed (`twilio>=9,<10`) exposes
  `twilio.jwt.access_token.AccessToken` and `.grants.VoiceGrant` — inspected
  their real constructor signatures directly rather than guessing, and
  smoke-tested `AccessToken(...).add_grant(VoiceGrant(...)).to_jwt()`
  end-to-end with dummy credentials before writing `create_voice_access_token()`.
- `Client.calls.create()`'s installed signature was already known to accept
  `twiml=` (confirmed for ADR-059) but that has no bearing on the Voice SDK
  path, which never calls the REST API at all — the browser talks to Twilio
  directly over its own signaling connection.
- **The Twilio Voice JS SDK is, as of v2.0, no longer CDN-hosted** (confirmed
  against the SDK's own README, not assumed from memory) — a `<script src=
  "https://sdk.twilio.com/...">` tag would 404. The officially recommended
  alternative is self-hosting the built bundle. `twilio.min.js` from GitHub
  Releases tag `2.18.5` (the confirmed-latest release at the time) was
  downloaded, verified (valid JS via `node --check`, ~300KB, exposes the
  documented `Twilio.Device`/`Twilio.Call` globals via `globalThis`) and
  vendored into the repo at `app/static/vendor/twilio-voice-sdk.min.js`,
  served same-origin by the existing static file mount — no CDN dependency,
  no build step, no npm/webpack introduced.
- The exact `Device` constructor signature, `connect()`'s `ConnectOptions`
  shape (`{ params: Record<string,string> }` — confirmed as the mechanism for
  passing `To`/`replica_call_id` to the Voice webhook), and both `Device`'s
  and `Call`'s real event names (`'registered'`, `'error'`, `'accept'`,
  `'ringing'`, `'disconnect'`, `'cancel'`, `'reject'`, ...) were read directly
  from the pinned version's own TypeScript source (`lib/twilio/device.ts`,
  `lib/twilio/call.ts`), not assumed from older SDK versions' now-outdated
  public examples.

**What was built:**
1. `app/config.py`: four new optional settings — `TWILIO_API_KEY_SID`/
   `TWILIO_API_KEY_SECRET` (a separate Twilio API Key, deliberately never the
   main `TWILIO_AUTH_TOKEN`, which stays reserved for webhook signature
   verification), `TWILIO_TWIML_APP_SID`, `TWILIO_VERIFIED_CALLER_ID`.
2. `app/integrations/twilio_rest.py`: `create_voice_access_token(identity,
   ttl_seconds=3600)` — mints a short-lived Access Token with a `VoiceGrant`
   scoped to the one configured TwiML Application, fails closed (`ValueError`)
   if any required setting is missing, mirroring `get_twilio_rest_client()`'s
   existing posture exactly.
3. `app/main.py`, two new endpoints:
   - `POST /api/voice/access-token` — authenticated like every other
     seller-facing endpoint (`require_role('seller','manager','tenant_admin')`),
     returns `{token, identity, ttl_seconds}`.
   - `POST /webhooks/twilio/voice-outbound` — the TwiML Application's Voice
     Request URL. Same authentication posture as the existing
     `POST /webhooks/twilio/call-status` webhook: X-Twilio-Signature is the
     ONLY authentication (fail-closed, ADR-029/036) — reuses
     `verify_twilio_signature()` and the exact URL-construction pattern
     already established there. Validates `To` against a plain E.164 regex
     and rejects (never echoing the rejected value) rather than embedding
     unvalidated input into TwiML; returns
     `<Start><Stream track="both_tracks"><Parameter name="replica_call_id">
     ...` then `<Dial callerId="<server-side TWILIO_VERIFIED_CALLER_ID>">
     <Number>{To}</Number></Dial>` — `callerId` is never something the
     browser can set, so a compromised/buggy client could never spoof it.
4. `app/static/vendor/twilio-voice-sdk.min.js` (new, vendored, see above) +
   `app/static/live.html`: a new "Echter Testcall (Twilio Voice SDK)" section
   added **inside the existing closed-by-default Debug-Ansicht** (ADR-056 —
   this is a test-harness control, not a seller-facing product feature): a
   number input and a button. The number is read once on click, the field is
   cleared immediately after, it is validated against E.164 before any
   network call, and it never appears in a `console.*` call anywhere in the
   click handler (all deliberate, and each individually covered by a new
   structural test — the operator's own runtime-only/never-logged
   requirement for the Prospect's number, first raised for ADR-059, applies
   identically here).

**Speaker-role mapping for this exact topology:** unchanged from ADR-053/058
— `OutboundSalesFlowResolver` still maps `inbound` (whoever is connected on
the parent leg) to `seller` and `outbound` (the `<Dial>`-ed child leg) to
`prospect`. Twilio's Media Streams track semantics do not distinguish a
WebRTC client leg from a PSTN one, so a browser-originated parent leg with
the Seller on it is structurally identical to the already-confirmed cases.
Clarified via a new paragraph in `app/streaming/speaker_mapping.py`'s module
docstring (doc-only, zero logic change, `tests/test_streaming_speaker_mapping.py`
untouched) — explicitly **not yet verified against a live call**, which is
exactly what running this test is for.

**Three real bugs found by writing tests before shipping, not shipped
unverified (this project's standing discipline):**
1. **XML attribute-injection risk.** `xml.sax.saxutils.escape()`'s documented
   default entity set is `&`/`<`/`>` only — it does NOT escape `"`. Two of
   the three values embedded in the generated TwiML sit inside
   double-quoted XML *attributes* (`value="..."`, `callerId="..."`); an
   unescaped `"` in either could have let a value break out of its attribute
   and inject arbitrary TwiML. Caught while writing
   `tests/test_voice_outbound.py`'s escaping test (which initially asserted
   the WRONG — i.e. actually-vulnerable — expected output, itself only
   caught by cross-checking `xml.sax.saxutils.escape`'s real default
   behavior directly rather than assuming). Fixed with a small
   `xml_attr_escape()` helper that additionally escapes `"` for the two
   attribute-context values; the `<Number>` element's plain text content
   correctly keeps the simpler default (it doesn't need quote-escaping, and
   `To` is already E.164-regex-validated before it ever reaches that point
   regardless).
2. **Test-isolation bug (test-only, not a product bug).** The first version
   of the access-token tests monkeypatched attributes directly on
   `app.main.settings` (the module-level `Settings` instance bound once at
   import time) — this is exactly the pattern this repo's own webhook tests
   already use successfully, but `create_voice_access_token()` calls
   `get_settings()` FRESH on every invocation rather than using that
   pre-bound reference. `tests/test_twilio_rest_region.py` (which sorts
   alphabetically before the new test file and already clears the
   `get_settings` lru_cache in its own `finally` blocks) left the cache
   pointing at a rebuilt instance that the old `app.main.settings` reference
   no longer represented — a full-suite run failed two tests that passed in
   isolation, confirmed by re-running the full suite three times before and
   after the fix. Fixed by switching to this repo's own already-established
   env-var + `get_settings.cache_clear()` pattern
   (`tests/test_twilio_rest_region.py`), plus an autouse fixture that
   re-clears the cache on teardown so this file cannot leak a fake-credentialed
   Settings instance into whichever test file happens to run next.
3. **Premature error surfacing gap (design decision, not a defect in shipped
   code):** confirmed the Device/Call error-event wiring surfaces failures to
   the visible `voiceStatus` text rather than only to the browser console,
   specifically because `device.connect()`'s exact registration requirements
   could not be independently verified against Twilio's own live
   documentation (`www.twilio.com` and `api.github.com` were both blocked by
   this session's network egress policy; the pinned version's own
   TypeScript source, fetched from `raw.githubusercontent.com`, was used as
   the authoritative source instead) — if `device.connect()` alone turns out
   to be insufficient without an explicit prior `device.register()` call,
   the operator will see a clear, specific error message rather than a
   silently non-functional button.

**Regression coverage, all passing, full suite run three times consecutively
to rule out ordering flakiness (this ADR's own test-isolation bug made that
non-optional): 308/308 every time.**
- `tests/test_voice_outbound.py` (new): access-token auth requirement,
  fail-closed when unconfigured, JWT grant/identity/subject correctness,
  per-user identity scoping; voice-outbound signature enforcement (missing/
  wrong signature both rejected), correct TwiML shape and ordering
  (`<Start>` before `<Dial>`), malformed `To` rejected without ever being
  logged (`caplog`-asserted), missing `replica_call_id` rejected, fails
  closed without `TWILIO_VERIFIED_CALLER_ID` configured, and the XML
  attribute-escaping fix verified against the actual endpoint response (not
  just the escape function in isolation).
- `tests/test_seller_frontend_structure.py` (extended): the Voice SDK is
  loaded from the vendored local file, never a third-party CDN host; the
  vendored file exists and contains real SDK content; the Prospect number
  field is never prefilled and has `autocomplete="off"`; no real-looking
  phone number literal exists anywhere in the file; the field is read then
  immediately cleared before any `console.*` call could exist in that code
  path; E.164 validation runs before `device.connect()`; `replica_call_id`
  is sent as a custom parameter; the whole voice-test UI lives inside the
  debug `<details>`, never in the main seller view.

**What did NOT change:** `OutboundSalesFlowResolver`'s logic, `TurnDetector`,
`SalesBrain`, the Media Stream pipeline, `/ws/twilio-media`, Render-ACK, or
any existing endpoint's behavior. The main seller-facing view (above the
debug disclosure) is untouched — this is additive, confined to the
already-reclassified (ADR-056) technical debug view.

## ADR-061 — ADR-060's Voice Access Token silently carried no EU region preference at all; fixed and verified against the real SDK source before the first real call

Status: accepted (correction, real bug found by the operator's own explicit
question before running anything — fixed and tested, no code shipped
unverified)

The operator asked, before creating any Twilio Console resources, for
verification that the ADR-060 browser-calling path is fully pinned to
`TWILIO_REGION=ie1`/`TWILIO_EDGE=dublin` — the same EU data-residency
guarantee `get_twilio_rest_client()` already enforces (ADR-049). It was not.

**Confirmed, by reading the installed Twilio SDK's own source directly (not
assumed):** `AccessToken.__init__` accepts a `region` parameter, but ADR-060's
`create_voice_access_token()` never passed it. Read `AccessToken`'s actual
`_generate_headers()`/`_generate_payload()` implementation: `region` is NOT a
no-op — it sets the JWT's `twr` (Twilio Region) header claim, which Twilio's
signaling infrastructure uses to route the client to the configured region.
Verified concretely by constructing a real token with `region='ie1'` and
decoding its header: `{'alg': 'HS256', 'cty': 'twilio-fpa;v=1', 'twr': 'ie1',
'typ': 'JWT'}` — confirming both that the parameter does something and
exactly what it produces. Without it, every Voice Access Token ADR-060 could
have issued carried no region preference at all, silently defeating this
account's EU-residency setup for the one path that most directly represents
a live call (the browser's real-time signaling connection to Twilio).

Separately confirmed (same rigor, this time against the pinned Voice JS
SDK's own TypeScript source, `lib/twilio/device.ts`): `Device.Options.edge`
exists, accepts a string or array of strings, and its own documented default
is `"roaming"` — automatic edge selection by client-measured latency, NOT
necessarily Dublin. ADR-060's `new Twilio.Device(body.token)` call never set
it either.

**Fix:**
1. `create_voice_access_token()` (`app/integrations/twilio_rest.py`) now
   passes `region=settings.twilio_region` to `AccessToken(...)`, and fails
   closed (`ValueError`) if `TWILIO_REGION`/`TWILIO_EDGE` are not both
   explicitly configured — matching `get_twilio_rest_client()`'s existing
   posture exactly, so the browser-calling path can no longer be the one
   place this account's EU-residency requirement is silently skippable. Its
   return value changed from a bare token string to `{token, region, edge}`
   — `edge` cannot be embedded in the Access Token itself (there is no such
   JWT claim), so it travels back to the caller instead.
2. `POST /api/voice/access-token` (`app/main.py`) now also returns `region`
   and `edge` in its JSON response.
3. `app/static/live.html`: `new Twilio.Device(body.token, { edge: body.edge })`
   — read from the server's response rather than hardcoded a second time in
   JavaScript, so this file can never independently drift out of sync with
   `TWILIO_EDGE`. The voice-test status line also now shows the active
   region/edge (`"Registriere Device (Region: ie1, Edge: dublin) …"`) so the
   operator can visually confirm it during the real test, not just trust it.

**Media Stream and the rest of the voice pipeline, stated plainly (not newly
verified, re-confirmed from the existing documented finding):** `/ws/twilio-
media` and the call-status/voice-outbound webhooks have no region parameter
in REPLICA's own code at all — inbound Twilio→REPLICA traffic was already
documented (`docs/REAL_TEST_SETUP.md` §1) as having no region concept on
REPLICA's side; Twilio's own infrastructure determines which region actually
processes a given call and its Media Stream, driven by which
region/edge the call's signaling connection used. Since that signaling
connection is now pinned to IE1/Dublin from the moment `Device.connect()` is
called, the whole call — the Media Stream included — should be processed
within Twilio's IE1/EU infrastructure consistently. This has NOT been
independently verified against a live call (no such verification is possible
without one); it is a well-founded expectation from the token/edge
configuration being correct now, not an observed fact yet.

**Regression coverage, all passing, full suite run three times consecutively
after this fix: 311/311 every time** (`tests/test_voice_outbound.py`: the
JWT header's `twr` claim and the response body's `region`/`edge` fields are
asserted directly against a real constructed token; a new fail-closed test
confirms 500 when either `TWILIO_REGION` or `TWILIO_EDGE` is unset;
`tests/test_seller_frontend_structure.py`: the `Device` constructor call
includes `{ edge: body.edge }` and no hardcoded edge string literal exists
anywhere in the file).

**What did NOT change:** no new endpoint, no change to
`OutboundSalesFlowResolver`, `get_twilio_rest_client()`, or any other
existing behavior — this is a correction confined entirely to ADR-060's own
new code, found and fixed before a single Twilio Console resource for it was
created.

**Addendum, same investigation: the Console-side half of "fully IE1" was
also about to be missed.** Before any Console resource was created, checked
whether API Keys and TwiML Apps are themselves region-scoped in the Console
UI, rather than assume the code-level fix above was the whole story.
Confirmed against Twilio's own published documentation ([Managing Regional
Resources in
Console](https://www.twilio.com/docs/global-infrastructure/managing-regional-resources-in-console)):
they are. Whichever Region the Console's Region selector is set to at the
moment of clicking "Create" is the Region the resource is created in —
defaulting to US1 if never touched. Creating the API Key or the TwiML App
without first switching that selector to IE1 would have produced a US1
resource, silently defeating the exact EU-residency intent of this whole
ADR at the one step still left to a human clicking through a UI rather than
running verified code. `docs/REAL_TEST_SETUP.md` §4b's Console steps were
updated to make switching the Region selector to IE1 an explicit, ordered
step 0 before creating either resource, with an honesty note that this
session could not click through the current Twilio Console live to confirm
exact wording (`www.twilio.com` was blocked by network egress policy here,
same as during ADR-058's original Console-steps write-up) — the steps
follow Twilio's own documented procedure, with an explicit instruction to
verify the Region indicator actually reads IE1 before proceeding.

## ADR-062 — Twilio Console unreachable; fail-closed preflight check, full browser-call-flow rehearsal, and a real prospect-number-not-cleared bug caught by live testing, all prepared before a single new Console resource exists

Status: accepted (preparation ahead of a blocked step, not a correction of
a previous ADR — though it did surface and fix one real UI bug along the
way)

The operator's Twilio Console was unreachable, blocking the two remaining
Console resources ADR-060/061 depend on (the API Key and the TwiML App).
Rather than wait, the request was to prepare everything else so that once
the Console is reachable again, only creating those two resources and
entering their values remains. Four things were built/verified for this,
none of them new product features:

**1. `GET /api/voice/preflight` (`app/main.py`), status-only, never a
secret value.** Reads the bound `settings` object (this endpoint is
naturally re-evaluated per request, so unlike `create_voice_access_token()`
there is no reason to call `get_settings()` fresh) and reports, per item, a
label, whether it's satisfied, and — only for the three genuinely
non-secret settings (`TWILIO_REGION`, `TWILIO_EDGE`,
`REPLICA_PUBLIC_BASE_URL`) — its actual value, so the operator can visually
confirm `ie1`/`dublin` rather than just trust a checkmark. Every credential
(`TWILIO_ACCOUNT_SID`, `TWILIO_API_KEY_SID`, `TWILIO_API_KEY_SECRET`,
`TWILIO_TWIML_APP_SID`, `TWILIO_VERIFIED_CALLER_ID`, `DEEPGRAM_API_KEY`) is
reported as present/absent only. The WS-origin check reuses the existing
`is_allowed_origin()`/`parse_allowed_origins()` (`app/services/ws_origin.py`,
ADR-051/052) rather than re-implementing origin matching — it reports
satisfied unconditionally when `REPLICA_ENV=local` (matching that
function's own bypass), otherwise checks `REPLICA_PUBLIC_BASE_URL`'s origin
against `REPLICA_ALLOWED_WS_ORIGINS`. The overall `ready` boolean is true
only if every item is satisfied. Auth-gated identically to the other voice
endpoints (`require_role('seller', 'manager', 'tenant_admin')`).

**2. `/live/{call_id}`'s voice-test section now calls this automatically
and fails closed.** `refreshVoicePreflight()` runs on `auth_ok` and renders
a ✓/✗ checklist (`renderPreflight()`); the `voiceCallBtn` click handler
now checks `ready` before doing anything else and, if false, shows the
missing items' plain-language labels and returns — `device.connect()` is
never reached. Verified live, not just read: a real Playwright run against
a real running server (not pytest's ASGI TestClient) confirmed the
checklist renders the correct ✓/✗ per item, shows exactly the three
non-secret values and nothing else, and that the fail-closed path
genuinely prevents the call from starting when configuration is
incomplete.

**3. Real bug found and fixed by that same live run, not by pytest:** the
first version of the click handler read and cleared the prospect-number
field only after the preflight check. When preflight failed and the
handler returned early, the field was left populated with whatever the
operator had typed — confirmed by a Playwright run showing
`prospectFieldAfterClick: "+491701234567"` after a fail-closed click.
Fixed by moving the read+clear to the first two lines of the handler,
before any other check, so the field is guaranteed empty after every
outcome — re-verified with the identical script showing
`prospectFieldAfterClick: ""` afterward. This is a real instance of the
project's standing prospect-number-never-lingers requirement, not a
hypothetical: the number now never reaches `localStorage`/`sessionStorage`
(never assigned to either), never reaches `console.*` (never logged),
never persists server-side beyond the one-time TwiML response Twilio
consumes once (no code path writes it to the database or a file), and no
error text anywhere embeds it (`renderPreflight()`'s messages only ever
name a config label or the endpoint's own generic text) — nor does it ever
reach `git`: the only file in this repo that ever names a real-looking
test number is `place_test_call.py`'s own docstring template from ADR-059,
which itself is written to live outside this repository and reads its
number from an environment variable or a non-echoed prompt.

**4. `tests/test_voice_call_flow_e2e.py` (new file), one continuous
end-to-end test proving the whole browser-call flow without a real Twilio
account, a real Deepgram account, or a real phone:** Voice Access Token
region/edge (`region='ie1'`, `Device` edge `'dublin'`, the JWT `twr`
header decoded and asserted directly) → `POST
/webhooks/twilio/voice-outbound` with a real Twilio signature → the
resulting TwiML asserted for shape (`<Start>` before `<Dial>`,
`track="both_tracks"`, the `replica_call_id` parameter, the escaped
`callerId`) → that exact `call_id` driven through the real Media Stream
pipeline (`StreamSimulator`, reusing `tests/test_streaming_pipeline_e2e.py`'s
fixtures rather than duplicating them) with a real `/ws/live/{call_id}`
client attached → a real `Suggestion` push received → the `Turn` table
queried directly to confirm `outbound` resolved to `prospect`
(`OutboundSalesFlowResolver`, ADR-053/060) → a real Render-ACK posted and
`wallclock_rsl_estimate_ms` confirmed non-null. As documented in the file's
own module docstring: audio content and the ASR transcript are still
simulated (`SimulatedASRProvider`) — everything else exercised is real,
unmocked REPLICA code. What this test does NOT and cannot prove: a real
Twilio account, a real phone ringing, or real Deepgram transcription —
that is exactly what the first real call itself is for.

**Regression coverage:** eight new tests added to
`tests/test_voice_outbound.py` for the preflight endpoint (auth
requirement, full-ready reporting, secret-value-leak prevention — asserted
by checking realistic-looking fake secret values do not appear anywhere in
the raw response text — missing-item reporting by label, wrong-region/edge
still showing its actual value, and all three WS-origin-allowlist
scenarios), plus the one new end-to-end test above. **Full suite run three
times consecutively: 320/320 every time** (up from the pre-existing
312/312 baseline — the +8 are exactly the new preflight tests). No prior
test needed changing, confirming this turn introduced no regression to any
previously-existing behavior, including the rest of the live-copilot UI
(re-confirmed working via the same live Playwright session used to find
the bug in point 3).

**What did NOT change:** no new product feature, no new frontend, no new
dialer — this ADR adds one read-only status endpoint, wires an existing UI
section to call it and fail closed, fixes one real bug that wiring
exposed, and adds test coverage; `OutboundSalesFlowResolver`,
`create_voice_access_token()`, the TwiML generation logic, and every other
previously-existing endpoint are unchanged. `docs/REAL_TEST_SETUP.md` §7
was rewritten from a stale, already-twice-superseded 19.09 resume note
into a short, current, four-part checklist (what's fully ready / what
remains Console-only / which values to enter locally / the exact start
sequence) reflecting this ADR's state — §1–6 are unchanged reference
material.

## ADR-063 — Red-team hardening pass before the first real call: double-start prevention, an explicit call/analysis state split, runtime fail-closed behavior, and a real cross-tenant call-hijack vulnerability found and closed

Status: accepted (hardening pass explicitly requested ahead of the first
real call, including one genuine security fix — not a cosmetic change)

The operator asked for nine concrete red-team risks to be closed before
placing the first real call, explicitly ruling out new product features or
a larger refactor. Nine numbered items below; the most consequential is
item 8, a real vulnerability found while implementing item 7, not merely a
defensive add-on.

**1/2. Double-start prevention + explicit call state
(`app/static/live.html`).** Replaced the previous single `voiceStatus`
string with two independent state variables: `callState` (`ready` |
`connecting` | `ringing` | `connected` | `ending` | `ended` | `failed`,
set ONLY from real `Twilio.Device`/`Call` SDK events — `call.on('ringing'/
'accept'/'disconnect'/'cancel'/'reject'/'error', ...)`, never assumed) and
`analysisState` (item 3, below). The entire call-starting logic was
extracted into one named function, `startVoiceTestCall()`, whose FIRST
statement — before reading the prospect number, before the preflight
check, before any `await` — is the guard `if (callState !== 'ready' &&
callState !== 'ended' && callState !== 'failed') return;`. Both the
button's click handler and a new Enter-key handler on the prospect-number
field call this exact same function, so neither can drift out of sync with
the other or bypass the guard. `renderVoiceStatus()` is the one place that
derives the button's `disabled`/hangup-button's `hidden` state from
`callState`, kept disabled for the entire connecting/ringing/connected/
ending duration as a second, independent layer (a disabled button never
dispatches a `click` event at all).

Verified live, not just read (a double-start guard is exactly the kind of
claim this project does not accept on faith): a real Playwright run against
a real running server, with a fake `Twilio.Device`/`Call` injected via
`page.addInitScript()` (no real Twilio account exists for this), confirmed
— genuinely, not by construction — that firing two near-simultaneous clicks
on the button produces exactly ONE `device.connect()` call, that Enter on
the number field while a call is already in flight is also a no-op, that
the full Ready→Connecting→Ringing→Connected→Ended cycle renders the
correct text and button states at every step (including "Call verbunden –
Media Stream wartet" once connected, before any real pipeline_status has
arrived), that the Hangup button disconnects and correctly re-enables a new
call only after a clean end, and that a second call afterward carries a
fresh ticket and never a raw `replica_call_id` (item 8, below) — zero
console errors throughout.

**5. Hangup button.** Added `#voiceHangupBtn`, confined to the same debug
test area (no new product UI). Its click handler calls `activeCall.
disconnect()` and shows `'ending'` as honest in-flight feedback that a
hangup was requested — the actual `'ended'` transition still only ever
comes from the real `call.on('disconnect')` handler, matching item 2's
"state comes from the SDK, never assumed" rule even for the one action the
operator themselves initiates. `disconnect`/`cancel`/`reject` all funnel
through one `onCallEnded()` helper (the one place `activeCall` is cleared),
so no abort path can independently forget to reset it and leave the Hangup
button silently pointed at a dead `Call` object (item 6).

**3. Independent analysis/pipeline state, decoupled from the phone call
(the item the operator called "ganz wichtig").** A new `PipelineStatus`
push channel (`app/streaming/pipeline.py`'s `PipelineStatus` constants;
`app/services/live_push.LiveSuggestionHub.push_status()`/`push_suggestion_
stale()`), delivered as `{'type': 'pipeline_status', 'status': ...,
'detail': ...}` over the SAME `/ws/live/{call_id}` connection the
suggestion push already uses (no new endpoint) — resynced on reconnect
exactly like the existing suggestion sync-on-connect (`hub.last_status()`).
Milestones, each pushed exactly once per transition (never spammed):
`media_stream_connected` (the instant the Media Stream attaches, in
`app/main.py`'s `/ws/twilio-media` `start`-event handling), `deepgram_
connecting`/`deepgram_ready` (only when the real `DeepgramASRProvider` is
configured — a simulated-provider demo never shows a synthetic Deepgram
status), `audio_received`/`transcript_active` (first chunk / first ASR
event, in `MediaStreamPipeline.consume_media()`), `suggestion_pipeline_
ready` (the first successfully processed turn, in `_process_turn()`), and
`disrupted` with a specific `detail` otherwise.

`app/static/live.html`'s `renderVoiceStatus()` shows the analysis label
ALONGSIDE — never instead of — "Call verbunden" whenever `callState` is
`connected`/`ending`, producing exactly the wording the operator asked for:
`"Call verbunden – Analyse nicht verfügbar"` (generic) or `"Call verbunden
– Deepgram nicht verfügbar"` (the specific case). Structurally guarded
(`tests/test_seller_frontend_structure.py`): `setAnalysisState()` is called
from exactly one place inside the call-starting function (a reset to
`'waiting'` for a fresh attempt) and otherwise ONLY from the `pipeline_
status` WS-message handler — no call-state event handler may set it,
keeping the two states genuinely independent as designed rather than just
by convention.

**4. Runtime fail-closed during an active call**, covering every failure
mode the operator listed by name:
- **Media-Stream-Abbruch**: `/ws/twilio-media`'s `WebSocketDisconnect`
  handler (Twilio's transport dropping without first sending a clean
  `'stop'` event — documented as the normal end-of-stream signal) now
  pushes `disrupted`/`media_stream_disconnected` after finalizing any
  mid-speech utterance, so a genuinely still-connected phone call is never
  silently analysis-less.
- **Deepgram-Disconnect**: the real blind spot found while implementing
  this — `DeepgramStreamHandle._ensure_connected()`/`feed_audio()` already
  degrade completely silently on a drop ("never crash the pipeline over one
  track's ASR connection failing"), meaning NOTHING in the existing code
  could ever detect this happening. Added `is_connected()` to the
  `ASRStreamHandle` protocol (`app/streaming/asr.py`) — `True` always for
  `SimulatedASRProvider` (nothing real to lose), the real, current
  connection state for `DeepgramStreamHandle`. `MediaStreamPipeline.
  consume_media()` polls it after every `feed_audio()` call and pushes
  `disrupted`/`deepgram_unavailable` (and `deepgram_ready` again on
  recovery) only on an actual TRANSITION, never repeatedly while already
  down. Verified against a real transient drop AND a real sustained one
  (`tests/test_streaming_deepgram_provider.py`, against the existing fake
  Deepgram-protocol server) — a momentary blip that `_ensure_connected()`'s
  own retry logic self-heals within one `feed_audio()` call is deliberately
  NOT reported (not a seller-visible event); only a drop that survives past
  that self-healing is.
- **Pipeline-Exception / fehlendem Prospect-/Seller-Track**: `/ws/twilio-
  media`'s `start`-event handling now wraps `MediaStreamPipeline.create()`
  in `try/except` (pushes `disrupted` with `deepgram_unavailable` when the
  configured provider is `DeepgramASRProvider`, `pipeline_error` otherwise,
  then closes the socket with 1011) and the whole per-message loop gained a
  matching `except Exception:` for anything unhandled during `consume_
  media`/`consume_stop`. A per-track "zero audio chunks ever received" case
  (a literally missing track) is deliberately NOT live-pushed — doing so
  correctly needs a timeout/watchdog that would be a real addition to this
  pipeline's shape, out of scope for a hardening pass — but stays visible
  retrospectively via the existing `diagnostics_summary()`/structured logs.
- **Nicht vertrauenswürdiges Speaker-Mapping**: `_process_turn()` now checks
  `turn_event.speaker in ('seller', 'prospect')` before persisting — the
  resolver's own fallback branch (`OutboundSalesFlowResolver.resolve()`)
  only returns those two values for the two tracks Twilio's Media Streams
  ever produce, so this is currently unreachable in production; kept as
  fail-closed defense-in-depth rather than trusting that invariant forever,
  and directly testable by injecting an alternate resolver
  (`tests/test_pipeline_status_hardening.py`).
- Every one of the above ALSO calls the new `push_suggestion_stale()`
  (`LiveSuggestionHub`) — sends `{'type': 'suggestion_stale', 'reason':
  ...}` and marks the remembered `last_payload`'s `stale` flag (so a
  reconnecting client is resynced to the correct staleness too), satisfying
  "eine bestehende letzte Suggestion klar als nicht mehr aktuell markieren"
  without retracting or deleting it — `app/static/live.html` dims the "Sag
  jetzt" text and shows an explicit badge whenever this fires, cleared
  automatically the moment a genuinely new suggestion arrives.

**7/8. `/api/voice/access-token` tenant/consent binding, and a real
cross-tenant call-hijack vulnerability closed.** Auditing item 7's
checklist against the existing endpoint surfaced a real gap: it accepted
NO `call_id` at all — any authenticated seller/manager/tenant_admin could
mint a working Access Token regardless of which call (if any) they
intended it for, with no tenant check and no consent/policy check
whatsoever. Fixed: `call_id` is now a required query parameter, resolved
via the same `_get_call_or_404()` every other call-scoped endpoint uses
(cross-tenant is a 404, indistinguishable from nonexistent — never a
distinguishable 403 a client could probe with), and gated on the same
`can_process(..., 'live_assist', ...)` check `/api/calls/{id}/turns`
already enforces — a call whose consent isn't currently granted cannot
even fetch a working token for it.

That alone was not enough — auditing item 8 (`replica_call_id` tenant
safety) surfaced a genuinely exploitable vulnerability the fix above does
NOT close by itself, present since ADR-060: `POST /webhooks/twilio/voice-
outbound` is authenticated ONLY by Twilio's signature (it cannot see the
seller's bearer token — Twilio itself is the caller), and it embedded
WHATEVER `replica_call_id` value the BROWSER'S `device.connect({params:
{...}})` call supplied, completely unchecked, directly into the `<Stream>`
Parameter. `_resolve_call_for_media_stream()` then trusts that value with
no tenant check of its own (by design — it has no bearer token to check
against either). **Concretely, before this fix**: a compromised or
malicious browser session for Tenant A's seller could set `replica_call_id`
to ANY other tenant's real call id at `device.connect()` time. The webhook
would embed it unchanged; the Media Stream would attach Tenant A's REAL
audio to Tenant B's `Call` row; every `Turn`/`Suggestion`/audit record
produced would be written against Tenant B's call, populated with Tenant
A's actual spoken content; and — the most damaging part —
`LiveSuggestionHub.publish_suggestion()`'s own tenant check would let this
through cleanly, since the pipeline's `company_id` is read from the
(attacker-chosen) `Call` row itself: Tenant B's own legitimate seller,
genuinely watching that call live, would receive fabricated suggestions
manufactured from a completely unrelated conversation, mixed permanently
into their own call's real record. This is exactly the "Audio an einen
fremden Call binden" / "einen fremden Live-Suggestion-Stream verwenden"
risk the operator named — not hypothetical, a real, working exploit path
in the shipped ADR-060 code, found by deliberately trying to break it
rather than assuming the existing design was safe.

**Fix, self-contained, no dependency on any Twilio-specific behavior**:
`create_voice_call_ticket()`/`decode_voice_call_ticket()`
(`app/auth/security.py`) — a short-lived (5 min default), REPLICA-signed
(`REPLICA_JWT_SECRET`, distinct `purpose: 'voice_call_ticket'` claim so a
login session token could never be replayed here) JWT carrying the
already-tenant-and-consent-verified `call_id`/`company_id`/`user_id` from
`/api/voice/access-token`. The browser now sends `replica_voice_ticket`
instead of a raw call_id; `/webhooks/twilio/voice-outbound` decodes and
verifies it (fails closed — missing/invalid/expired/wrong-signature/wrong-
purpose all rejected before any TwiML is generated) and uses ONLY the
call_id/company_id it contains — there is no code path left that reads a
call_id from anywhere else. Even a validly-issued ticket is re-checked
against the CURRENT `Call`/consent state at call-placement time (not just
trusted because it was valid moments earlier when minted), closing the
window where consent could be withdrawn in between. `<Parameter
name="replica_call_id" value="...">` still exists in the generated TwiML —
now always the ticket-verified integer, never anything the browser could
have influenced.

Regression-tested exhaustively (`tests/test_voice_outbound.py`): a forged
ticket (wrong secret) rejected, an expired ticket rejected, a login token
presented as a ticket rejected (wrong `purpose`), a ticket whose company_id
doesn't match the real call's rejected, a ticket valid at mint-time but
whose consent was withdrawn before the call was placed rejected — and,
the direct proof of the fix (`test_voice_outbound_ignores_a_raw_replica_
call_id_and_trusts_only_the_ticket`): a request carrying a legitimate
ticket for the caller's OWN call PLUS a raw `replica_call_id` pointing at
an entirely different tenant's real call — asserts the resulting TwiML
embeds only the ticket's own call_id, never the attacker-supplied one.

**9. Speaker-mapping instrumentation for the real call.** `MediaStreamPipeline.
create()` now logs once per call (INFO, structured, zero transcript/audio
content): the resolved topology name, the full `{track: role}` mapping,
and a newly-generated per-track `asr_session_id` (a correlation id, not a
provider concept) — directly answering "inbound_track → seller?" /
"outbound_track → prospect?" after the real call without guessing, and
correlating to whichever ASR session and `Turn` rows resulted. No change to
where the mapping itself lives — `SpeakerRoleResolver`
(`app/streaming/speaker_mapping.py`) remains the ONE place a topology
correction would ever be made. Found and fixed one small but real drift
risk while auditing this: `app/streaming/media_stream_session.py`'s own
module docstring/comments asserted a fixed `inbound=prospect`/
`outbound=seller` identity for the transport-level track labels — already
wrong even before this ADR (ADR-053 established the opposite for REPLICA's
actual topology) and exactly the kind of second, uncoordinated place this
requirement warns about. Corrected to describe those constants as opaque
transport labels only, pointing to `speaker_mapping.py` as the sole source
of truth — doc-only, no logic change.

**What did NOT change**: no new product feature, no new dialer, no new
frontend beyond the debug-only Hangup button and the stale-suggestion
badge; `OutboundSalesFlowResolver`'s actual mapping logic, `TurnDetector`,
`SalesBrain`, `ConversationState`, and every previously-existing endpoint's
core behavior are unchanged. The Twilio Access Token's own TTL (1 hour) was
deliberately left as-is — reducing it risked cutting off an in-progress
real call for no real security gain, since the new voice-call ticket (5
minutes, call/tenant/consent-bound) is what actually closes the exposure
"kurzlebig" was asking about.

**Regression coverage**: 20 new tests across `tests/test_live_push.py`
(pipeline-status/suggestion-stale push + tenant isolation),
`tests/test_seller_frontend_structure.py` (double-start guard ordering,
call-state-only-from-SDK-events, analysis-state independence, hangup
button, cleanup convergence — all structural, matching this project's
established no-JS-test-tooling approach), `tests/test_streaming_deepgram_
provider.py` (`is_connected()` across a real transient and a real
sustained drop), `tests/test_voice_outbound.py` (the full ticket-based
access-token/webhook rewrite, including the cross-tenant-hijack
regression test), and a new `tests/test_pipeline_status_hardening.py`
(direct pipeline-level Deepgram-flap/untrusted-speaker-mapping/
instrumentation-logging tests, plus full `/ws/twilio-media`-level tests for
pipeline-construction failure and an unclean media-stream disconnect).
`tests/test_streaming_pipeline_e2e.py` and `tests/test_voice_call_flow_
e2e.py` updated to drain the now-interleaved `pipeline_status` milestones
before asserting on the eventual suggestion, and to use the ticket rather
than a raw call_id — both re-verified passing end-to-end. Full suite:
357/357, run three times consecutively, no regression to any previously-
existing behavior. Also live-browser-verified (Playwright, fake `Twilio.
Device`/`Call`, real server, zero console errors) per item 1/2's own
section above — not just read, exactly this project's standing discipline
for any UI-behavior claim.

## ADR-064 — Two residual red-team gaps that 357/357 green tests did not cover: voice-ticket replay and cross-ticket concurrent calls for the same call_id

Status: accepted (targeted audit ahead of the first real call — two real
gaps found and closed, no new product feature)

The operator asked, explicitly, for exactly the kind of check ADR-063's own
test count couldn't by itself prove: whether the new voice_call_ticket
mechanism (ADR-063) could be replayed, and whether a manipulated/buggy
browser could still trigger multiple concurrent real calls server-side even
with the JS-level double-start guard in place. Both turned out to be real,
unaddressed gaps in the ADR-063 design — not defended by anything already
built, and not exercised by any of the 357 passing tests.

**Gap 1 — ticket replay.** `decode_voice_call_ticket()` verifies signature,
expiry, purpose, and (at the webhook) that the referenced call/tenant/
consent are still current — but nothing marked a ticket as used. Within its
5-minute lifetime, the exact same `replica_voice_ticket` value could be
resent to `POST /webhooks/twilio/voice-outbound` an unlimited number of
times, each producing valid TwiML. Confirmed this is not hypothetical:
nothing in `_resolve_call_for_media_stream()` or `MediaStreamPipeline`
prevents two independently-placed real calls from both attaching a Media
Stream to the same `call_id` — two concurrent real conversations' audio
would be interleaved into one call's `Turn`/`Suggestion` records.

The operator's own constraint made the naive fix wrong: Twilio's own
documented behavior is to retry a voice webhook request if it doesn't get a
timely response, resending the IDENTICAL request (same params, same
signature) for the SAME call-setup attempt — "ticket invalid after first
use" would break that legitimate retry and fail a real call for no reason.
The fix needed to tell "same attempt, retried" apart from "second,
independent attempt reusing the ticket" using a fact ticket verification
alone cannot see: **Twilio's own `CallSid`** — allocated once per real
call-setup attempt and stable across that attempt's own retries (already an
established, trusted fact in this codebase — the call-status webhook has
required and correlated on `CallSid` since ADR-029/054).

**Fix**: `create_voice_call_ticket()` now stamps every minted ticket with a
`jti` (a fresh UUID, distinct from anything Twilio provides).
`app/services/voice_call_guard.VoiceTicketLedger.check_and_record(jti,
call_sid)` (new, small, in-memory — see "what stayed in-memory" below)
returns `'new'` (first use), `'retry'` (same jti + same CallSid — a
legitimate Twilio retry, proceed identically) or `'conflict'` (same jti + a
DIFFERENT CallSid — a second, independent attempt; reject, HTTP 403). The
webhook now requires `CallSid` (fails closed, 400, if absent — a real
Twilio request always includes it) and calls this check after every
existing verification, right before generating TwiML.

**Gap 2 — cross-ticket concurrency.** Even with replay closed, TWO
DIFFERENT, individually valid tickets for the SAME `call_id` (e.g. two
browser tabs, or a race on `/api/voice/access-token`) would each pass every
existing check independently and could both place a real call concurrently
— the same audio-interleaving risk as Gap 1, just via two legitimate
tickets instead of one replayed one. The operator explicitly named this as
the server-side backstop the existing JS double-start guard (ADR-063 item
1) cannot provide on its own against a manipulated client.

**Fix**: `VoiceCallConcurrencyLock` (same new module) — at most one real
call in flight per `call_id`. Acquired by the webhook the moment it commits
to placing a real call (only on a `'new'` ticket-use verdict — a `'retry'`
already holds it from the original attempt), refused with HTTP 409
otherwise. Released, unconditionally, in `app/main.py`'s `/ws/twilio-media`
handler's single `finally` block — covering every real exit path of that
call's Media Stream (a clean `'stop'`, an unclean disconnect, or a pipeline-
construction failure with no `pipeline` object ever created) via one
`resolved_call_id` variable set as soon as the Call is resolved, rather than
three separate copies of a release call that could drift out of sync. A
30-minute TTL is a safety net ONLY, for the residual case where neither
release path ever fires (e.g. TwiML is returned but the call never reaches
a Media Stream at all) — never the primary mechanism, so one failed attempt
never requires a server restart to recover from ("sauberer Reset nach
Ended/Failed", satisfied by the explicit release path, not the TTL).

**Scope deliberately NOT extended, stated plainly rather than silently
assumed**: no per-user (as opposed to per-call_id) concurrency lock — the
operator flagged this as "idealerweise", not required, and every REPLICA
call already belongs to exactly one seller/one test session in the data
model, so a per-call_id lock already prevents the realistic double-testcall
scenario without inventing a second, coarser lock with its own edge cases.
No DB-backed ledger/lock — both new structures are in-memory, single-
instance-scoped, explicitly matching the same already-documented
constraint `app/services/live_push.LiveSuggestionHub` states for this
pilot's deployment shape (docs/DEPLOYMENT.md): this is the manual, one-
operator real-call test path, not scaled product infrastructure, and adding
a migration for it would have been exactly the "größerer Refactor" ruled
out for this pass. No live-UI change — the lock/replay checks happen
entirely between Twilio and the server (the browser never sees a 409/403
from this path directly, since Twilio — not the browser — calls the
webhook), so there was nothing here for `app/static/live.html` to surface
that ADR-063's existing preflight/call-state/analysis-state UI doesn't
already cover.

**Regression coverage**: 9 new tests — `tests/test_voice_outbound.py`
(same-ticket-same-CallSid is idempotent and returns byte-identical TwiML;
same-ticket-different-CallSid is rejected; missing `CallSid` rejected;
missing `jti` claim rejected; two independently-minted tickets for the same
call — first succeeds, second gets 409 while the first is "in progress";
and, after directly releasing the lock, a third succeeds — proving the 409
is temporary, not permanent) and a new `tests/test_voice_call_guard.py`
(three full `/ws/twilio-media`-level tests proving the lock is genuinely
released by a clean stop, an unclean disconnect, and a pipeline-
construction failure respectively — not asserted against the lock object
directly, but by confirming a SECOND real call attempt is accepted
afterward). Full suite: 366/366, run three times consecutively — the
+9 over ADR-063's 357/357 baseline are exactly these new tests, zero
regressions to any previously-existing behavior.

**Verdict: ready for the first real call.** Both gaps the operator asked
about are now closed and regression-tested; no other unaddressed gap was
found in this pass. Nothing about `/api/voice/access-token`,
`app/static/live.html`, or any other part of the ADR-060/061/062/063
browser-call path needed to change — this ADR is confined entirely to
`POST /webhooks/twilio/voice-outbound`'s own request-handling and the two
new small guard structures it now calls.

## ADR-065 — The concurrency lock's only release path required `/ws/twilio-media` to connect at all; a call that never gets that far would hold it for the full 30-minute TTL

Status: accepted (a residual gap the operator asked to specifically check
for, ahead of the actual first real call using a live TwiML App)

With the real IE1 TwiML App now created and its Voice Request URL pointed
at this deployment's tunnel, the operator asked two narrow questions: is
the tunnel currently reachable, and is `VoiceCallConcurrencyLock`'s release
path (ADR-064) actually closed for every way a real call can end — not just
the ones already tested.

**Tunnel reachability could not be checked from this session.** This
session's own outbound network egress policy blocks `trycloudflare.com`
entirely (confirmed via the proxy's own diagnostic status endpoint —
`connect_rejected`/403 on the CONNECT, the exact same class of egress
denial already documented for `www.twilio.com` earlier in this project) —
not a statement about the tunnel or the server being down, simply that this
sandboxed environment cannot reach that domain at all. The operator's own
machine — where the tunnel actually terminates — is the only place this can
be confirmed; `curl https://bold-pmc-passage-assured.trycloudflare.com/api/health`
(expect `{"status":"ok",...}`) or opening that URL in a browser is
sufficient.

**The lock-lifecycle question was a real, confirmed gap.** Every test added
for ADR-064 proved the lock releases correctly once `/ws/twilio-media`
connects — but the webhook acquires the lock at TwiML-generation time,
BEFORE Twilio has attempted the `<Dial>` or the `<Stream>` WebSocket
handshake at all. A call that fails before ever reaching that
WebSocket — busy, no-answer, a rejected dial, or the `<Stream>` handshake
itself failing (TLS/DNS/tunnel hiccup, exactly the kind of failure a fresh
`trycloudflare.com` tunnel is prone to) — left the ONLY release path
(`/ws/twilio-media`'s own `finally` block) never reached, holding the lock
for its full 30-minute safety-net TTL. Confirmed via Twilio's own
documented `<Stream statusCallback>` mechanism (`StreamEvent` values
`stream-started`/`stream-stopped`/`stream-error`, delivered independently
of whether the Media Stream WebSocket itself ever connects) that this
mechanism exists specifically to cover this blind spot.

**Fix, exactly as scoped by the operator, nothing broader:**
`twilio_voice_outbound()`'s generated `<Stream>` now carries
`statusCallback`/`statusCallbackMethod="POST"`, pointed at a new
`POST /webhooks/twilio/stream-status` endpoint — `replica_call_id` travels
in that URL's own query string (Twilio's statusCallback payload has no
notion of our custom `<Parameter>` values; those only ever reach the Media
Stream WebSocket's `start` event), verified the same way every other
webhook here verifies a signed URL that includes a query string. On
`stream-stopped` or `stream-error`, it calls
`VoiceCallConcurrencyLock.release()` — a no-op by construction for an
already-released or never-held call_id, so this is safe to call
idempotently (Twilio's own retries included) and safe to race against
`/ws/twilio-media`'s own release of the very same lock. `stream-started` is
acknowledged and otherwise ignored — the lock is already held from the
moment TwiML was returned. The 30-minute TTL remains as the final,
last-resort fallback for the (now much narrower) case where neither this
callback nor the Media Stream WebSocket's own lifecycle ever fires at all.

**What did NOT change**: no new product feature, no change to the ticket/
replay logic from ADR-064, no change to `/ws/twilio-media` itself (its own
`finally`-block release stays exactly as it was — this is a second,
independent release path, not a replacement) — this new endpoint's ONLY
job is releasing the lock for the one gap that path could not cover. The
§4a REST-based test path (a manually-configured Twilio Console TwiML Bin)
is unaffected: it never acquires `VoiceCallConcurrencyLock` in the first
place (that lock is only ever taken inside `twilio_voice_outbound()`, the
ADR-060 browser-ticket path's own webhook), so it needs no `statusCallback`
addition for this purpose.

**Regression coverage**: 7 new tests in `tests/test_voice_outbound.py` —
missing/wrong signature rejected; the exact scenario this ADR exists for
(`stream-error` after a webhook call that never reaches `/ws/twilio-media`
releases the lock, confirmed by a subsequent call succeeding where it would
otherwise 409); `stream-stopped` also releases; `stream-started` does NOT
release (still 409s); three repeated `stream-error` calls for the same
call_id are all accepted without error (idempotency); and a missing/
malformed `replica_call_id` query parameter is handled without a crash.
Full suite: 373/373 (up from ADR-064's 366/366), run three times
consecutively, zero regressions.

**Verdict for Call #1: NOT READY yet — pending the operator's own
confirmation of tunnel reachability (this session cannot check it); the
lock-lifecycle question itself is now fully closed and regression-tested.**

## ADR-066 — Foresight: a predictive conversation decision engine, documented as a planning-only architecture ahead of implementation

Status: **proposed / documentation only — no code, no migration, no
production path change**. This ADR exists so that once Call #1's baseline
is proven (see "Sequencing" below), Foresight V1 can begin implementation
directly, without re-litigating the concept. Nothing in this ADR is built
yet. It must not become the reason the first real call gets delayed.

### Why this ADR exists now, not later

The operator, after reviewing REPLICA against the closest real
competitors (Clari Copilot/Wingman, Gong, Balto, Dialpad AI Live Coach,
Avoma, Convo, Cresta — see the same conversation's competitive research),
concluded that REPLICA's most differentiated, most defensible future
capability is not a better cue-card retriever, but a system that reasons
about **which seller action to take next by estimating its likely effect
on the prospect**, before the seller speaks — not just "what should the
seller say" but "if the seller uses strategy X vs. Y vs. Z, which one most
likely moves the conversation state forward." That idea, and its full
technical specification (data model, evaluation methodology, safety
constraints), is captured here in full so it survives to when it's
actually built.

### The core shift: HEAR → UNDERSTAND → PREDICT → DECIDE → OBSERVE → LEARN

Today's loop is `Prospect speaks → REPLICA understands → REPLICA shows
"SAG JETZT"`. Foresight adds two new stages *before* the existing decision
and two new stages *after* it, without replacing anything: the system
additionally asks "what would each plausible seller action likely produce
next," decides among candidates using that estimate (in shadow mode only —
never surfaced to the seller in V1), then observes what actually happened
and learns from the gap between prediction and reality.

We are explicitly **not** predicting the prospect's next sentence.
We predict **semantic reaction classes / conversation-state transitions**
(e.g. `reveals_budget`, `skepticism`, `disengagement`) — a classification
problem, not a language-generation problem.

### The central design principle: Decision Intelligence, not Conversation Prediction

This is the single most important architectural rule in this ADR, added
explicitly per the operator's own correction during this ADR's drafting —
it is a first-class design principle, not an implementation detail buried
in a schema:

> Foresight never predicts a single, global "what will the prospect do
> next" for the conversation. It predicts a **separate reaction
> distribution for each candidate seller action**:
> `P(prospect_reaction | conversation_state, candidate_seller_action)`.
>
> Not: *"the prospect will probably be skeptical."*
> But: *"IF the seller uses candidate A → 18% skepticism, 52% elaborates.
> IF the seller uses candidate B → 47% skepticism, 21% elaborates."*

This counterfactual separation — one prediction per candidate action, not
one prediction per conversation — is what turns a cue-card retriever
(content lookup) into a decision-support system (comparing the likely
consequences of different moves before choosing one). No competitor
researched has a documented public implementation of this specific
mechanic; it is treated here as REPLICA's most valuable and most
defensible differentiator, and the data model below (`reaction_prediction`
keyed 1:1 on `decision_candidate_id`, never on the decision alone) exists
specifically to make this structurally impossible to collapse back into a
single global prediction later.

### Reaction Ontology V1 (versioned, fixed — not free-text per call)

`elaborates`, `reveals_pain`, `reveals_budget`, `reveals_authority`,
`reveals_timing`, `asks_question`, `positive_engagement`, `skepticism`,
`price_resistance`, `competitor_defense`, `deflection`, `disengagement`,
`next_step_acceptance`, `other`, `uncertain`. Every prediction and every
observed reaction is tagged with `reaction_ontology_version`; the ontology
may grow later, but a historical prediction must always remain
reproducible against the ontology version it was made under — never
silently reinterpreted against a newer one. A reaction has exactly one
`primary_reaction` and zero or more `secondary_reactions` (e.g. "sounds
interesting, but no budget this year" → primary `reveals_budget`,
secondary `positive_engagement`) — deliberately not an unbounded
multi-label free-for-all.

### Seller Action Ontology V1 (versioned strategy types, not raw sentences)

`clarify`, `discover_pain`, `discover_impact`, `discover_budget`,
`discover_authority`, `discover_timing`, `reframe_value`,
`provide_evidence`, `social_proof`, `differentiate_competitor`, `de_risk`,
`handle_price`, `challenge_assumption`, `advance_next_step`,
`hold_position`, `intentional_silence`. The concrete sentence is the
*wording* realizing a strategy type — this lets later analysis ask "does
`clarify` work better than `differentiate_competitor` here" instead of
being stuck comparing individual, non-reusable sentences.

### Candidate generation, prediction, and the temporal-integrity rule

At a decision point, Foresight generates **2–4** plausible candidate
seller actions (never 10–20) from conversation state, phase, detected
objection/intent, prior turns, already-asked questions, tenant playbook
rules, and compliance constraints — combining the existing `SalesBrain`
rule engine with an LLM constrained to an allowed strategy library (never
a free-form strategy). For each candidate, a reaction predictor computes a
full probability distribution over the reaction ontology (must sum to
1.0, schema-validated; an invalid distribution is discarded, not
coerced). These V1 numbers are **model estimates, not calibrated
probabilities** — a stated "72%" does not mean real-world 72% until
`expected_calibration_error` is later measured against outcomes and
explicitly reported as such; they must never be shown to the seller as if
they were real probabilities.

**Temporal integrity is a hard, non-negotiable rule.** A prediction must
be provably sealed — `prediction_sealed_at` — before the prospect's actual
next turn begins (`first_target_audio_at`, or the earliest provable
prospect-turn time if audio timing isn't reliably available). Every
prediction carries `prediction_created_at`, `prediction_sealed_at`,
`input_cutoff_timestamp`, `source_turn_id`, `target_turn_index`,
`first_target_audio_at`, `first_target_transcript_at`. If
`prediction_sealed_at >= first_target_audio_at` (or the fallback), that
prediction is disqualified from evaluation and marketing claims —
`valid_for_evaluation = false`, with `invalid_reason` recorded — no
exceptions, no silent inclusion. This is the single mechanism that
prevents any future claim of "REPLICA predicted the next reaction" from
being unfalsifiable leakage.

### Shadow Mode is mandatory for V1 — no exceptions

`FORESIGHT_MODE` defaults to `shadow` (`off` | `shadow` | `live`).
In shadow mode, Foresight computes and stores everything above, observes
the actual seller action and actual prospect reaction, and scores its own
predictions after the fact — but **never touches the existing `SAG
JETZT` path**. The seller sees nothing different. The existing live-
suggestion pipeline (`app/services/sales_brain.py` +
`app/services/conversation_state.py` + `app/services/live_push.py`)
remains the sole source of truth for what the seller actually sees, for
the entire V1 phase. This is what lets us later measure "what would
Foresight have recommended" without changing seller behavior or risking
the one thing that must work: the existing suggestion path.

### Seller adherence — never attribute an outcome to an unused recommendation

Every decision distinguishes `recommended_action` (Foresight's
candidate) from `actual_seller_action` (what the seller really said,
reclassified into the same strategy ontology), with an explicit
`adherence_type`: `exact`, `semantic` (same strategy, different wording),
`partial`, `ignored`, `unknown`. REPLICA must never claim "our
recommendation caused outcome X" when the seller didn't use it — this
field is what makes that claim falsifiable.

### Reaction Delta V1 — observable state changes, not invented psychological scores

No fabricated composite metrics like `trust = 0.73` without a real
measurement method behind them. V1's Reaction Delta is based on discrete,
observable state changes only (e.g. objection present → budget stated;
no next step → meeting accepted; conversation deepens vs. ends).
Probabilistic/composite scores are an explicit later stage, not V1.

### Data model (six logically separate entities — never one giant JSON blob)

Adapted to this codebase's naming conventions, all under `company_id`
tenant scoping like every other table in `app/models.py`:

- **`conversation_decision`** — one per decision point: `call_id`,
  `source_prospect_turn_id`, `conversation_state_version`,
  `state_snapshot`, `sales_phase`, `objection_type`, `intent_type`,
  `mode` (`shadow`/`live`), `engine_version`, `created_at`.
- **`decision_candidate`** — 2-4 rows per decision: `decision_id`,
  `strategy_type`, `strategy_version`, `proposed_wording`,
  `candidate_rank`, `generated_at`.
- **`reaction_prediction`** — **exactly one row per `decision_candidate`**
  (the counterfactual-separation principle above, enforced structurally
  via this foreign key, never denormalized onto `conversation_decision`):
  `decision_candidate_id`, `prediction_distribution` (JSON, sums to 1.0),
  `top_reaction`, `model_provider`, `model_name`, `model_version`,
  `prompt_version`, `ontology_version`, `generation_latency_ms`,
  `created_at`, `sealed_at`, `input_cutoff_at`, `valid_for_evaluation`,
  `invalid_reason`.
- **`seller_action_observation`** — one per decision once the seller has
  spoken: `decision_id`, `seller_turn_id`, `actual_strategy_type`,
  `matched_candidate_id` (nullable), `adherence_type`,
  `classification_confidence`, `observed_at`.
- **`prospect_reaction_observation`** — one per decision once the
  prospect has responded: `decision_id`, `prospect_turn_id`,
  `primary_reaction`, `secondary_reactions`, `ontology_version`,
  `classification_confidence`, `ground_truth_source` (`automatic` /
  `human_reviewed` / `adjudicated`), `observed_at`.
- **`decision_outcome`** — attached later from existing call-outcome data:
  `decision_id`, `immediate_outcome`, `meeting_booked`, `meeting_held`,
  `opportunity_created`, `opportunity_won`, `revenue`, `updated_at`.

No accuracy claim may be published from `automatic` ground truth alone —
a small human-reviewed gold set (`human_reviewed`/`adjudicated`) is
required before any calibration or accuracy number leaves this system.

### Evaluation — instrumented from day one, with mandatory baselines

Metrics: `top_1_accuracy`, `top_3_recall`, `brier_score`, `log_loss`,
`expected_calibration_error`, `coverage`, `abstention_rate`,
`prediction_latency_ms`, `sealed_before_target_rate`. Two baselines are
**mandatory**, not optional: `majority_reaction_baseline` (always predict
the most common reaction) and `state_only_baseline` (predict from
conversation state alone, withholding the candidate seller action). If
Foresight's full model doesn't clearly beat `state_only_baseline`, the
seller-action signal isn't adding real predictive value and the whole
premise needs revisiting — before any uplift claim is made anywhere.

### Abstention is a feature, not a failure mode

When state is unclear, prediction is too diffuse/high-entropy, speaker
mapping or transcript confidence is low, candidates are too similar, or
grounding is missing, Foresight sets `abstain = true` rather than forcing
a low-confidence guess. Long-term, this same "know when not to say
anything" capability is meant to inform the *live* intervention policy
too — REPLICA should learn not just what to say, but when to stay silent,
directly continuing the product's existing "one SAG JETZT, not constant
noise" philosophy (ADR-063's stale-suggestion handling is the closest
existing precedent for this kind of restraint).

### Explicitly out of scope for V1 (do not build yet)

Exact next-sentence prediction (semantic reaction class only — never
generate the prospect's likely words); multi-turn lookahead beyond one
turn; reinforcement learning of any kind; self-modifying prompts;
contextual bandits or automatic strategy optimization in the production
path; any causal claim from a single observed (action → reaction) pair —
unchosen candidates' predicted outcomes are counterfactual estimates,
never observed reality, and a real causal claim needs controlled
experiments/randomization/bandits/uplift modeling, explicitly a later
stage (Stage 5–7 below), not V1.

### Staged long-term evolution (documented, not scheduled)

1. Reaction prediction (this ADR's V1 scope). 2. Candidate action
simulation. 3. Calibrated reaction predictor. 4. Customer/segment-specific
prediction. 5. Intervention policy. 6. Contextual bandits/uplift learning
among already-approved strategies. 7. Causal outcome optimization. Stages
5–7 are explicitly not current implementation scope and are not
authorized by this ADR.

### Mapped against the existing codebase

**Reusable as-is (no change needed):**
- `app/services/sales_brain.py` (`classify_sales_event`, `resolve_phase`,
  `decide`) — becomes one of Foresight's candidate-generation inputs, used
  read-only; its own behavior and the existing `SAG JETZT` output are
  untouched.
- `app/services/conversation_state.py` / `conversation_state_store.py` —
  the existing `ConversationState`/`ConversationStateEvent` history is
  exactly the "what did REPLICA know at this point" record Foresight
  needs as `state_snapshot` input; no schema change required to consume
  it.
- `app/models.Suggestion.feedback` (good/usable/bad) and `Turn` — already
  exactly the kind of seller-facing outcome signal `decision_outcome`
  will eventually want to correlate against; already collected today,
  independent of Foresight.
- `app/services/live_push.LiveSuggestionHub` — untouched; Foresight in
  shadow mode never publishes through it.
- Speaker-mapping (`app/streaming/speaker_mapping.py`) and the Deepgram
  pipeline (`app/streaming/pipeline.py`, `deepgram_provider.py`) — pure
  inputs, read-only, no change.

**Would need extending (later, not now):**
- `app/streaming/pipeline.MediaStreamPipeline._process_turn` (or an
  equivalent turn-finalization hook) — the natural integration point
  where a decision point would be raised, strictly as an async,
  non-blocking side-call so it can never add latency to the existing
  `SAG JETZT` render path (ADR-063/ADR-051's latency-measurement work is
  directly reusable for `total_foresight_ms` instrumentation).
- `app/config.Settings` — new settings (`FORESIGHT_ENABLED`,
  `FORESIGHT_MODE`, later `FORESIGHT_CANDIDATE_SIMULATION_ENABLED`,
  `FORESIGHT_DEBUG_UI_ENABLED`) alongside the existing
  `REPLICA_ASR_PROVIDER`-style provider-selection pattern already
  established there.

**Entirely new components (none exist yet):**
- The six tables above, plus corresponding SQLAlchemy models in
  `app/models.py` and one Alembic migration (not run — this ADR
  authorizes documentation, not the migration itself).
- A `ForesightEngine` service (name to be finalized) implementing
  candidate generation + reaction prediction, isolated from the existing
  suggestion path — likely `app/services/foresight/` given this
  codebase's existing `app/services/` convention.
- A minimal, developer-only debug panel inside `live.html`'s existing
  `<details>` debug block (ADR-063's precedent) — never a new top-level
  seller-facing UI in V1.

**Migrations needed later (not now):** one Alembic revision adding all
six tables, tenant-scoped (`company_id`) and foreign-keyed to `Call`,
matching this codebase's existing migration style (see
`migrations/versions/0cd3645f7d6d_add_conversation_states.py` for the
precedent this would follow).

**Tests that will be needed (not written yet):** schema validation
(distribution sums to 1.0, invalid distributions discarded); the
temporal-integrity rule as an executable invariant (`prediction_sealed_at
< first_target_audio_at`, with a regression test proving a violating
prediction is excluded from evaluation); shadow-mode isolation (a
Foresight failure/exception must never affect the existing `SAG JETZT`
path — fail-open for Foresight, fail-closed remains exactly as strict for
security/consent per ADR-063); adherence classification; baseline
comparison plumbing.

**Integration points identified, no code touched:** turn finalization in
`MediaStreamPipeline`; `ConversationState` as the state-snapshot source;
`Suggestion.feedback` and eventual `Meeting`/`Deal` records as
`decision_outcome` inputs; `TurnLatencyTrace`'s existing latency-metric
pattern as the template for Foresight's own timing instrumentation.

### What must NOT change when Foresight V1 eventually starts

Call state, analysis state, tenant isolation, voice-ticket security,
consent checks, speaker mapping, the Deepgram pipeline, live push, the
existing `SAG JETZT` path, Render-ACK, current latency measurement, Call
Review, and the existing test suite — all exactly as they are today.
Foresight runs parallel and fail-open (a Foresight crash never affects
the call or the existing suggestion pipeline); fail-closed remains
absolute for security/consent, unchanged.

### Sequencing — this is the actual decision this ADR makes

**Nothing above is implemented. No table is created. No migration runs.
No LLM call is added. The existing `SAG JETZT` path is not touched.**

The operator explicitly wants an unmodified, measured baseline of the
current system before Foresight exists at all — otherwise there is no
clean before/after to measure Foresight's actual effect against. Before
any Foresight code is written, the following must be demonstrated on a
real end-to-end call:

1. A real human-to-human call actually connects.
2. Both speakers are received and correctly attributed.
3. Deepgram delivers real transcripts.
4. Prospect turns are correctly detected.
5. The existing `SalesBrain` processes the call.
6. `SAG JETZT` is actually delivered live.
7. Render-ACK and real RSL/latency data are recorded.
8. The call and analysis run stably through to the end.
9. The resulting stored call data is traceable/reconstructable.

Only after these nine are met does Foresight V1 begin, as its own
clearly separated development track, starting exclusively in shadow
mode.

## ADR-067 — Post-mortem: why the first real call took a full day, and the five independent bug classes it actually was

Status: **incident report — no open action items block further work; the
prevention checklist below is the durable artifact.**

### Summary

On 2026-09-22/23, the first real end-to-end call (browser → Twilio →
real phone ringing → a real person answering) was successfully placed.
Getting there took roughly a full day and looked, at almost every step,
like "the same bug again" — every failure surfaced as either a generic
Twilio Voice SDK error (`53000`, `31000`, `31603`) or the identical HTTP
`403 Invalid webhook signature` response from our own server. In
reality this was **five unrelated bug classes**, each masquerading as
the previous one, compounding into a long trial-and-error session. This
ADR exists so the next person (human or AI) who sees any of these
symptoms can jump straight to the right fix instead of re-deriving it.

None of these were REPLICA application-logic bugs. All five were
environment/configuration issues: regional resource scoping on the
Twilio side, an ephemeral tunnel, two on-disk copies of the same repo,
and a Python stdlib default. **Zero lines of `app/` business logic
changed as a result of this investigation** (the two code changes made —
`enableImprovedSignalingErrorPrecision` in `live.html` and `python -u` in
`run.sh` — are both pure diagnostics/dev-ergonomics, not fixes to
application behavior).

### The five bug classes, in the order they had to be found

**1. Twilio resources are scoped per data-residency region, and nothing
warns you when they aren't.** This account's home region is `IE1`
(`TWILIO_REGION=ie1`, `TWILIO_EDGE=dublin`). Verified Caller IDs are not
a supported feature in IE1 at all (only US1/AU1 — confirmed against
Twilio's own regional feature-availability documentation), which forced
a temporary, explicitly-approved move to `US1`/`ashburn` purely to prove
the pipeline end-to-end. That move then required recreating, one at a
time, **every other region-scoped credential/resource**, because none of
them carry over between regions even though the Twilio Console UI gives
no indication of this:
   - the **Auth Token** used to verify inbound webhook signatures (IE1
     has its own Primary Auth Token, distinct from the account's
     default/US1 one shown on the main dashboard);
   - the **API Key** (SID+secret) used to sign the browser's Voice
     Access Token (an IE1-scoped key produces `AccessTokenInvalid
     (20101)` once the token specifies `region=us1`; the *first* US1 key
     we created also failed independently, with Twilio error `8001
     "actor doesn't have any assertions"` — it had no permissions
     attached and had to be recreated as a proper Standard key);
   - the **TwiML Application** referenced by `outgoingApplicationSid`
     (confirmed via direct REST fetch: `client.applications(sid).fetch()`
     scoped to `region='us1'` returned `404` for the IE1-created app —
     it does not exist in US1 at all, which is why Twilio's gateway
     produced only a generic `UnknownError (31000)` and never even
     called our webhook).

   *Prevention:* treat `TWILIO_REGION`/`TWILIO_EDGE`, the Auth Token, the
   API Key, and the TwiML Application as **one atomic unit**. Never
   change the region without recreating all three of the others in the
   Twilio Console with that exact region selected first (the Console's
   region dropdown, where present, is the source of truth — it is easy
   to have it silently default back to the account's home region).

**2. Ephemeral Cloudflare quick tunnels (`cloudflared tunnel --url ...`)
change hostname on every restart and can die silently.** One tunnel
outage surfaced as Twilio's gateway returning HTTP `530` for our webhook
URL; a later one surfaced as `curl` returning status `000` (DNS/connect
failure) while `cloudflared`'s own log showed `"Unauthorized: Tunnel not
found"` — i.e. Cloudflare had invalidated the tunnel server-side and it
was retrying forever into a dead end. Every time the tunnel is restarted,
**two separate places** must be updated together, or the failure again
looks identical to bug class 1 or 3:
   - the TwiML Application's Voice Request URL (Console, or the
     `client.applications(sid).update(voice_url=...)` REST call used
     throughout today), and
   - `REPLICA_PUBLIC_BASE_URL` in `.env` — this is the value
     `app/main.py` uses to *reconstruct* the exact URL Twilio signed,
     for webhook-signature verification (`app/webhooks/security.py`).
     It is **not** derived from the incoming request automatically
     (the server only ever sees `127.0.0.1` behind the tunnel), so a
     stale value here produces the exact same `403 Invalid webhook
     signature` response as a wrong Auth Token, with no way to tell
     the two apart from the HTTP response alone.

   *Prevention:* the durable fix is to stop using an anonymous quick
   tunnel at all and switch to a Cloudflare **named tunnel** (stable
   hostname across restarts, free with a Cloudflare account) — this
   would have prevented essentially all of bug class 2 outright. Until
   that migration happens, treat "new tunnel URL" and "update
   `REPLICA_PUBLIC_BASE_URL` + the TwiML App's voice_url" as one
   inseparable action, and verify the tunnel independently of Twilio
   first (`curl -X POST <tunnel-url>/webhooks/twilio/voice-outbound`) —
   any non-timeout HTTP status, even our own `403`, proves the tunnel
   itself is alive and the problem is elsewhere.

**3. Two separate local clones of the repo existed on disk**
(`~/HaydarHinisli/replica-handoff` and `~/Downloads/replica-handoff`),
and the zsh prompt shows only the relative folder name (`replica-handoff`
in both cases), never the full path. `.env` edits, verified correct by
sha256 hash comparison, repeatedly failed to reach the running server —
because the edits and the running `./run.sh` process were, at least
once, reading two physically different `.env` files in two different
directories, with no visible way to tell from the terminal prompt alone.

   *Prevention:* the stray `~/Downloads/replica-handoff` copy should be
   deleted or renamed so it can never be `cd`'d into by mistake again.
   Going forward, every command in a debugging session like this one
   should start from the one canonical absolute path
   (`/Users/haydarhinisli/HaydarHinisli/replica-handoff`), not a bare
   `cd replica-handoff` or a prompt that only shows the folder's last
   path segment.

**4. Python defaults to block-buffered (not line-buffered) stdout when
it is redirected to a file** — exactly what `./run.sh > replica.log
2>&1` does. This is unrelated to Twilio entirely, but repeatedly made it
look like a request (a real call's webhook, or a diagnostic `curl`)
"never arrived" in `replica.log`, when the log line may simply not have
been flushed to disk yet. Fixed permanently: `run.sh` now invokes
`python -u -m uvicorn ...` (commit `225d734`).

   *Prevention:* already fixed in `run.sh` — no further action needed.
   If a future dev script redirects Python output to a file again, add
   `-u` (or `PYTHONUNBUFFERED=1`) from the start.

**5. A stray/orphaned server process** left listening on port 8000 from
an earlier interrupted `./run.sh` caused a separate, shorter-lived
episode of spurious `409` concurrency-lock errors earlier in the day
(unrelated to bug classes 1–4, already resolved by `lsof -ti:8000 |
xargs kill -9` before the region-switch work began).

### How to tell these five apart quickly, next time

All five can present as an HTTP `403 Invalid webhook signature`, a
generic Voice SDK error, or "nothing happens" — the following checks
distinguish them in under a minute, cheapest first:

1. `curl -s -o /dev/null -w "%{http_code}\n" -X POST
   <tunnel-url>/webhooks/twilio/voice-outbound` — anything other than a
   real HTTP status (timeout, `000`, or a Cloudflare `5xx`) means bug
   class 2 (tunnel), independent of Twilio entirely.
2. Compare `auth_token_sha256` in the `replica.webhooks` failure log
   against a locally computed `echo -n "<expected-token>" | shasum -a
   256` — a mismatch means bug class 1 (wrong token) or class 3 (server
   reading the wrong `.env`); an unexpected but *matching* value that
   still fails means bug class 2 (URL/`REPLICA_PUBLIC_BASE_URL`
   mismatch), since the signature math itself is then correct for a URL
   Twilio no longer calls.
3. `client.applications(<TWILIO_TWIML_APP_SID>).fetch()` with an
   explicit `region=` matching whatever `TWILIO_REGION` currently is —
   a `404` means the TwiML App does not exist in that region (part of
   bug class 1).
4. `lsof -a -p $(lsof -ti:8000) -d cwd` — shows the exact absolute
   directory the *running* server process was started from; compare it
   character-for-character against the directory any `.env` edit was
   made in (bug class 3).

### What did NOT change

No `app/` business logic, no data model, no migration, no test
behavior, and no security/consent/auth logic changed as a result of
today's investigation. The two code changes made
(`enableImprovedSignalingErrorPrecision` in `app/static/live.html`, and
`python -u` in `run.sh`) are both diagnostics/dev-ergonomics fixes, not
behavior changes to the product itself. `docs/DECISIONS.md` ADR-066
(Foresight) and its nine-point sequencing gate are unaffected; Call #1's
baseline (browser ↔ real phone, full audio in both directions) is not
yet fully proven — audio was not yet flowing from the browser
microphone to the callee when this ADR was written, which is the
immediate next item, tracked separately from this ADR.
