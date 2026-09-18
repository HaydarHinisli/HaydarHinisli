# REPLICA Integrations

## Twilio Media Streams

Goal: receive real-time call audio on a server-side WebSocket.

Implemented in Sprint 2 (`app/streaming/`, `POST /ws/twilio-media` in
`app/main.py` — see `docs/DECISIONS.md` ADR-037..042):
1. ~~create/bridge the actual outbound or inbound call flow~~ — still requires a
   real Twilio phone number / TwiML `<Stream>` configuration; not itself REPLICA code.
2. ~~start Media Stream for the desired tracks~~ — REPLICA expects `tracks="both_tracks"`
   (`inbound`/`outbound`); provider-side TwiML configuration, not REPLICA code.
3. **verify Twilio request/signature** — done, `app/streaming/media_stream_security.py`,
   same official `RequestValidator` as the HTTP webhook (ADR-036/037). Documented
   assumption about WS handshake signing (no live Twilio account to confirm against
   from this environment) flagged explicitly in ADR-037 — confirm before pilot go-live.
4. **decode μ-law payload** — done, `app/streaming/mulaw.py` (own implementation,
   not the deprecated stdlib `audioop`; byte-exact verified against it in tests).
5. **split/label channels** — done, `app/streaming/media_stream_session.py` keeps
   `inbound` (prospect) and `outbound` (seller/agent) completely separate end to end.
6. **forward stream to ASR and audio feature extractor** — done for the seam and
   the audio-feature (VAD) side (`app/streaming/vad.py`); the ASR side has no live
   vendor wired in — `app/streaming/asr.py`'s `SimulatedASRProvider` is the one
   implementation of the `ASRProvider` seam today (ADR-042), honestly labelled as
   non-functional transcription, ready for a real vendor to drop in.
7. **record Twilio call SID as `external_call_id`** — done indirectly: the stream is
   *correlated* to a `Call` via `external_call_id` (or `customParameters.replica_call_id`,
   preferred when set) rather than written by the stream itself, matching how the
   call-status webhook already does this correlation (ADR-029).

Heavy AI work still does not run synchronously in the media handler: ASR/VAD/turn
detection are lightweight per-chunk operations, and the one DB-touching,
potentially-heavier step (`process_final_turn()`) runs only once per detected final
turn, on its own short-lived DB session — never inside the tight per-chunk receive
loop for anything other than that.

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
