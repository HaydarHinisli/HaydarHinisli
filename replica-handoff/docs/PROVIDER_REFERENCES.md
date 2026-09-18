# Provider References — checked 2026-09-18

Use these official docs as the implementation reference; provider APIs can change.

## Twilio Media Streams
- https://www.twilio.com/docs/voice/media-streams
- https://www.twilio.com/docs/voice/media-streams/websocket-messages

Important current facts:
- Media Streams send JSON WebSocket messages such as `connected`, `start`, `media`, `stop`.
- Audio payload arrives base64-encoded inside media events.
- Region support should be chosen deliberately for an EU pilot.
- `media.chunk`/`media.timestamp`/`sequenceNumber` are documented as arriving as
  JSON strings, not numbers — parsed defensively (`app/streaming/media_stream_session.py`).

**Unverified assumption, flagged for pilot go-live** (Sprint 2, `docs/DECISIONS.md`
ADR-037): this environment has no live Twilio account to confirm current wire
behavior against, so the following is implemented per the best available
documentation but MUST be confirmed against a real Media Streams connection before
going live: the WebSocket handshake request is signed with `X-Twilio-Signature` the
same way as an HTTP webhook, validated against the request URL and its query-string
parameters (empty dict, since there is no POST body).

## Deepgram Streaming ASR (Sprint 2B)
- https://developers.deepgram.com/docs/getting-started-with-live-streaming-audio
- https://developers.deepgram.com/reference/speech-to-text-api/listen-streaming
- https://developers.deepgram.com/docs/model-nova-3

Important assumed facts (`app/streaming/deepgram_provider.py`, `docs/DECISIONS.md`
ADR-045) — **unverified against a live Deepgram account from this environment,
confirm before real-provider use**:
- WebSocket endpoint `wss://api.deepgram.com/v1/listen` (global) or
  `wss://api.eu.deepgram.com/v1/listen` (EU region, used here per the explicit
  requirement for EU data residency).
- Auth via `Authorization: Token <API_KEY>` header on the handshake.
- Query params used: `model=nova-3`, `language=de`, `interim_results=true`,
  `mip_opt_out=true` (opts out of Deepgram's model-improvement program, per the
  explicit requirement), `encoding=mulaw&sample_rate=8000&channels=1` (Twilio's
  default media format).
- Audio sent as raw binary WebSocket frames (not JSON) after connecting.
- Results arrive as JSON `{"type": "Results", "is_final": bool, "speech_final":
  bool, "channel": {"alternatives": [{"transcript": str, "words": [...]}]}}`
  messages; word-level timestamps are included in `words` when available, no extra
  flag required.
- `{"type": "Finalize"}` (sent as text) prompts Deepgram to flush its buffer
  immediately without closing the connection — used here to implement OUR
  VAD-driven `finalize()`, not Deepgram's own endpointing.
- `{"type": "CloseStream"}` (sent as text) requests a graceful close.
- Keyterm prompting: a repeatable `keyterm=<term>` query parameter, supported on
  Nova-3 — wired as a constructor parameter (`keyterms`), not populated yet.
- Deepgram Flux (model-integrated turn detection) is explicitly NOT used as the
  primary provider path yet, per the decision to keep our own VAD as the turn-end
  authority for now — noted as a later benchmark candidate, not implemented.
- **Audio path checked (Sprint 3A, docs/DECISIONS.md ADR-050)**: raw Twilio
  mu-law bytes are sent to Deepgram completely unmodified — no transcoding. Our
  own VAD separately decodes the SAME bytes to PCM locally, purely to compute
  signal energy; this never touches what is sent to Deepgram. No code change was
  needed — the pipeline already matched the efficient shape.

## OpenAI Realtime / Voice WebSockets
- https://developers.openai.com/api/docs/guides/realtime
- https://developers.openai.com/api/docs/guides/voice-websockets
- https://developers.openai.com/api/docs/guides/websocket-mode

Implementation principle:
- server-side managed audio should use a trusted server connection
- keep the project API key server-side
- do not bind REPLICA domain events directly to one vendor event schema

## HubSpot CRM
- https://developers.hubspot.com/docs/api-reference/crm-meetings-v3/guide
- https://developers.hubspot.com/docs/api-reference/crm-deals-v3/guide

MVP adapter uses CRM v3 objects for meetings/deals. Production should use OAuth and webhooks/sync cursors.

## Google Calendar
- https://developers.google.com/workspace/calendar/api/guides/overview
- https://developers.google.com/workspace/calendar/api/v3/reference/events

Calendar event presence does not automatically prove attendance. Where possible use CRM disposition or meeting attendance metadata.

## Salesforce REST API
- https://developer.salesforce.com/docs/platform/api-rest/guide/intro-what-is-rest-api.html

Production integration should map Opportunity plus Task/Event or company-specific activity objects.
