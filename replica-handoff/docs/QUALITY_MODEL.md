# REPLICA Quality Model — Hearing / Understanding / Helping

Sprint 2B requirement 6. These three dimensions are tracked **separately** and must
never be collapsed into a single "AI accuracy" number — a bad Suggestion caused by a
transcription error (Hearing) is a completely different problem, with a completely
different fix, than a bad Suggestion caused by SalesBrain misreading a correctly
transcribed sentence (Understanding), which is again different from a Suggestion
that was accurate but simply not useful to the seller in the moment (Helping). A
blended score would hide which of the three actually needs work.

## 1. Hearing — was the spoken word correctly transcribed?

Question: **how correct is the ASR transcript relative to what was actually said?**

This is the ASR provider's own quality, measured independently of everything
downstream. It is NOT judged by whether the resulting Suggestion was good — a
perfect transcript can still lead to a bad Suggestion (that's a Understanding or
Helping problem), and a good Suggestion can happen despite a flawed transcript by
accident (that must not be mistaken for good Hearing).

Concrete measurement, once real test calls exist:
- Word Error Rate (WER) / character-level diff between the ASR final transcript and
  a human-produced ground-truth transcript of the same audio segment.
- Provider-reported confidence (Deepgram returns per-word confidence — captured via
  `ASREvent.words`, see `app/streaming/deepgram_provider.py`) as a proxy signal,
  cross-checked against actual WER rather than trusted blindly.
- Per the VAD field test plan (`docs/VAD_FIELD_TEST_PLAN.md`): does transcript
  quality degrade under background noise, phone-speaker audio, or fast speech —
  and is that degradation visible in the provider's own confidence scores or does
  it silently produce confident-but-wrong text?

## 2. Understanding — did SalesBrain correctly interpret the (correctly heard) utterance?

Question: **given an accurate transcript, did REPLICA correctly identify the
conversation phase, the sales event, and any objection?**

This is evaluated against `app/services/sales_brain.py`'s own vocabulary — phase
(`greeting`, `rapport_smalltalk`, ..., `objection`, ...), event
(`classify_sales_event()`'s output), and objection type — compared to a human
sales-expert's own label for the same (correct) transcript.

Concrete measurement:
- Human-labeled ground truth for a sample of real call transcripts: "what phase was
  this really", "was this really an objection, and which kind".
- Compare against `ConversationStateEvent` rows (`from_phase`/`to_phase`/
  `event_type`/`objection_type`) produced for the same turns.
- Classification accuracy/confusion matrix per phase and per objection type — NOT a
  single blended "understanding score", since e.g. price-objection detection and
  smalltalk-vs-business-anchor detection are different sub-problems with different
  failure modes (see `docs/DECISIONS.md` ADR-024's smalltalk-anchor logic).

## 3. Helping — was the resulting Next-Best-Action actually useful to the seller?

Question: **given a correct transcript and a correct understanding of the
situation, was the suggested response something the seller would actually want to
say?**

This is the only dimension end users (sellers) can judge directly without needing a
transcript or a labeled phase — and the only one where "correct" isn't really the
right word at all; "useful in the moment" is a better frame.

Already partially instrumented: `Suggestion.rating` (`good`/`usable`/`bad`) and
`Suggestion.used` (`app/models.py`) exist precisely to capture this dimension
directly from the seller, per-suggestion, today — no new schema needed for the
MVP-level signal. What real test calls add on top:
- Whether the seller's own qualitative feedback (rating/used) correlates with
  Hearing/Understanding being correct — a "bad" rating on a suggestion where Hearing
  and Understanding were BOTH correct is real, specific Helping-quality signal (the
  suggestion itself needs work), distinct from a "bad" rating caused by an upstream
  transcription or classification error.
- Post-call review: did the seller actually use language close to the suggestion,
  and did the call outcome improve when they did (ties into the existing Reaction
  Delta / Cold Call Genome direction, `docs/ARCHITECTURE.md` §6) — a longer-horizon
  signal than per-turn rating.

## Why these must stay separate

A single "AI accuracy" metric cannot be acted on: it doesn't tell an engineer
whether to improve the ASR provider/config, the SalesBrain classification logic, or
the suggestion/playbook content. Reporting on Sprint 2B's (and any future) real test
calls must break results out along these three dimensions explicitly, even when the
sample size is small (a handful of real test calls, per the Definition of Done) —
directional signal per dimension is more useful than a single confident-looking
blended number from too little data.
