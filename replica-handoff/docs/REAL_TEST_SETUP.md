# Real Provider Setup & First Live Call — Operator Checklist

Purpose: everything needed to run REPLICA's first real end-to-end test call
(Twilio IE1 → real phone call → real Media Stream → Deepgram EU → real
transcript → Turn Detection → SalesBrain → Live Suggestion → browser push →
Render-ACK → real latency measurement), against real provider accounts, with
consenting test persons only. No new code is required for this — everything
below uses endpoints and mechanisms already built and tested (Sprints 2/2B/3A,
Fix-Sprint, ADR-052).

Never put a real secret value into this file, a commit, a log line, or any
other document in this repo. Only variable *names* and their *purpose* are
listed here.

## 1. Environment variables

### Core / networking
| Variable | Purpose |
|---|---|
| `REPLICA_ENV` | Set to `production` for this test (NOT `local`). Activates two fail-closed gates that stay off in local dev: wss-only enforcement on `/ws/twilio-media` (`app/streaming/media_stream_security.py`) and the Origin allowlist on `/ws/live/{call_id}` (`app/services/ws_origin.py`, ADR-051/052). |
| `REPLICA_PUBLIC_BASE_URL` | The exact public HTTPS base URL (e.g. `https://replica-test.example.com`, no trailing slash). Twilio's `X-Twilio-Signature` is validated against this — a mismatch silently fails every webhook/media-stream handshake closed (403 / connection refused). |
| `REPLICA_ALLOWED_WS_ORIGINS` | Comma-separated browser origins allowed to open `/ws/live/{call_id}` (the seller's live-suggestion WebSocket). Must contain the exact origin (scheme+host, no path) the seller's browser will use — normally the same origin as `REPLICA_PUBLIC_BASE_URL`. **Required** once `REPLICA_ENV != local`: empty/unset rejects every connection. |
| `REPLICA_DEMO_MODE` | Recommend `true` for this one supervised test only — reuses the seeded demo tenant/seller/login (`haydar@replica-pilot.example`) so you don't need to create a tenant/user by hand. Set `false` for anything beyond this single test. |

### Database
| Variable | Purpose |
|---|---|
| `REPLICA_DATABASE_URL` | Real PostgreSQL connection string, `postgresql+psycopg://<user>:<password>@<host>:<port>/<db>`. Migrations run automatically on app startup (`app/migrate.py`) — no manual `alembic upgrade` step needed. |

### Auth
| Variable | Purpose |
|---|---|
| `REPLICA_JWT_SECRET` | Long random secret signing seller login session tokens. MUST be overridden from the dev default (e.g. `openssl rand -hex 32`), generated fresh, never committed. |
| `REPLICA_JWT_EXPIRES_MINUTES` | Optional, session token lifetime in minutes (default 480 — fine as-is for a single test). |

### Twilio
| Variable | Purpose |
|---|---|
| `TWILIO_AUTH_TOKEN` | The **only** Twilio credential REPLICA's code actually reads for this test — verifies `X-Twilio-Signature` on both the call-status webhook (`POST /webhooks/twilio/call-status`) and the Media Streams WebSocket handshake (`/ws/twilio-media`). Fail-closed: wrong/missing → request rejected. |
| `TWILIO_ACCOUNT_SID` | Not read by any code path this test depends on today (only by the not-yet-used REST client factory / `/api/integrations` status display). Worth setting for completeness; the test does not require it. |
| `TWILIO_REGION` / `TWILIO_EDGE` | Govern REST API calls REPLICA itself makes TO Twilio (not the inbound webhook/media-stream traffic, which has no region concept). REPLICA makes no such calls yet, so these aren't exercised by this test either — already default to `ie1`/`dublin` in code (ADR-049). |
| *(Twilio phone number)* | **Not an environment variable at all** — REPLICA's backend never reads it. It only matters for how you configure the number in the Twilio Console (§4 below). |

### Deepgram
| Variable | Purpose |
|---|---|
| `REPLICA_ASR_PROVIDER` | Set to `deepgram` — switches the streaming ASR seam (`app/streaming/asr.get_asr_provider()`) from `SimulatedASRProvider` to the real `DeepgramASRProvider`. |
| `DEEPGRAM_API_KEY` | Deepgram API key, sent as `Authorization: Token <key>` on the ASR WebSocket connection. |
| `DEEPGRAM_REGION` | `eu` selects `api.eu.deepgram.com` (EU data residency) over the global endpoint — already the default. |
| `DEEPGRAM_MODEL` / `DEEPGRAM_LANGUAGE` | Already default to `nova-3` / `de` — only set explicitly if overriding. |

### Not needed for this test
`OPENAI_API_KEY`, `HUBSPOT_ACCESS_TOKEN`, `GOOGLE_CALENDAR_ACCESS_TOKEN`, `GOOGLE_CALENDAR_ID`, `SALESFORCE_INSTANCE_URL`, `SALESFORCE_ACCESS_TOKEN` — unrelated integrations, leave unset.

## 2. Public URLs Twilio needs configured

| Purpose | URL | Where it's configured |
|---|---|---|
| Media Stream WebSocket | `wss://<PUBLIC_HOST>/ws/twilio-media` (**no query parameters**) | Embedded literally inside the TwiML you configure (§4) — not a separate Twilio dashboard field. |
| Status Callback | `https://<PUBLIC_HOST>/webhooks/twilio/call-status` (HTTP POST) | Embedded directly in the TwiML Bin (§4), as `<Number statusCallback="...">` — kept inside the Bin so the whole Bin is the single place to fill in, per the explicit "only 4 fields" simplification. |
| Call/Voice webhook ("A call comes in") | **No REPLICA URL** — see finding below | Phone Number → Voice Configuration → "A call comes in" → a **TwiML Bin**, not a webhook URL. |

**Finding, stated plainly:** REPLICA's backend does not currently serve any
TwiML-generating endpoint (no `/webhooks/twilio/voice` or similar exists in
`app/main.py`). Building one would be a new backend feature, out of scope
right now per the explicit instruction not to add architecture/product work.
For this first test, use a static Twilio **TwiML Bin** instead (Twilio hosts
the TwiML content itself — REPLICA's server is never contacted for it) — exact
content given in §4.

**Confirmed (code-verified, not a guess): `call_id` travels exclusively via
`<Stream><Parameter name="replica_call_id" value="..."/></Stream>`, delivered
to REPLICA inside the WebSocket `start` event's `customParameters`
(`app/main.py`'s `_resolve_call_for_media_stream()`), never via a query string
on the `<Stream url="...">` itself.** `app/streaming/media_stream_security.
verify_media_stream_signature()` builds the URL it validates the Twilio
signature against from `websocket.url.path` plus `websocket.url.query` — with
no query string in the configured `<Stream url="...">`, that query component
is empty, exactly matching what Twilio itself signs for a query-param-free
URL. Adding a query string to the `<Stream>` URL would still technically work
(the signature check would validate against it), but is unnecessary and not
what the TwiML template below does.

**Status-callback correlation limitation, found while preparing this:**
`Call.external_call_id` (the field the call-status webhook and `<Stream>`'s
`callSid` fallback correlate against) is never written anywhere in the current
codebase — only read. For this first test, status-callback events will
therefore arrive, be signature-verified, deduplicated, and recorded in
`CallProviderStatus`, but with `call_id=None` (uncorrelated to your specific
`Call` row) — this does not block or affect the actual pipeline test in any
way (the Media Stream correlates independently via the `Parameter` above), it
just means you won't see status events tied to a specific call in
`GET /api/audit/export`. Not a feature to add before this test.

**Child-leg correlation, corrected (ADR-054):** the TwiML below attaches
`statusCallback`/`statusCallbackMethod`/`statusCallbackEvent` to `<Number>`,
not `<Dial>` — this is Twilio's documented pattern for a PSTN child call. That
means the webhook fires for the DIALED-OUT (Prospect) leg specifically, with
`CallSid` = that child leg's own SID and `ParentCallSid` = the original Parent
call's SID (the Seller's call, i.e. the one the Media Stream runs on). The
call-status webhook (`app/main.py`'s `twilio_call_status()`) has been
corrected to correlate against `ParentCallSid` when present, falling back to
`CallSid` only when it is not — so once `Call.external_call_id` is eventually
populated with the Parent call's SID (still not done in this codebase — the
limitation above), this event will correlate correctly. `CallProviderStatus`
itself still tracks ordering by the child leg's own `CallSid`, since that
leg's status progression (`initiated`/`ringing`/`answered`/`completed`) is
independent of the parent call's own status.

No other provider callback is required for this test: no recording callback
(the pipeline is listen-only, ADR-047), no fallback URL needed for one manual
supervised call.

## 3. Infrastructure for the first public test environment

Simplest robust shape meeting EU/HTTPS/WSS/Postgres/single-instance:

- **One** small VM or PaaS instance, EU region (Frankfurt/Dublin/Amsterdam —
  whichever your provider's EU location is).
- **Reverse proxy / TLS**: a single-binary reverse proxy with automatic HTTPS
  (e.g. Caddy) in front of the container, OR your PaaS's own built-in
  HTTPS/WSS termination if it already provides one — pick whichever avoids
  manual certbot/nginx configuration. WSS rides the same TLS certificate as
  HTTPS; no separate setup.
- **App container**: the existing `Dockerfile` as-is, run as
  `uvicorn app.main:app --host 0.0.0.0 --port 8000`. **Do not** add
  `--workers N>1` and do not run multiple replicas — `LiveSuggestionHub`
  requires exactly one process (`docs/DEPLOYMENT.md`).
- **Database**: a managed PostgreSQL instance in the same EU region, or the
  `docker-compose.yml` `postgres:16-alpine` service co-located on the same VM
  for a single supervised test. Either way, point `REPLICA_DATABASE_URL` at it.
- **Drop `redis`** from `docker-compose.yml` for this test — it is an unused
  placeholder in that file for a possible future multi-instance pub/sub
  backplane (see `app/services/live_push.py`'s own note); nothing in the code
  reads it today.
- **Secrets**: set via your host/PaaS's own secret store, never committed —
  this repo's `.gitignore` already excludes `.env`.

## 4. Dashboard steps

### Twilio (https://console.twilio.com)

1. Öffne https://console.twilio.com und melde dich an.
2. **Trial → Pay-as-you-go upgraden (zwingend vor dem echten Test)**: im Free
   Trial sind sowohl `<Stream>` als auch `<Dial><Number>` blockiert — ohne
   Upgrade läuft der Test gar nicht erst an. Console-Startseite oder
   Account-Menü → "Upgrade" bzw. "Add funds"/"Billing" → Zahlungsmethode
   hinterlegen → Account wird dadurch auf Pay-as-you-go umgestellt.
3. **Account SID / Auth Token**: Öffne die Console-Startseite (oder
   Account → API keys & tokens) → dort stehen "Account SID" und "Auth Token"
   (Auth Token ggf. über "View"/Augen-Symbol sichtbar machen) → in deinen
   Passwort-Manager kopieren, niemals in eine Datei in diesem Repo.
4. **Telefonnummer**: Phone Numbers → Manage → Buy a number (falls noch keine
   vorhanden) → eine Nummer mit aktivierter Voice-Funktion wählen.
5. **TwiML Bin erstellen**: Develop → TwiML Bins → "Create new TwiML Bin" →
   Name z. B. `replica-first-test` → folgenden Inhalt einfügen. **Nur diese
   vier Stellen müssen noch ausgefüllt werden**: die öffentliche REPLICA-WSS-URL
   (`<PUBLIC_HOST>`, zweimal — WebSocket und Status-Callback teilen sich denselben
   Host), die aktuelle REPLICA `call_id` (`<REPLICA_CALL_ID>`, aus Schritt 2 der
   Preflight-Checkliste unten), und die Telefonnummer der einwilligenden
   Prospect-Testperson (`<PROSPECT_TEST_PERSON_NUMBER>`, Format `+49...`):
   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <Response>
       <Start>
           <Stream
               url="wss://<PUBLIC_HOST>/ws/twilio-media"
               track="both_tracks">
               <Parameter
                   name="replica_call_id"
                   value="<REPLICA_CALL_ID>" />
           </Stream>
       </Start>

       <Dial>
           <Number
               statusCallback="https://<PUBLIC_HOST>/webhooks/twilio/call-status"
               statusCallbackMethod="POST"
               statusCallbackEvent="initiated ringing answered completed">
               <PROSPECT_TEST_PERSON_NUMBER>
           </Number>
       </Dial>
   </Response>
   ```
   → Speichern. **Korrektur gegenüber einer früheren Version dieses Dokuments:**
   `statusCallback`/`statusCallbackMethod`/`statusCallbackEvent` gehören laut
   aktueller offizieller Twilio-Dokumentation für einen PSTN-Child-Call an
   `<Number>`, nicht an `<Dial>` — daher oben so korrigiert. Diese Reihenfolge
   (`<Start><Stream>` zuerst, dann `<Dial>`) entspricht weiterhin exakt der
   bestätigten Testtopologie: der Seller ruft diese Nummer an (Parent Call,
   wird zum `inbound`-Track), REPLICA startet den Media Stream, und erst
   danach verbindet Twilio zur Prospect-Testperson (`<Dial><Number>`, wird zum
   `outbound`-Track) — siehe ADR-053. Der Status-Callback beschreibt dabei den
   Child-Call (die angerufene Prospect-Nummer) mit einer eigenen `CallSid` und
   einer `ParentCallSid`, die auf den Parent/Seller-Call zurückverweist — siehe
   ADR-054 zur entsprechend korrigierten Korrelation im
   `/webhooks/twilio/call-status`-Endpoint.
6. **Nummer mit der Bin verknüpfen**: Phone Numbers → Manage → Active Numbers
   → deine Nummer anklicken → Abschnitt "Voice Configuration" → Feld
   "A call comes in" → Dropdown auf "TwiML Bin" stellen → die eben erstellte
   Bin auswählen → Speichern. (Kein separates "Call status changes"-Feld nötig
   — der Status-Callback ist bereits Teil der Bin selbst, siehe oben.)
7. **EU-Region (IE1)** — Hinweis zur Ehrlichkeit: dieser Schritt konnte hier
   nicht an einem echten Twilio-Dashboard verifiziert werden. Ob und wo eine
   explizite "IE1"/EU-Data-Residency-Auswahl im Twilio Console für einen
   Standard-Account sichtbar ist, hängt vom Account-Typ ab (bei manchen
   Konten ein separates/Enterprise-Feature unter Account-Einstellungen oder
   Voice → Settings/Regions). Für den reinen Signalisierungs-/Anrufpfad
   dieses ersten Tests ist keine solche Einstellung zwingend erforderlich;
   `ie1`/`dublin` ist bereits im Code für zukünftige REST-API-Aufrufe fest
   hinterlegt (`app/integrations/twilio_rest.py`). Falls deine
   Account-Einstellungen eine Regions-/Data-Residency-Sektion zeigen, wähle
   dort EU, ansonsten beim Twilio-Support nachfragen.

### Deepgram (https://console.deepgram.com)

1. Öffne https://console.deepgram.com und melde dich an.
2. **API Key erzeugen**: linkes Menü "API Keys" → "Create a New API Key" →
   Name z. B. `replica-first-test` → Standardrolle übernehmen → Erzeugen →
   den Key sofort sicher speichern (wird meist nur einmal angezeigt).
3. **EU-Endpoint**: kein separates Dashboard-Toggle nötig — REPLICA verwendet
   automatisch `api.eu.deepgram.com`, weil `DEEPGRAM_REGION=eu` bereits der
   Code-Default ist (`app/streaming/deepgram_provider.py`). Nur prüfen, ob dein
   Deepgram-Projekt selbst in der EU liegt, falls die Konsole eine
   Projekt-Region anzeigt.
4. `mip_opt_out=true` ist bereits fest im Code gesetzt — keine Dashboard-Aktion
   nötig.

## 5. Preflight checklist (existing API, no new code)

Once infra + credentials are in place, before dialing:

1. **Login** (`POST /api/auth/login`) with the demo seller (if
   `REPLICA_DEMO_MODE=true`) → get a bearer token.
2. **Create the call** (`POST /api/calls`) → note the returned numeric `id` —
   this is `<REPLICA_CALL_ID>` for the TwiML Bin above.
3. **Grant consent** (`POST /api/calls/{id}/consent`, `{"state":"granted"}`) —
   **mandatory**: without it, `can_process()` denies `transcribe`/`live_assist`
   and the whole pipeline silently produces nothing, even though the phone
   call itself connects fine.
4. Optionally confirm (`GET /api/calls/{id}/processing-permissions`) that both
   `transcribe` and `live_assist` show `ALLOWED` for this call/jurisdiction
   before dialing.
5. **Open the live UI**: `https://<PUBLIC_HOST>/live/{id}` in the seller's
   browser, paste a fresh bearer token, click "Verbinden" — do this BEFORE
   placing the call, so the push connection is already live.
6. **Place the call**: the Seller (Haydar) dials the Twilio number — **not**
   the other way around. This is the confirmed topology for this test; do not
   have the Prospect test person call in.

**Speaker-role honesty note** (corrected by ADR-053, superseding ADR-043's
original assumption): with the TwiML above, the person who **calls the
number** — the Seller — becomes the `inbound` track (mapped to `seller` by
`OutboundSalesFlowResolver`, `outbound_sales_flow_v2`), and the person
**`<Dial>`-ed out to** — the consenting Prospect test person — becomes
`outbound` (mapped to `prospect`). This mapping matches the concrete topology
confirmed for this test (Seller calls in, TwiML `<Dial>`s the Prospect out),
but has still never been verified against a live Twilio account — only
against documented Twilio semantics and the unit tests in
`tests/test_streaming_speaker_mapping.py`. After the test call, check
`GET /api/calls/{id}/review` (existing endpoint, no new code) to confirm which
`Turn.speaker` values actually match who said what — if inverted, that is real
field data for a further topology correction, not something to guess-fix in
advance.

## 6. What this test proves

Twilio IE1 → real phone call → real Media Stream → Deepgram EU → real interim
transcript → real final transcript → Turn Detection → Conversation State →
SalesBrain → Live Suggestion → browser push → browser render → Render-ACK →
real latency measurement (`wallclock_rsl_estimate_ms`, `server_render_ack_latency_ms`,
still labelled `is_synthetic=False`/`asr_provider='deepgram'` once this runs for
real — everything before this remains `is_synthetic=True`). Consenting test
persons only, never a real external prospect. This single test closes both
Sprint 2B (Real Provider Verification) and Sprint 3A (Real-RSL Verification)
at once, per the existing plan.
