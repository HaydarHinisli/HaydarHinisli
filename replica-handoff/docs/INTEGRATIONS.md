# REPLICA Integrations

## Twilio Media Streams

Goal: receive real-time call audio on a server-side WebSocket.

Production tasks:
1. create/bridge the actual outbound or inbound call flow
2. start Media Stream for the desired tracks
3. verify Twilio request/signature
4. decode μ-law payload
5. split/label channels where possible
6. forward stream to ASR and audio feature extractor
7. record Twilio call SID as `external_call_id`

Do not let the media handler perform heavy AI work synchronously.

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
