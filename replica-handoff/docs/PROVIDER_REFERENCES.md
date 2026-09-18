# Provider References — checked 2026-09-18

Use these official docs as the implementation reference; provider APIs can change.

## Twilio Media Streams
- https://www.twilio.com/docs/voice/media-streams
- https://www.twilio.com/docs/voice/media-streams/websocket-messages

Important current facts:
- Media Streams send JSON WebSocket messages such as `connected`, `start`, `media`, `stop`.
- Audio payload arrives base64-encoded inside media events.
- Region support should be chosen deliberately for an EU pilot.

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
