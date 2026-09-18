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

## ADR-031 — Event/Turn Identity & Deduplication: exactly-once processing per real turn
Status: accepted

Once Sprint 2 introduces streaming ASR, the same real spoken turn can legitimately
reach REPLICA's endpoints more than once: a webhook/provider retry, a websocket
reconnect mid-utterance, a provider re-sending a "final" transcript it already sent,
or an interim revision that looks like a new event. None of these may trigger a
second state transition or a second Copilot suggestion for the same turn — that would
double-count `turn_index`, corrupt phase progression, and show the seller two
suggestions for one thing the prospect said once.

`ProcessedTurnEvent` (new table `processed_turn_events`) is the single choke point
enforcing "exactly once", scoped to `(call_id, action, turn_id)` via a unique
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
