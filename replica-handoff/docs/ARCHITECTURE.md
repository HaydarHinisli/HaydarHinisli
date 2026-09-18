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

Sprint 3A implements the last box ("Seller UI") for real: `app/services/
live_push.LiveSuggestionHub` pushes each persisted Suggestion to the seller's
connected browser client over `/ws/live/{call_id}`, and `app/static/live.html` is
a minimal (non-final) UI proving the mechanism — see `docs/DECISIONS.md` ADR-048
and `docs/API_SPEC.md`. The full REPLICA seller frontend itself remains future work.

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

Implemented in Sprint 2 (`app/services/latency_trace.py`, `TurnLatencyTrace` — see
`docs/DECISIONS.md` ADR-041). The originally-sketched stage names above are refined
to the more granular set actually implemented:

- `t_audio_received`
- `t_asr_interim` (refines `t_interim_transcript`)
- `t_asr_final` (new — separates ASR's own final-transcript signal from turn detection)
- `t_turn_end_detected`
- `t_provider_endpoint_detected` (Sprint 2B — the ASR provider's OWN endpointing
  signal, e.g. Deepgram's `speech_final`, captured for comparison only; our own VAD
  remains the sole turn-end authority, see `docs/DECISIONS.md` ADR-046)
- `t_salesbrain_started` / `t_salesbrain_finished` (together refine `t_fast_path_ready`)
- `t_suggestion_persisted` (refines `t_suggestion_sent`)
- `t_suggestion_pushed` (Sprint 3A — now actually reached: the moment the persisted
  Suggestion is handed to `app/services/live_push.LiveSuggestionHub`, regardless of
  whether a browser happens to be connected at that instant, see ADR-048)
- `t_browser_received` / `t_ui_rendered` (Sprint 3A — set ONLY by the browser's own
  Render-ACK, `POST /api/suggestions/{id}/render-ack`; never estimated server-side)

Primary metric (unchanged):

`RSL = t_ui_rendered - t_turn_end_detected`

`real_rsl_ms` stays `NULL` until a real Render-ACK sets `t_ui_rendered` — never
approximated. Since Sprint 3A, this is a genuine, computed value whenever a
Render-ACK has fired for that trace — but it is necessarily a WALL-CLOCK delta
(the browser and this server share no monotonic clock), unlike every other `_ms`
column here, which are all monotonic-derived (see `docs/DECISIONS.md` ADR-048).
`t_salesbrain_started`→`t_salesbrain_finished` (the pre-existing internal Fast-Path
engine latency, Sprint 1 ADR-021/022) is recorded separately and must never be
reported as RSL. ASR delay (`t_audio_received`→`t_asr_final`) and turn-detection
delay (`t_asr_final`→`t_turn_end_detected`) are likewise recorded as their own
columns so bottlenecks are visible individually, per the original intent here.
`client_render_latency_ms` (Sprint 3A — the browser's own `performance.now()`
delta between receiving and painting the suggestion) is a further, separate
diagnostic, never merged into `real_rsl_ms`.

As of Sprint 3A, every stage through `t_suggestion_pushed` is populated by
`app/streaming/pipeline.py` for every finalized turn (whether or not a seller
browser is connected); `t_browser_received`/`t_ui_rendered`/`real_rsl_ms` are
populated later, asynchronously, only when that specific browser client actually
acknowledges rendering it — see `docs/DECISIONS.md` ADR-048 for the full design
and its "no real Twilio/Deepgram traffic yet" caveat (`is_synthetic`/`asr_provider`
still label every row honestly regardless of how complete its timing chain is).
