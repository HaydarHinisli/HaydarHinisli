# Developer API Examples

## Start call

```bash
curl -X POST http://127.0.0.1:8000/api/calls \
  -H 'Content-Type: application/json' \
  -d '{"seller_id":1,"prospect_company":"Acme","prospect_role":"CFO","segment":"B2B SaaS"}'
```

## Grant analysis consent

```bash
curl -X POST http://127.0.0.1:8000/api/calls/55/consent \
  -H 'Content-Type: application/json' \
  -d '{"state":"granted"}'
```

## Store Prospect turn

```bash
curl -X POST http://127.0.0.1:8000/api/calls/55/turns \
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

## Get live suggestion

```bash
curl -X POST http://127.0.0.1:8000/api/copilot/suggest \
  -H 'Content-Type: application/json' \
  -d '{"call_id":55,"utterance":"Wir haben bereits einen Anbieter."}'
```

## Rate suggestion

```bash
curl -X POST http://127.0.0.1:8000/api/suggestions/1/feedback \
  -H 'Content-Type: application/json' \
  -d '{"rating":"good","used":true}'
```
