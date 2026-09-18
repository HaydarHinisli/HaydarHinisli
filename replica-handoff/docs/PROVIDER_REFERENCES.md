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
