# VAD Field Test Plan (Sprint 2B requirement 4)

Purpose: `app/streaming/vad.py`'s fixed-threshold, fixed-hangover
`VoiceActivityDetector` was built and unit-tested against synthetic audio (silence
bytes vs. a synthesized tone — see `tests/test_streaming_dsp.py`). It has never been
measured against real telephone audio. Per the explicit instruction, it is **not**
to be replaced pre-emptively — this plan exists to collect the data that decides
whether it needs to be replaced by adaptive VAD, provider endpointing (Deepgram's
`speech_final`/`UtteranceEnd`, already captured for comparison — see
`docs/DECISIONS.md` ADR-046), or some combination, once real test calls exist.

Every scenario below must be run with consenting test persons only (never a real
external prospect — see the Sprint 2B Definition of Done) and produces:
1. The real audio (retained per the tenant's own retention policy, not a Sprint 2B
   concern) for manual listen-back against what REPLICA detected.
2. The resulting `TurnLatencyTrace`/`ConversationStateEvent` rows for that call,
   which already carry `provider_endpoint_vs_turn_end_ms` (ADR-046) and the VAD's
   own turn-count/timing — no new instrumentation needed to start collecting.

## What to record for every scenario

- **False turn-ends**: VAD declared silence (and thus a final turn) while the
  speaker was still mid-thought (a pause the fixed 300ms hangover didn't absorb).
- **Missed/late turn-ends**: VAD kept waiting past when a human listener would
  clearly say the person had finished talking.
- **Energy-threshold misses**: speech present but below `energy_threshold`, not
  detected as speaking at all (a quiet voice, a bad connection).
- **False positives**: non-speech (noise, breathing, line hiss) registered as
  speaking.
- **`provider_endpoint_vs_turn_end_ms`**: how far off Deepgram's own endpointing was
  from our VAD's turn-end for the same utterance, once a real ASR provider is wired
  in (Sprint 2B is prepared for this; the comparison itself needs real Deepgram
  traffic, which is not yet available — see the Sprint 2B report).

## Scenarios to collect (per the explicit list)

| # | Scenario | What it stresses |
|---|---|---|
| 1 | Ruhige Umgebung (quiet room) | Baseline — establishes whether the fixed threshold is even roughly right under best-case conditions. |
| 2 | Hintergrundgeräusche (background noise) | False-positive risk (threshold too low for the noise floor) and false-negative risk (real speech masked). |
| 3 | Headset | Likely the cleanest real-world signal; a second baseline besides "quiet room" since headset mic gain/proximity differs from a room mic. |
| 4 | Telefonlautsprecher (phone speaker/handsfree) | Real telephony line degradation, echo, lower signal-to-noise — the case the fixed threshold is most likely to fail on. |
| 5 | Kurze Denkpausen (short thinking pauses) | Whether the 300ms hangover is well-calibrated — too short falsely ends turns on a pause, too long delays real turn-ends. |
| 6 | Sehr kurze Antworten (very short answers, e.g. "Ja.", "Nein.") | Whether a short utterance still crosses the energy threshold long enough to register as speech at all before hangover kicks in. |
| 7 | Schneller Sprecher (fast speaker) | Whether word-level ASR timestamps (once real Deepgram traffic exists) and our turn boundaries stay coherent at speech rates the synthetic tests never exercised. |
| 8 | Langsamer Sprecher (slow speaker) | Whether natural inter-word pauses at a slow cadence get misread as turn-end. |
| 9 | Seller/Prospect Overlap | Exercises `TurnDetector`'s overlap flagging (ADR-039) against a REAL simultaneous-speech event, not the synthetic timing used in `tests/test_streaming_turn_detector.py`. |

## Decision criteria (after data collection, not before)

Only after collecting real measurements across these scenarios do we decide between:
- Keep the fixed threshold/hangover, possibly retuned with real numbers.
- Adaptive VAD (noise-floor-relative threshold).
- Rely more on provider endpointing (`speech_final`) once a real ASR provider is
  live, using our own VAD as a fallback/cross-check instead of the primary signal.
- A combination (e.g. provider endpointing for turn-end, our own VAD only for
  interim speaker-activity signals like overlap detection).

This is explicitly a data-driven decision per the Sprint 2B requirements, not an
engineering preference — do not act on this table until real recordings exist.
