# REPLICA Data Model — Cold Call Genome

## 1. Purpose

A call is not just an audio file. REPLICA stores a structured genome that connects conversation behavior with business outcome.

## 2. Core entities

### Company
- tenant boundary
- network-learning opt-in

### Seller
- company
- role
- hired_at
- product_started_at

`hired_at` and `product_started_at` are context variables, not a performance score.

### Call
- seller
- prospect company/role/segment
- offer/campaign
- consent state
- outcome flags
- external call ID

### Turn
Text/time:
- speaker
- text
- start/end timestamps
- ASR confidence

Acoustic/interaction:
- words_per_minute
- response_latency_ms
- pause_before_ms
- overlap_ms
- loudness dBFS
- pitch
- pitch range

Language:
- lexical complexity
- style snapshot

### Suggestion
- what REPLICA recommended
- strategy
- reason
- do-not
- confidence
- language policy
- reaction snapshot
- latency
- seller feedback
- used/not used

### Meeting
- external provider ID
- source
- scheduled time
- held/not held

### Deal
- CRM deal/opportunity stage
- amount
- closed won

### Experiment
- hypothesis
- variants
- primary metric
- assignment

### AuditEvent
- consent changes
- exports
- data deletion
- integration actions

## 3. Evidence levels

Every derived claim should carry one of:

1. `measured` — timestamp, pause, audio metric
2. `derived` — WPM, lexical complexity
3. `observed_association` — correlation across calls
4. `experimentally_supported` — randomized/controlled test
5. `replicated` — repeated across periods/segments

The UI should never display an association as if it were causal.

## 4. Prospect language profile

Do not store labels such as education/intelligence.
Store observable preferences only:
- sentence length
- jargon usage
- preferred terminology
- directness
- clarification requests
- answer length

## 5. Reaction Delta

Build a within-call baseline for the Prospect and compare later turns:
- WPM delta
- response latency delta
- turn length delta
- loudness delta
- pitch-range delta

These describe conversation changes. They do not prove emotion.

## 6. Data lineage

Every model-facing training sample should preserve:
- source call ID
- tenant ID
- consent / allowed-use state
- transformation version
- model/prompt version
- evidence level
- removal/deletion lineage
