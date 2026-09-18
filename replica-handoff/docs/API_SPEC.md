# REPLICA API Contract

FastAPI exposes Swagger automatically at `/docs`.

## Calls

### `POST /api/calls`
Create a call shell.

### `POST /api/calls/{call_id}/consent`
Body:
```json
{"state":"granted"}
```
Valid states: `granted`, `declined`, `withdrawn`.

### `POST /api/calls/{call_id}/turns`
Stores a measured/transcribed turn. Analysis is blocked unless consent is `granted`.

### `POST /api/calls/{call_id}/complete`
Stores business outcome.

### `GET /api/calls/{call_id}/review`
Returns compact post-call coaching.

### `GET /api/calls/{call_id}/reaction`
Returns baseline + relative reaction deltas for Prospect turns.

## Copilot

### `POST /api/copilot/suggest`
Input:
```json
{
  "call_id": null,
  "utterance": "Wir haben bereits einen Anbieter.",
  "recent_context": [],
  "reaction_snapshot": {}
}
```
Output includes:
- suggestion
- strategy
- do_not
- reason
- confidence
- language_policy
- latency_ms
- evidence_level

### `POST /api/suggestions/{id}/feedback`
```json
{"rating":"good","used":true}
```

## Manager

### `GET /api/manager/overview`
Returns seller context with tenure/product tenure and trend. This endpoint must stay decision-support only.

## Integrations

- `GET /api/integrations`
- `POST /api/integrations/hubspot/sync`
- `POST /api/integrations/google-calendar/sync`
- `GET /api/integrations/openai-realtime/blueprint`

## Experiments

### `POST /api/experiments`
Creates an experiment.

### `POST /api/experiments/{experiment_id}/assign/{call_id}`
Deterministically assigns a call to a variant.

## Streaming

### `WS /ws/twilio-media`
Accepts Twilio Media Stream JSON events. The current MVP counts/validates stream metadata only. The production version routes payloads into ASR/audio-feature workers.
