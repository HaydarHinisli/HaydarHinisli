# Developer API Examples

Every call below except login requires a bearer token (Sprint 1). Get one first:

## Log in

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"haydar@replica-pilot.example","password":"replica-demo-2026"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
```

The demo password only ever works against a `REPLICA_DEMO_MODE=true` seeded tenant
(see `app/seed.py`) — it is not a real credential for any production tenant.

## Start call

```bash
curl -X POST http://127.0.0.1:8000/api/calls \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"seller_id":1,"prospect_company":"Acme","prospect_role":"CFO","segment":"B2B SaaS","prospect_type":"b2b"}'
```

`jurisdiction_country` defaults to the tenant's own `Company.country_code` when
omitted; set it explicitly for a call happening in a different jurisdiction.

## Grant analysis consent

```bash
curl -X POST http://127.0.0.1:8000/api/calls/55/consent \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"state":"granted"}'
```

## Store Prospect turn

```bash
curl -X POST http://127.0.0.1:8000/api/calls/55/turns \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "speaker":"prospect",
    "text":"Wir haben bereits einen Anbieter.",
    "started_ms":12000,
    "ended_ms":14200,
    "words_per_minute":171,
    "response_latency_ms":420,
    "avg_loudness_dbfs":-21.2,
    "avg_pitch_hz":136,
    "pitch_range_hz":49
  }'
```

Returns `403` with a policy decision (`action`, `result`, `reason`, `policy_reference`)
if consent for the `transcription` purpose has not been granted for this call yet.

## Get live suggestion

```bash
curl -X POST http://127.0.0.1:8000/api/copilot/suggest \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"call_id":55,"utterance":"Wir haben bereits einen Anbieter."}'
```

Omit `call_id` for sandbox/practice mode (no policy gate, no real prospect involved).

## Rate suggestion

```bash
curl -X POST http://127.0.0.1:8000/api/suggestions/1/feedback \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"rating":"good","used":true}'
```

## Check what's permitted for a call

```bash
curl http://127.0.0.1:8000/api/calls/55/processing-permissions -H "Authorization: Bearer $TOKEN"
```
