# REPLICA Architecture

## 1. Core idea

REPLICA must not wait for a full sentence and then call a large LLM. The live architecture is split into three paths.

## 2. Live Path

```text
Phone / Softphone
      │
      ▼
Audio Stream
      │
      ├──► Streaming ASR ──► interim transcript
      │                         │
      │                         ▼
      │                  Early Event Classifier
      │                         │
      ├──► Audio Features       │
      │    WPM / pause /        │
      │    overlap / latency    │
      │                         ▼
      │                  Prospect Live State
      │                         │
      ▼                         ▼
Turn Detector ───────────► FAST PATH
                              │
                              ├──► SalesBrain
                              ├──► LanguageSync
                              └──► one short response
                                      │
                                      ▼
                                  Seller UI
```

The Fast Path is allowed to be deterministic / small-model based.

## 3. Smart Path

For complex cases only:

```text
Fast Path result + recent transcript + company playbook
                    │
                    ▼
              Reasoning model
                    │
                    ▼
           refined suggestion
```

Rules:
- Smart Path never blocks initial UI suggestion.
- If Smart Path returns too late, ignore it for the current turn.
- A refined suggestion may replace the Fast Path only before the seller has acted.

## 4. Background Path

Runs asynchronously after/during call:
- detailed transcript
- reaction deltas
- post-call review
- CRM outcome sync
- experiment aggregation
- manager coaching trends
- training/export dataset creation

## 5. Data layers

### Tenant private data
- raw audio if retained
- transcripts
- call turns
- seller feedback
- company playbook
- CRM outcomes

### Derived private intelligence
- company-specific patterns
- seller-specific coaching
- offer/segment performance

### Optional network intelligence
Only if separately permitted:
- anonymized/aggregated statistics
- no competitor-accessible raw calls
- no direct cross-tenant transcript lookup

## 6. Provider boundaries

REPLICA owns:
- SalesBrain
- LanguageSync
- Reaction Delta
- Cold Call Genome
- Experiment Engine
- Revenue Reward
- Coaching / Manager layer

Providers may supply:
- telephony
- ASR
- realtime speech model
- TTS
- CRM/calendar transport

## 7. Suggested production stack

Pilot:
- FastAPI
- PostgreSQL
- Redis
- object storage
- WebSocket/SSE UI push

Scale-up:
- event bus / stream (Kafka, Redpanda, NATS, etc.) only when traffic justifies it
- worker queue for post-call jobs
- dedicated feature store only after enough data exists

## 8. Latency instrumentation

Record at minimum:
- `t_audio_received`
- `t_interim_transcript`
- `t_turn_end_detected`
- `t_fast_path_ready`
- `t_suggestion_sent`
- `t_ui_rendered`

Primary metric:

`RSL = t_ui_rendered - t_turn_end_detected`

Also record ASR delay separately so bottlenecks are visible.
