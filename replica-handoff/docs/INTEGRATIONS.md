# REPLICA Integrations

## Twilio Media Streams

Goal: receive real-time call audio on a server-side WebSocket.

Implemented in Sprint 2/2B (`app/streaming/`, `POST /ws/twilio-media` in
`app/main.py` — see `docs/DECISIONS.md` ADR-037..047):
1. ~~create/bridge the actual outbound or inbound call flow~~ — still requires a
   real Twilio phone number / TwiML `<Stream>` configuration; not itself REPLICA code.
2. **start Media Stream for the desired tracks — required TwiML (Sprint 2B, ADR-047)**:
   ```xml
   <Response>
     <Start>
       <Stream url="wss://<your-public-host>/ws/twilio-media" track="both_tracks">
         <Parameter name="replica_call_id" value="<REPLICA's own Call.id>" />
       </Stream>
     </Start>
     <!-- ... continue with <Dial> to bridge the seller, etc. ... -->
   </Response>
   ```
   Must be `<Start><Stream>` — a parallel, listen-only side-channel while the call's
   own audio path continues normally — **never** `<Connect><Stream>`, which replaces
   the call's own bidirectional media path and is for voice agents that need to send
   audio back into the call. REPLICA's current assist MVP only listens; see ADR-047
   for the full unidirectional-mode rationale and the code-level guarantee it enforces.
3. **verify Twilio request/signature** — done, `app/streaming/media_stream_security.py`,
   same official `RequestValidator` as the HTTP webhook (ADR-036/037). Documented
   assumption about WS handshake signing (no live Twilio account to confirm against
   from this environment) flagged explicitly in ADR-037 — confirm before pilot go-live.
4. **decode μ-law payload** — done, `app/streaming/mulaw.py` (own implementation,
   not the deprecated stdlib `audioop`; byte-exact verified against it in tests).
5. **split/label channels** — done, `app/streaming/media_stream_session.py` keeps
   `inbound`/`outbound` completely separate end to end; which track is `prospect` vs.
   `seller` is resolved via `app/streaming/speaker_mapping.py` (Sprint 2B, ADR-043;
   mapping direction corrected by ADR-053 for the confirmed first-real-test
   topology), NOT a hardcoded assumption — see those ADRs for the explicit
   outbound-sales-flow topology restriction this resolver is scoped to.
6. **forward stream to ASR and audio feature extractor** — done for the seam, the
   audio-feature (VAD) side (`app/streaming/vad.py`), and now a real vendor adapter:
   `app/streaming/deepgram_provider.py`'s `DeepgramASRProvider` (Sprint 2B, ADR-045),
   selected via `REPLICA_ASR_PROVIDER=deepgram` + `DEEPGRAM_API_KEY`. **Not yet
   verified against a live Deepgram account** — implemented per documented protocol
   and tested against a local protocol-faithful fake server only; see ADR-045 and
   the Sprint 2B report for exactly what real-provider verification still requires.
   `SimulatedASRProvider` remains the default and the one implementation actually
   exercised end-to-end so far.
7. **record Twilio call SID as `external_call_id`** — done indirectly: the stream is
   *correlated* to a `Call` via `external_call_id` (or `customParameters.replica_call_id`,
   preferred when set) rather than written by the stream itself, matching how the
   call-status webhook already does this correlation (ADR-029).
8. **EU region/edge (Sprint 3A, ADR-049)** — `TWILIO_REGION`/`TWILIO_EDGE` (default
   `ie1`/`dublin`) govern any REST API call REPLICA makes TO Twilio (not the inbound
   webhook/Media Streams traffic above, which targets `REPLICA_PUBLIC_BASE_URL` and
   has no region concept). No such REST call exists in the codebase yet — this
   prepares `app/integrations/twilio_rest.get_twilio_rest_client()` as the single
   seam for when one is added, refusing to build a client (rather than silently
   inheriting the SDK's own `us1` default) unless both are explicitly configured.

Heavy AI work still does not run synchronously in the media handler: ASR/VAD/turn
detection are lightweight per-chunk operations, and the one DB-touching,
potentially-heavier step (`process_final_turn()`) runs only once per detected final
turn, on its own short-lived DB session — never inside the tight per-chunk receive
loop for anything other than that.

## Live Suggestion Push (Sprint 3A)

Downstream of the Twilio Media Streams pipeline above: every Suggestion
`process_final_turn()` persists is handed to `app/services/live_push.
LiveSuggestionHub`, which pushes it to the seller's browser over
`/ws/live/{call_id}` (`docs/DECISIONS.md` ADR-048, `docs/API_SPEC.md`). This is
REPLICA's own WebSocket to REPLICA's own browser client — not a third-party
provider integration — included here because it is the other real-time transport
in the system, immediately after the Twilio one. In-process/single-instance only
today (see ADR-048's known-limitation note); a multi-instance deployment would
need a shared pub/sub backplane in front of the same publish/register interface.
**See `docs/DEPLOYMENT.md`** for the exact deployment-topology requirement this
implies for the pilot (single instance, or call_id-sticky routing) — read it
before deploying behind a load balancer or with multiple worker processes.

## OpenAI Realtime / other speech foundation provider

Use as a replaceable provider layer.
- API key remains server-side
- use server-side WebSocket for server-managed audio
- associate a stable safety/user identifier
- do not couple REPLICA business logic to one provider event schema

REPLICA should convert provider events into internal events:
- `transcript.interim`
- `transcript.final`
- `turn.started`
- `turn.ended`
- `audio.metric`

## HubSpot

MVP adapter reads:
- CRM v3 meeting objects
- CRM v3 deals

Production:
- OAuth app
- tenant-specific token storage
- webhook subscriptions where possible
- map call/contact/company/deal IDs
- idempotent sync

## Salesforce

MVP contains a generic REST query adapter.
Production:
- OAuth
- Opportunity mapping
- Task/Event mapping
- optional custom fields linking external call ID / REPLICA call ID

## Google Calendar

Use Events resource to determine:
- scheduled meeting
- attendees
- start/end

Calendar event alone does not prove a meeting was held. Prefer meeting provider attendance or CRM disposition if available.

## Microsoft / Teams

Not implemented in code yet, but production should add:
- Microsoft Graph calendar events
- Teams meeting metadata/attendance only where permitted and needed

## Adapter contract

Every provider integration should expose:
- `status()`
- `sync_*()` / webhook handler
- normalized internal payload
- external ID
- observed timestamp
- source provider
