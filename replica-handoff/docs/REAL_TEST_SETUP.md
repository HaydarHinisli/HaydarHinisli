# Real Provider Setup & First Live Call — Operator Checklist

Purpose: everything needed to run REPLICA's first real end-to-end test call
(Twilio IE1 → real phone call → real Media Stream → Deepgram EU → real
transcript → Turn Detection → SalesBrain → Live Suggestion → browser push →
Render-ACK → real latency measurement), against real provider accounts, with
consenting test persons only. Through ADR-058/059, no new code was required —
everything used endpoints and mechanisms already built and tested (Sprints
2/2B/3A, Fix-Sprint, ADR-052). **ADR-060 changed that for the browser-based
call path (§4b)**: placing the outbound call from the seller's own browser
(Twilio Voice JS SDK) instead of a purchased number or a REST script needs a
short-lived Access Token and a TwiML response Twilio can only get from
REPLICA's own server at call time — two small, tested endpoints
(`POST /api/voice/access-token`, `POST /webhooks/twilio/voice-outbound`) were
added specifically for this. §4a's REST path remains fully code-free, as
before.

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
| `TWILIO_AUTH_TOKEN` | Verifies `X-Twilio-Signature` on the call-status webhook, the NEW voice-outbound webhook (`POST /webhooks/twilio/voice-outbound`, ADR-060), and the Media Streams WebSocket handshake (`/ws/twilio-media`). Fail-closed: wrong/missing → request rejected. |
| `TWILIO_ACCOUNT_SID` | **Correction (ADR-058):** required for real this time, not just "for completeness" — both the REST call-placement path (§4a) and the browser-based path's Access Token minting (§4b, ADR-060) need it. |
| `TWILIO_REGION` / `TWILIO_EDGE` | Exercised by `get_twilio_rest_client()` for §4a's REST call placement (ADR-058). **Correction (ADR-061):** also required for §4b's browser path — `create_voice_access_token()` sets the Access Token's `twr` (region) JWT header from `TWILIO_REGION`, and the response's `edge` field is passed to the Voice SDK's `Device` constructor as `TWILIO_EDGE`; both now fail closed (500) if either is unset, matching `get_twilio_rest_client()`'s posture exactly. Already default to `ie1`/`dublin` in code (ADR-049); only set explicitly if overriding. |
| `TWILIO_API_KEY_SID` / `TWILIO_API_KEY_SECRET` | **New (ADR-060), only needed for the browser-based test path (§4b).** A Twilio API Key (not the Account Auth Token — kept deliberately separate, see the code comment in `app/integrations/twilio_rest.py`) used to sign the short-lived Access Token the seller's browser needs to register a Voice SDK `Device`. Created once in the Console (§4b step 1). |
| `TWILIO_TWIML_APP_SID` | **New (ADR-060), only needed for §4b.** The TwiML Application the browser's `device.connect()` call is routed through — created once in the Console (§4b step 2), its Voice Request URL points at `POST /webhooks/twilio/voice-outbound`. |
| `TWILIO_VERIFIED_CALLER_ID` | **New (ADR-060), only needed for §4b.** The operator's own already-Verified Caller ID, used server-side (never sent by the browser) as `<Dial callerId="...">` so the Prospect sees a real, verified number and the browser client can never spoof an arbitrary caller ID. |
| *(Twilio phone number)* | **Still not purchased and still not an environment variable** — both real-test paths (§4a REST, §4b browser) deliberately run without one, using a Verified Caller ID instead. |

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
| Call/Voice webhook ("A call comes in") | **No REPLICA URL for the REST path (§4a)** — see finding below. **For the browser path (§4b, ADR-060): `https://<PUBLIC_HOST>/webhooks/twilio/voice-outbound` (HTTP POST)** | §4a: Phone Number → Voice Configuration → "A call comes in" → a **TwiML Bin**. §4b: TwiML Application → **Voice Configuration → "A call comes in" → Webhook**, this exact URL. |

**Finding, stated plainly (still true for §4a's REST path, superseded for §4b
by ADR-060):** REPLICA's backend originally served no TwiML-generating
endpoint at all (no `/webhooks/twilio/voice` or similar existed in
`app/main.py`) — building one was explicitly out of scope while only a
purchased-number/REST call flow was being prepared. §4a's REST path still
uses a static Twilio **TwiML Bin** instead (Twilio hosts the TwiML itself —
REPLICA's server is never contacted for it), exact content given in §4.
**This changed with ADR-060**: the browser-based path (§4b) needs the
Prospect's number at connect-time, which a static Bin cannot embed — so
`POST /webhooks/twilio/voice-outbound` now exists specifically for that path,
built the same way and with the same signature-verification posture as the
existing `POST /webhooks/twilio/call-status` webhook (see `app/main.py`).

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

**Validated alternative for a single supervised test (no deployment at all):**
a local server (`./run.sh`) exposed via a `cloudflared tunnel --url http://localhost:8000`
quick tunnel (no Cloudflare account needed) gives Twilio a real public
`https://*.trycloudflare.com` URL that forwards straight to the developer's own
machine — no server to provision, no DNS, no TLS setup. Confirmed working
end-to-end for `/api/health` over the tunnel. Trade-offs, stated plainly: the
URL is random and changes every time the tunnel restarts (the TwiML Bin and
`REPLICA_PUBLIC_BASE_URL` must be updated together whenever that happens), and
the tunnel process itself must stay running in its own terminal for the
duration of the test. Fine for one supervised session; not a substitute for
the real deployment above for anything beyond that.

## 4. Dashboard steps

### Twilio (https://console.twilio.com)

1. Öffne https://console.twilio.com und melde dich an.
2. **Trial → Pay-as-you-go upgraden (zwingend vor dem echten Test)**: im Free
   Trial sind sowohl `<Stream>` (in eigenem/Custom-TwiML — die eingebaute
   "Try out Voice"-Demo läuft über eine Twilio-eigene Demo-Nummer und ist davon
   unabhängig) als auch `<Dial><Number>` blockiert — ohne Upgrade läuft der
   Test gar nicht erst an. Console-Startseite oder Account-Menü → "Upgrade"
   bzw. "Add funds"/"Billing" → Zahlungsmethode hinterlegen → Account wird
   dadurch auf Pay-as-you-go umgestellt.

   **Zusätzlich gefunden, real am Account geprüft (19.09.2026):** das Upgrade
   ist nicht nur für `<Stream>`/`<Dial>` selbst nötig, sondern auch jede
   *eigene* Telefonnummer erfordert es — unabhängig vom Land. EU-Nummern
   (Deutschland, Irland) verlangen zusätzlich ein "Regulatory Bundle"
   (Compliance-Nachweis mit Adress-/Identitätsangaben), selbst für den
   "Individual"-Profiltyp; eine **US-Nummer mit ausschließlich Voice-Fähigkeit
   (SMS/MMS bei der Suche abgewählt)** verlangt dieses Bundle dagegen nicht.
   Der Upgrade-Vorgang selbst (Zahlungsmethode + Compliance-Profil anlegen)
   brach bei diesem Test wiederholt mit Navigations-Schleifen bzw. internen
   Serverfehlern auf Twilio-Seite ab — vermutlich eine automatische
   Risikoprüfung für neue Accounts, kein Bedienfehler; einfach nach einiger
   Zeit erneut versuchen, oder Twilio-Support kontaktieren, falls es anhält.
3. **Account SID / Auth Token**: Öffne die Console-Startseite (oder
   Account → API keys & tokens) → dort stehen "Account SID" und "Auth Token"
   (Auth Token ggf. über "View"/Augen-Symbol sichtbar machen) → in deinen
   Passwort-Manager kopieren, niemals in eine Datei in diesem Repo.
4. **Telefonnummer — OPTIONAL, per ADR-058 bewusst übersprungen für den ersten
   Test**: Phone Numbers → Manage → Buy a number, falls du doch eine kaufen
   willst. Mit einer erfolgreich hinterlegten **Verified Caller ID** (Voice →
   Caller IDs → Verify a number) ist keine gekaufte Nummer nötig — §4a unten
   beschreibt den Testablauf ganz ohne eine.
5. **TwiML Bin erstellen**: Develop → TwiML Bins → "Create new TwiML Bin".

   **Zwischenschritt, empfohlen bevor eine zweite Testperson feststeht — Solo-
   Verifikation ohne `<Dial>`:** prüft Media Stream, Signaturprüfung und
   echte Deepgram-Erkennung, ohne dass ein Prospect-Gegenüber nötig ist (es
   entsteht dabei bewusst keine Suggestion, da nur Prospect-Turns eine
   auslösen — siehe ADR-053). Nur `<PUBLIC_HOST>` und `<REPLICA_CALL_ID>`
   ausfüllen:
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
       <Say language="de-DE">Verbindung zu REPLICA hergestellt. Bitte sprechen Sie jetzt.</Say>
       <Pause length="30"/>
   </Response>
   ```

   **Vollständige Variante mit Prospect (sobald eine zweite Person feststeht).**
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
6. **Nummer mit der Bin verknüpfen — nur falls du in Schritt 4 doch eine
   Nummer gekauft hast**: Phone Numbers → Manage → Active Numbers → deine
   Nummer anklicken → Abschnitt "Voice Configuration" → Feld "A call comes
   in" → Dropdown auf "TwiML Bin" stellen → die eben erstellte Bin auswählen
   → Speichern. (Kein separates "Call status changes"-Feld nötig — der
   Status-Callback ist bereits Teil der Bin selbst, siehe oben.) **Ohne
   gekaufte Nummer (der Weg für diesen ersten Test) entfällt dieser Schritt
   komplett** — die Bin wird stattdessen direkt als `url`-Parameter eines
   REST-`calls.create()`-Aufrufs verwendet, siehe §4a.
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

### Placing the call without a purchased number (ADR-058)

Confirmed prerequisites (checked live against the operator's own account):
Pay-as-you-go active, a real balance, a **Verified Caller ID** (not a
purchased number) on the account, and the destination country's **Voice
Geographic Permission** enabled (Low Risk) for every number this test will
touch — both the number the REST call rings AND the number `<Dial>`-ed out
to as the prospect. High Risk is intentionally not enabled; don't dial a
number Twilio classifies High Risk with this account as configured.

**Topology, and why it must be this way round and not the other:** the
already-confirmed, already-tested speaker mapping (ADR-053,
`OutboundSalesFlowResolver`) requires the SELLER to be the party connected on
the PARENT call leg (`inbound` track) and the PROSPECT to be the party
`<Dial>`-ed out afterward (`outbound` track) — a live Suggestion only ever
fires from a `prospect`-labelled turn, so getting this backwards means the
call sounds fine on the phone but silently produces zero suggestions (or
mislabels who-said-what). With no purchased number, "the Seller dials the
Twilio number" (the previous plan's step 6) isn't possible — nobody can call
a number that doesn't exist. The REST-equivalent that preserves the exact
same topology is: **Twilio calls the SELLER via the REST API** (using the
Verified Caller ID as `From`), the Seller answers exactly as if they'd dialed
in, and the SAME already-written TwiML then proceeds unchanged (`<Start>
<Stream>` immediately, then `<Dial><Number>` to the Prospect test person).
The parent leg's connected party is still the Seller either way — only
*how* that leg was established changes (REST-outbound instead of
PSTN-inbound), which the Media Stream's `inbound`/`outbound` labelling does
not depend on (see the clarifying note added to `app/streaming/
speaker_mapping.py`'s docstring). **Do not** instead place the REST call `To`
the Prospect test person with the Seller bridged in separately — that
inverts which party is on the parent leg and is explicitly out of scope for
`OutboundSalesFlowResolver` as written.

**Keeping the Prospect test person's number out of the TwiML Bin entirely
(ADR-059):** step 5's "vollständige Variante mit Prospect" TwiML Bin is
still fine to use if you're comfortable with that number sitting in a named
Twilio Console resource indefinitely. If the test person is someone whose
number you'd rather not leave stored in a third-party dashboard at all (a
family member, a friend doing you a favor — not a company test account),
skip that Bin entirely and use the script below instead: it builds the same
TwiML **inline**, per call, from a number that only ever lives in an
environment variable or a non-echoed prompt on your own machine — never
written to any file, never logged, never committed.

**Steps:**
1. Save the script below as `place_test_call.py` **outside this repository**
   (e.g. your home folder or `/tmp`) — never inside `replica-handoff/`, so it
   can never end up staged or committed by accident.
   ```python
   """One-off operator script (docs/DECISIONS.md ADR-059) — never committed.
   Places the first real test call without a purchased Twilio number and
   without ever writing the Prospect test person's number to a file, a log,
   or a Twilio Console resource. Run with the replica-handoff venv active
   and its repo root on PYTHONPATH (see the command below)."""
   import getpass
   import os
   import re
   from xml.sax.saxutils import escape

   from app.integrations.twilio_rest import get_twilio_rest_client

   # --- fill these in for this run (not personal data about a third party) ---
   SELLER_NUMBER = '+49...'        # your own phone — answers first, plays the seller
   VERIFIED_CALLER_ID = '+49...'   # your Verified Caller ID (may be the same number)
   PUBLIC_HOST = '<PUBLIC_HOST>'   # same host as REPLICA_PUBLIC_BASE_URL, no scheme
   REPLICA_CALL_ID = '<REPLICA_CALL_ID>'  # from preflight step 2 below
   # ---------------------------------------------------------------------------

   def read_prospect_number() -> str:
       # TEST_PROSPECT_NUMBER (env var) or a non-echoed prompt — either way this
       # value is used once, in memory, and never printed, logged, or written
       # to disk anywhere in this script.
       raw = os.environ.get('TEST_PROSPECT_NUMBER') or getpass.getpass(
           'Prospect test person\'s number (E.164, e.g. +49...), not echoed, not logged: '
       )
       raw = raw.strip()
       if not re.fullmatch(r'\+[1-9]\d{6,14}', raw):
           raise SystemExit('Not a valid E.164 number — refusing to place the call.')
       return raw

   prospect_number = read_prospect_number()

   twiml = (
       '<?xml version="1.0" encoding="UTF-8"?>'
       '<Response>'
       '<Start>'
       f'<Stream url="wss://{PUBLIC_HOST}/ws/twilio-media" track="both_tracks">'
       f'<Parameter name="replica_call_id" value="{REPLICA_CALL_ID}" />'
       '</Stream>'
       '</Start>'
       '<Dial>'
       f'<Number statusCallback="https://{PUBLIC_HOST}/webhooks/twilio/call-status" '
       'statusCallbackMethod="POST" '
       f'statusCallbackEvent="initiated ringing answered completed">{escape(prospect_number)}</Number>'
       '</Dial>'
       '</Response>'
   )

   client = get_twilio_rest_client()
   call = client.calls.create(to=SELLER_NUMBER, from_=VERIFIED_CALLER_ID, twiml=twiml)
   print('Call SID:', call.sid)  # deliberately never prints prospect_number or twiml
   ```
2. Fill in `SELLER_NUMBER`, `VERIFIED_CALLER_ID`, `PUBLIC_HOST`,
   `REPLICA_CALL_ID` in the script (these are yours/operational, not the
   third party's data).
3. Complete preflight checklist steps 1–5 below (login, create the call, grant
   consent, confirm permissions, open `/live/{id}` in the browser) — unchanged.
4. Run it, `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`/`TWILIO_REGION`/
   `TWILIO_EDGE` already set in the environment (§1):
   ```bash
   cd /path/to/replica-handoff && source .venv/bin/activate
   TEST_PROSPECT_NUMBER='+49...' python3 /path/to/place_test_call.py
   # or, to be prompted instead (not echoed to the terminal):
   python3 /path/to/place_test_call.py
   ```
   The Seller's phone rings; answering it runs the exact TwiML above —
   `<Start><Stream>` starts the Media Stream immediately, then
   `<Dial><Number>` rings the Prospect test person. `get_twilio_rest_client()`
   (`app/integrations/twilio_rest.py`) is already EU region/edge-configured
   and never constructs a client without `TWILIO_ACCOUNT_SID`/
   `TWILIO_AUTH_TOKEN` set.
5. Clear your shell history of this run if you used the `TEST_PROSPECT_NUMBER=`
   inline form (`history -d <line>` or equivalent) — the non-echoed prompt
   avoids this entirely, which is why it's the safer default when in doubt.

### Browser-based calling from the seller's own MacBook (ADR-060, now the preferred path)

Supersedes §4a's REST call placement for the actual first test, per explicit
request: the operator places the call themselves, live, from the browser
(Twilio Voice JS SDK, `Device.connect()`), rather than a script calling
Twilio's REST API. §4a's underlying topology reasoning (seller must be the
PARENT leg / `inbound` track, Prospect must be the `<Dial>`-ed child leg /
`outbound` track) is unchanged and still applies — only *how* the parent leg
gets established changes again, this time to a WebRTC browser connection.
§4a stays documented as a working alternative (e.g. for a fully unattended/
scripted re-run later); it is not being removed.

**One-time Twilio Console setup (steps 0–2 only ever need doing once per
account, not per call). Step 0 is not optional** — per Twilio's own
documentation ([Managing Regional Resources in
Console](https://www.twilio.com/docs/global-infrastructure/managing-regional-resources-in-console)),
API Keys and TwiML Apps are themselves Region-scoped resources: whichever
Region the Console's Region selector is set to at the moment you click
"Create" is the Region that resource is created in, defaulting to US1 if you
never touch it. Creating either one without switching to IE1 first would
silently produce a US1 API Key / US1 TwiML App — exactly the kind of hidden
non-EU dependency ADR-049/061 exist to prevent, and it would not necessarily
even be usable together with an IE1-region Access Token. This session could
not click through the Console live to confirm the exact current wording
(`www.twilio.com` was blocked by network egress policy here) — the steps
below follow Twilio's own documented procedure; verify the Region indicator
actually reads **IE1** before proceeding with steps 1 and 2, and stop to
re-check if it doesn't match what's described.

0. **Switch the Console's Region selector to IE1**: Console → Develop → API
   keys & creds → **API Keys & auth tokens** → find the **Region** selector
   (a dropdown, shown alongside this page in the current Console) → select
   **IE1**. The page reloads scoped to IE1. (Older/legacy Console layout:
   Account menu, top right → "API keys & tokens" under Keys & Credentials →
   Region dropdown → IE1.)
1. **Create an API Key** (Standard, not Main — deliberately separate from the
   Account Auth Token used for webhook signatures), with the Region selector
   still on IE1 from step 0: click **"Create API key"** → Type: **Standard**
   → name it e.g. `replica-voice-sdk` → copy the **SID** (`SK...`) and the
   **Secret** (shown once) into your password manager, never into this repo.
   These become `TWILIO_API_KEY_SID` / `TWILIO_API_KEY_SECRET`.
2. **Create a TwiML Application**, Region selector still on IE1: Console →
   Voice → TwiML → **TwiML Apps** — confirm the Region indicator on this page
   also reads IE1 (it is tracked per product area, not globally for the
   whole Console session) → "Create new TwiML App" → name it e.g.
   `replica-first-test-browser` → under **Voice Configuration**, set **"A
   call comes in"** to **Webhook**, HTTP **POST**, URL
   `https://<PUBLIC_HOST>/webhooks/twilio/voice-outbound` → Save. Copy the
   **Application SID** (`AP...`) shown at the top — this is
   `TWILIO_TWIML_APP_SID`.
3. Set the four new environment variables from §1
   (`TWILIO_API_KEY_SID`, `TWILIO_API_KEY_SECRET`, `TWILIO_TWIML_APP_SID`,
   `TWILIO_VERIFIED_CALLER_ID` — the last one is your own already-Verified
   Caller ID number) in `.env`, alongside the existing
   `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`/`TWILIO_REGION`/`TWILIO_EDGE`.
   Restart the server after editing `.env` so the new values are picked up.

**Running the actual test call, with as few steps as possible:**

1. Complete preflight checklist steps 1–4 below (login, create the call,
   grant consent, confirm permissions) — unchanged.
2. Open `https://<PUBLIC_HOST>/live/{id}` in Chrome, paste a fresh bearer
   token, click **"Verbinden"** (this is what makes `replica_call_id`
   available to the page — required before the next step will do anything).
3. Open the **Debug-Ansicht** (closed by default, ADR-056) → scroll to
   **"Echter Testcall (Twilio Voice SDK, ADR-060)"**.
4. Type the Prospect test person's number into the field (E.164, e.g.
   `+49...`) — this value is never sent anywhere except this one call, never
   logged, and the field clears itself the instant you click the button.
5. Click **"Testcall starten"**. The browser will ask for microphone
   permission (required by WebRTC/getUserMedia; HTTPS is already a
   prerequisite for this whole setup) — allow it. The page fetches a fresh
   Access Token from `POST /api/voice/access-token`, registers a Voice SDK
   `Device`, and calls `device.connect()` with the number and
   `replica_call_id` as custom parameters.
6. Twilio POSTs those parameters to `/webhooks/twilio/voice-outbound`
   (signature-verified, same posture as the existing call-status webhook),
   which returns the TwiML: `<Start><Stream track="both_tracks">` first (so
   the Media Stream is already running), then `<Dial callerId="<your
   Verified Caller ID>">` to the Prospect's number.
7. The Prospect's normal mobile phone rings, showing your Verified Caller ID
   as the caller. Once they answer, speak as the seller directly into your
   MacBook's microphone — REPLICA processes it through the same pipeline as
   every other real-provider test (Deepgram EU → Turn Detection → Speaker
   Mapping → Conversation State → SalesBrain → Live Suggestion → browser
   render → Render-ACK).

**IE1/Dublin confirmation (ADR-061 — checked and fixed before step 1 above
was ever run for real):** the Access Token minted in step 5 carries `region:
'ie1'` as its JWT `twr` header claim (confirmed by decoding a real
constructed token — `{'twr': 'ie1', ...}`), and the `Device` in step 5 is
constructed with `edge: 'dublin'` read from that same response, never
hardcoded. Both now fail closed (HTTP 500 from `/api/voice/access-token`) if
`TWILIO_REGION`/`TWILIO_EDGE` are ever unset — the browser-calling path can
no longer silently fall back to Twilio's own `roaming`/`us1` defaults, the
exact same guarantee `get_twilio_rest_client()` already had for the REST
path. The voice-test status line shows the active region/edge live
(`"Registriere Device (Region: ie1, Edge: dublin) …"`) so you can see it
during the test, not just trust it. What this does NOT cover: Twilio's own
infrastructure (not REPLICA's code) ultimately decides which region actually
processes a call and its Media Stream — pinning the signaling connection to
IE1/Dublin is the well-founded expectation that the whole call stays in that
region, not an independently observed fact; this test itself IS that
observation.

**Honesty note, stated plainly (mirrors ADR-058's for the REST path):** the
speaker-role mapping for this exact topology (browser parent leg = `inbound`
= seller, `<Dial>`-ed child leg = `outbound` = prospect) has been verified by
re-reading Twilio's Media Streams track semantics and by confirming
`OutboundSalesFlowResolver` makes no assumption anywhere about the parent
leg's connection type (see the clarifying paragraph added to `app/streaming/
speaker_mapping.py`'s docstring, ADR-060) — it has NOT yet been verified
against an actual live call. That verification is what running this test
IS; check `GET /api/calls/{id}/review` afterward to confirm which
`Turn.speaker` values actually match who said what, exactly as ADR-058
already recommended for its own topology.

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

## 5. Preflight checklist

Once infra + credentials are in place, before dialing. Steps 1–5 use only
already-existing API, exactly as before ADR-060; step 6's browser option is
the one part of this checklist that now also depends on the two new
endpoints ADR-060 added (`POST /api/voice/access-token`,
`POST /webhooks/twilio/voice-outbound`).

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
6. **Place the call.** Three equivalent ways to get the Seller onto the
   parent leg — pick the one matching your setup:
   - **With a purchased number**: the Seller (Haydar) dials the Twilio number
     — **not** the other way around, and not the Prospect test person calling
     in either.
   - **Without a purchased number, via REST** (ADR-058, §4a): run the REST
     `calls.create()` command with `to=` the Seller's own phone — Twilio
     calls the Seller, who answers exactly as if they'd dialed in.
   - **Without a purchased number, from the browser** (ADR-060, §4b, the
     path actually used for this test): click **"Testcall starten"** in the
     Debug-Ansicht's new voice-test section on the same `/live/{id}` page
     already opened in step 5 — the Seller's own MacBook microphone becomes
     the parent leg directly, no phone involved on the Seller's side at all.

**Speaker-role honesty note** (corrected by ADR-053, superseding ADR-043's
original assumption): with the TwiML above, the person **connected on the
parent leg** — the Seller, however that leg was established — becomes the
`inbound` track (mapped to `seller` by `OutboundSalesFlowResolver`,
`outbound_sales_flow_v2`), and the person **`<Dial>`-ed out to** — the
consenting Prospect test person — becomes `outbound` (mapped to `prospect`).
This mapping matches the concrete topology confirmed for this test (Seller on
the parent leg, TwiML `<Dial>`s the Prospect out), but has still never been
verified against a live Twilio account — only against documented Twilio
semantics and the unit tests in `tests/test_streaming_speaker_mapping.py`.
After the test call, check `GET /api/calls/{id}/review` (existing endpoint,
no new code) to confirm which `Turn.speaker` values actually match who said
what — if inverted, that is real field data for a further topology
correction, not something to guess-fix in advance.

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

## 7. Status (21.09.2026, ADR-062) — everything code-side is done; only the Console steps below remain

Everything above (§1–6) stays as reference material for *why* each piece
exists. This section is the short, current, actually-followable sequence —
superseding §7's old 19.09 resume-point entirely (that note's own "buy a
number" plan was already abandoned in favor of §4a/§4b; it is not repeated
here).

### A) Already fully ready (code, tests, UI — nothing left to build)

- Browser calling path complete end-to-end (ADR-060/061): Access Token
  minting pinned to `region=ie1` (`twr` JWT claim, verified by decoding a
  real token), `Device` pinned to `edge=dublin`, TwiML generation
  (`Start/Stream` before `Dial`, `both_tracks`, `replica_call_id`,
  `callerId`), all XML-attribute values escaped safely.
- `GET /api/voice/preflight` (ADR-062): one status-only check covering every
  item this test needs — both Twilio credentials, the TwiML App SID, the
  Verified Caller ID, region/edge, Deepgram key, public base URL, and the
  WS-origin allowlist. Never returns a secret value, only booleans/labels
  and the three genuinely non-secret settings (region, edge, base URL).
- `/live/{call_id}`'s voice-test section now calls that preflight
  automatically and renders it as a checklist; **"Testcall starten" fails
  closed** — greyed out / refuses with the missing item's plain-language
  label whenever any required setting is missing, and never calls
  `device.connect()` in that case.
- Prospect-number handling audited end-to-end: the field is read and
  cleared as the very first action of the click handler (before any other
  check), so it never lingers in the DOM on any code path — confirmed by a
  real Playwright run showing the field empty immediately after both a
  successful and a fail-closed click. It is never written to
  `localStorage`/`sessionStorage`, never passed to `console.*`, never
  persisted server-side beyond the one-time TwiML response Twilio consumes
  once, and no error text anywhere embeds it — only config-item labels or
  generic messages. It also never appears in this repo or in `git`
  history — the only source file that ever mentions a real-looking test
  number is `place_test_call.py` from §4a, which is explicitly written to
  live outside the repo (ADR-059) and reads its number from an
  environment variable or a non-echoed prompt, never a literal.
- New end-to-end test (`tests/test_voice_call_flow_e2e.py`, ADR-062) proves
  the entire flow without a real Twilio/Deepgram account or phone: token
  region/edge → webhook TwiML → the same `call_id` driven through the real
  Media Stream pipeline → real Turn Detection/SalesBrain → a real
  `Suggestion` pushed to a real `/ws/live/{id}` client → speaker mapping
  (`outbound` → `prospect`, confirmed via the `Turn` table) → a real
  Render-ACK with a computed `wallclock_rsl_estimate_ms`.
- Full regression confirmed clean after all of the above: **320/320
  passing, run three times consecutively** (up from the pre-existing
  312/312 baseline — the +8 are the new preflight tests). Zero changes to
  any previously-existing behavior; `/live/{call_id}` and the rest of the
  live-copilot UI verified working via real Playwright browser runs, not
  just pytest.

### B) Only remaining before the first real call — Twilio Console, once

Do this only once the Console is reachable again. Full detail (with exact
menu paths) is in §4b steps 0–2 above; short form:

1. Console → switch the **Region selector to IE1** (step 0 — do this
   before either resource below, or they're created in the wrong region).
2. **Create an API Key** (Standard) while still on IE1 → copy its SID and
   Secret.
3. **Create a TwiML Application** while still on IE1 → set its "A call
   comes in" webhook to `POST https://<PUBLIC_HOST>/webhooks/twilio/voice-outbound`
   → copy its Application SID.

Nothing else needs creating in the Console for this test — no phone number
(a Verified Caller ID is used instead, §4), no TwiML Bin (only used by the
alternative REST path, §4a).

### C) Values to enter locally afterward (`.env`, then restart the server)

From step B: `TWILIO_API_KEY_SID`, `TWILIO_API_KEY_SECRET`,
`TWILIO_TWIML_APP_SID`. Already known beforehand:
`TWILIO_VERIFIED_CALLER_ID` (your existing Verified Caller ID),
`TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN` (Console home), `TWILIO_REGION=ie1`/
`TWILIO_EDGE=dublin`, `DEEPGRAM_API_KEY`, `REPLICA_PUBLIC_BASE_URL`,
`REPLICA_ALLOWED_WS_ORIGINS`. Restart the server after editing `.env`, then
open `/live/{id}`'s Debug-Ansicht and confirm the new preflight checklist
shows every item green before doing anything else — it is the fail-closed
gate that guarantees nothing below can silently run half-configured.

### D) Exact start sequence for the first real call

1. Login → create the call → grant consent (preflight checklist steps 1–3,
   §5).
2. Open `https://<PUBLIC_HOST>/live/{id}`, paste a bearer token, click
   **"Verbinden"**.
3. Open the Debug-Ansicht → confirm the preflight checklist is fully green
   (if not, fix whatever it names — it will not let you proceed silently).
4. Type the consenting Prospect test person's number into the field.
5. Click **"Testcall starten"**, allow microphone access.
6. Speak as the seller; the Prospect's phone rings showing your Verified
   Caller ID. Once they answer, the full pipeline runs for real.
7. Afterward: check `GET /api/calls/{id}/review` to confirm speaker
   mapping matched reality, and confirm the resulting `TurnLatencyTrace`
   row shows `is_synthetic=False`, `asr_provider='deepgram'` — this is
   what closes out Sprint 2B/3A's real-provider verification (§6).
