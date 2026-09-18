# REPLICA Global Product & Compliance Specification v1.0

> Engineering specification, not legal advice. Every production launch requires jurisdiction-specific legal review. The purpose of this document is to ensure the codebase can enforce legal/product boundaries instead of relying on policy text alone.

## 0. Executive engineering mandate

REPLICA is **not** primarily an autonomous cold-calling robot.

The default product is:

1. **REPLICA Assist** — a human seller speaks; REPLICA provides low-latency live guidance.
2. **REPLICA Intelligence** — post-call analysis, coaching, quality measurement and downstream CRM outcomes.
3. **REPLICA Manager** — contextual team insights, ramp-up and coaching opportunities, with human management decision-making.
4. **REPLICA Agent** — autonomous voice operation only where a jurisdiction and customer use case have been reviewed and explicitly enabled.

The architecture must make these four modes separable. Do not couple autonomous calling to the core intelligence layer.

---

## 1. Product principles that are mandatory in code

### 1.1 Human augmentation first
The core value proposition is: **make the seller better, not remove human judgment by default**.

### 1.2 Observable signals, not hidden psychology
REPLICA may measure:
- speech rate
- response latency
- pause duration
- interruptions / overlap
- word choice
- sentence length
- vocabulary complexity
- turn duration
- relative loudness change
- pitch/F0 and pitch range where technically reliable

REPLICA must not infer or store workplace labels such as:
- angry
- anxious
- insecure
- depressed
- frustrated
- low intelligence
- low education
- personality type
- protected/sensitive traits inferred from voice, accent or language

Use `reaction_delta` / `communication_pattern`, never `emotion_score`.

### 1.3 No automated employment verdict
REPLICA must never output:
- fire / terminate recommendation
- "bad seller" label
- suitability score for continued employment
- automated ranking intended to decide promotion/termination
- probability that a seller should be dismissed

Allowed manager outputs:
- observed outcomes
- trend over time
- ramp-up/product tenure context
- coaching opportunities
- data quality / sample size
- external/context factors where known
- uncertainty

### 1.4 Explainable recommendations
Every live suggestion and post-call observation must be traceable to:
- source call/turn
- model/prompt/rule version
- evidence level
- confidence or data quality marker where applicable

### 1.5 Private learning is default
Raw customer data does not enter a cross-customer training pool by default.

---

## 2. Runtime product modes

### A. REPLICA Assist
Human seller remains the speaker.

Inputs:
- live transcript/interim transcript
- optional consented audio-derived features
- product/offer context
- seller playbook
- prospect language profile for the current call

Outputs:
- one `SAG JETZT` suggestion
- one delivery hint
- one `NICHT` hint

Hard latency target for pilot:
- P50 <= 500 ms after detected end-of-turn
- P95 <= 800 ms after detected end-of-turn

No blocking large-model call in Fast Path.

### B. REPLICA Intelligence
Post-call:
- summary
- strengths
- improvement points
- missed opportunities
- one next-call focus
- downstream outcomes when CRM/calendar data is available

### C. REPLICA Manager
Manager view must separate:
1. results
2. conversation/process metrics
3. trend
4. ramp-up / product tenure
5. lead/campaign context
6. uncertainty / sample size

### D. REPLICA Agent
Autonomous speaking is a separately licensed and feature-flagged capability.
Default: OFF in every jurisdiction.

---

## 3. Data model additions

Add the following entities or equivalent tables.

### `jurisdiction_policy`
- `country_code`
- `region_code` nullable
- `policy_version`
- `effective_from`
- `human_copilot_allowed`
- `audio_recording_mode` enum: `legal_review`, `consent_required`, `provider_rule`, `disabled`
- `live_ai_listening_mode` enum
- `autonomous_marketing_call_mode` enum: `disabled`, `consent_only`, `review_required`, `allowed_with_conditions`
- `ai_identity_disclosure_required`
- `employee_analytics_mode` enum: `assist_only`, `high_risk_controls`, `disabled`
- `emotion_inference_allowed` default false
- `network_intelligence_mode`
- `notes`

### `consent_event`
- `tenant_id`
- `call_id`
- `subject_type` (`prospect`, `seller`)
- `purpose`
- `consent_version`
- `status`
- `captured_at`
- `captured_by`
- `source`
- `withdrawn_at`
- `evidence_ref`

Consent purposes must be granular. Example:
- call_recording
- transcription
- live_copilot_processing
- customer_private_learning
- cross_customer_network_learning

Do not model these as one all-purpose boolean.

### `seller_context`
- `seller_id`
- `employment_start_date`
- `team_start_date`
- `product_start_date`
- `segment_start_date`
- `role`

This is context, not an HR record system.

### `evidence_metric`
- `call_id`
- `seller_id`
- `metric_type`
- `value`
- `measurement_method`
- `evidence_level`
- `sample_size`
- `confidence_interval_low` nullable
- `confidence_interval_high` nullable
- `data_quality_flags`

Evidence levels:
- `measured`
- `derived`
- `observed_association`
- `experimentally_supported`
- `replicated`

### `network_learning_contribution`
- `tenant_id`
- `opt_in_version`
- `allowed_data_classes`
- `effective_from`
- `revoked_at`

### `network_benchmark_cell`
Store aggregate only. Never expose raw competitor-level rows.
- segment dimensions
- time bucket
- company_count
- observation_count
- metric
- aggregate value
- dispersion / CI
- minimum cohort threshold passed
- publication delay passed

---

## 4. LanguageSync rules

LanguageSync adapts communication style, not human worth or intelligence.

Allowed signals:
- average sentence length
- vocabulary rarity/complexity
- domain terminology
- use of Anglicisms
- prospect-preferred terms
- direct vs. indirect question style
- response length
- clarification requests

Allowed output:
- simpler wording
- more precise wording
- shorter sentence
- use prospect's preferred terminology
- reduce jargon
- increase domain precision when prospect uses it

Forbidden inference examples:
- "low education"
- "low IQ"
- ethnicity/nationality from accent
- socioeconomic status from speech

Store `communication_preference`, not demographic inference.

---

## 5. Reaction Delta rules

Always calculate relative change against a within-call baseline where possible.

Example:
- baseline response latency = 410 ms
- post-pricing response latency = 920 ms
- delta = +510 ms

Do NOT transform this automatically into `negative_emotion=true`.

Network/audio telemetry must be stored alongside reaction timing where available so latency caused by telecom/network quality is not falsely attributed to the prospect.

Data quality flags should include:
- packet loss high
- RTT spike
- ASR confidence low
- channel separation unavailable
- background noise high

---

## 6. Seller protection and manager analytics

The manager module must be built around **contextual performance**, not punishment automation.

Manager UI sections:
1. Outcomes
2. Controllable conversation factors
3. Development trend
4. Ramp-adjusted context
5. Lead/campaign context
6. Coaching opportunity
7. Evidence quality

Example of an acceptable manager statement:
> Current meeting outcomes are below team baseline, while discovery and objection-handling indicators have improved over the last four weeks. Connect rate and reachable-decision-maker share are also below the campaign baseline.

Unacceptable:
> Seller is underperforming and should be terminated.

### Germany/EU specific engineering trigger
If manager analytics is enabled for employee monitoring/evaluation, set deployment flag:
`employment_ai_review_required=true`.

Require:
- documented human oversight
- access logging
- manager acknowledgement that output is decision support
- configurable data retention
- employee-facing transparency configuration
- exportable audit trail

In Germany, additionally expose a deployment checklist item for works council review where applicable.

---

## 7. Learning architecture

### Layer 1 — In-call adaptation
Temporary only.
- current prospect language profile
- current conversation state
- no model-weight update

### Layer 2 — Customer-private learning
Tenant-specific learning from approved data.
- customer playbooks
- customer outcome patterns
- customer terminology
- tenant-specific prompts/adapters/policies

### Layer 3 — REPLICA Network Intelligence
Opt-in only.

Allowed design:
- aggregated patterns
- anonymised/pseudonymised inputs where appropriate
- customer contribution lineage
- withdrawal handling
- minimum cohort sizes
- delayed publication

Not allowed by product policy:
- exposing competitor identities
- competitor-specific current pricing
- competitor-specific customer lists
- future commercial plans
- identifiable discount strategy
- future capacity/output strategy
- raw cross-tenant transcripts to another customer

---

## 8. Competition / antitrust guardrails for Network Intelligence

The platform itself can become a conduit for unlawful competitor information exchange if built carelessly.

Therefore implement:

### 8.1 No direct competitor comparison for sensitive commercial data
Never render:
- "Competitor X charges EUR 4,900"
- "Competitor Y will reduce prices next quarter"
- "Company Z is targeting Client ABC"

### 8.2 Aggregation threshold
Initial engineering default (policy choice, not a statutory safe harbour):
- `MIN_COMPANIES_PER_BENCHMARK_CELL = 10`
- prefer 20+ for sensitive commercial performance metrics

Legal team must be able to raise this threshold per jurisdiction/sector.

### 8.3 Publication delay
Initial engineering default:
- `MIN_BENCHMARK_AGE_DAYS = 90`

No real-time cross-company pricing/strategy benchmark.

### 8.4 Sensitive data blacklist
Global Network Intelligence must reject fields such as:
- current/future price per named SKU/customer
- named customer identity
- bid terms
- future strategy
- unpublished launch plans
- future production/capacity
- competitor-specific discount schedule

### 8.5 Aggregation service boundary
Cross-tenant analytics must run through a dedicated aggregation service. Ordinary tenant application queries must never have cross-tenant raw data access.

---

## 9. Jurisdiction Policy Engine

Every call session must resolve a policy **before** enabling recording, autonomous speech, or employee analytics.

Policy resolution inputs:
- customer tenant country
- called number country
- seller location where relevant
- prospect type (`consumer`, `business`, `unknown`)
- campaign type (`cold_marketing`, `existing_customer`, `requested_callback`, `inbound`, `follow_up`)
- speaker mode (`human`, `ai_voice`)
- recording requested yes/no

Output:
- allowed features
- blocked features
- required disclosures
- consent requirements
- logging obligations
- `legal_review_required`

If policy cannot be resolved confidently, fail closed for autonomous marketing calls and recording.

---

## 10. Initial jurisdiction matrix

This table is an engineering default, not a complete legal opinion.

### Germany / EU
**Human copilot:** potentially deployable subject to privacy/telemarketing rules.

**B2B live cold call:** Germany requires at least presumed consent for calls to non-consumer market participants; consumer calls require prior express consent.

**Automated calling machine:** prior express consent required under German UWG wording.

**AI direct interaction:** AI Act transparency obligations apply when a natural person directly interacts with the AI unless obvious.

**Workplace emotion inference:** disabled. EU AI Act prohibits emotion inference in the workplace except narrow medical/safety exceptions.

**Employee performance AI:** treat as a regulated/high-risk deployment path; high-risk Annex III rules apply from 2 Dec 2027 under the current AI Act timeline. Human oversight and compliance workflow required.

**Germany works council:** deployment checklist must flag employee-monitoring functionality because BetrVG provides co-determination rights for technical systems intended to monitor behaviour/performance and requires consultation on AI/work-process planning.

**Default autonomous cold outbound:** OFF.

### United Kingdom
**Live B2B marketing calls:** support only with compliance workflow for TPS/CTPS, prior objections and caller identity requirements.

**Automated marketing calls:** consent-required mode only.

**Default autonomous cold outbound:** OFF pending specific review.

### United States
**AI/artificial voice:** FCC treats AI-generated voice as artificial/prerecorded voice under TCPA; outbound consumer calls using such voice require prior express consent absent an exemption, with additional telemarketing obligations.

**B2B telemarketing:** FTC rules include recordkeeping and prohibit material misrepresentations/false or misleading statements in B2B telemarketing.

**Recording:** state-specific rules vary; do not ship one US-wide recording rule.

**Default autonomous cold outbound:** OFF; enable only under counsel-approved campaign configuration.

### Canada
**ADAD / robocall solicitation:** express consent required.

**Default autonomous solicitation:** consent-only and legal-review mode.

### Australia
Do Not Call Register primarily protects eligible personal numbers; business phone numbers generally cannot be registered unless mixed-use requirements are met. Telemarketing industry standards still impose conduct rules broadly.

Implement:
- number-washing integration hook where required
- consent / withdrawal state
- local calling-time and identification policy hooks

### Singapore
B2B marketing messages made for the receiving organisation's business purposes are excluded from DNC specified-message rules, while other PDPA obligations can still apply.

Engineering must distinguish true B2B purpose from personal/consumer marketing.

### India
Commercial communications are governed through TRAI's TCCCPR framework and DLT-based mechanisms; the consolidated regulation was updated in 2026 and the framework continues to evolve.

Default for pilot:
- `legal_review_required=true`
- no autonomous outbound until local telecom/telemarketer registration, number ranges, consent/preferences and DLT obligations are mapped.

---

## 11. Consent and recording state machine

Implement state machine rather than boolean:

`not_requested -> requested -> granted | denied -> withdrawn`

Per purpose.

Before processing that requires consent:
1. policy engine resolves requirement
2. consent event exists and is valid
3. consent version/purpose matches processing
4. no withdrawal exists

If denied/withdrawn:
- recording stops
- prohibited processing stops
- raw audio retention job applies

Do not silently downgrade a consented purpose into another purpose (e.g. "quality" -> global model training).

---

## 12. AI identity and autonomous agent disclosure

When `speaker_mode=ai_voice`, the conversation service must expose a pre-call/first-interaction disclosure hook.

Required fields:
- disclosure text version
- timestamp
- locale/language
- delivery success state

The exact disclosure text is jurisdiction/customer specific and must live in configuration, not hardcoded logic.

---

## 13. Manipulation boundary

REPLICA may optimise clarity and relevance.

Allowed:
- simplify language
- shorten turns
- use prospect terminology
- ask a better discovery question
- adjust speaking pace within normal conversational bounds

Do not build policies whose objective is to exploit inferred vulnerability.

Examples that must be rejected:
- target inferred financial desperation
- target disability or age vulnerability
- exploit supposed anxiety detected from voice
- subliminal or deceptive persuasion mechanisms

Policy engine / model safety layer should classify and reject such strategy requests.

---

## 14. CRM and meeting outcome integration

REPLICA needs outcome data to evaluate usefulness.

Minimum external events:
- meeting booked
- meeting held/cancelled/no-show
- opportunity created
- opportunity stage changed
- proposal sent (optional)
- closed won/lost
- revenue/ARR where customer chooses to provide it

Store provenance:
- provider
- external object ID
- sync timestamp
- field mapping version

Never treat CRM outcomes alone as proof of causal effect. Experiments must record treatment/control assignment.

---

## 15. Experimental learning requirements

Every experiment must include:
- hypothesis
- unit of randomisation
- eligibility criteria
- control
- treatment(s)
- primary metric
- secondary/guardrail metrics
- start/end dates
- sample size
- exposure logging

Do not allow the analytics UI to label correlation as causation.

UI language:
- `Observed association` until controlled experiment
- `Experimentally supported` only after valid experiment criteria
- `Replicated` only after repeated result in a distinct cohort/time period

---

## 16. API additions

Suggested endpoints:

- `POST /v1/policy/resolve`
- `GET /v1/policy/jurisdictions/{country}`
- `POST /v1/calls/{id}/consents`
- `POST /v1/calls/{id}/consents/{purpose}/withdraw`
- `GET /v1/calls/{id}/processing-permissions`
- `POST /v1/network-learning/opt-in`
- `POST /v1/network-learning/withdraw`
- `GET /v1/network-benchmarks`
- `GET /v1/sellers/{id}/development-context`
- `GET /v1/audit/export`

All endpoints must be tenant scoped.

---

## 17. Required frontend states

### Seller live screen
Only:
- SAG JETZT
- DELIVERY
- NICHT
- consent/processing status indicator when relevant

### Seller post-call
- summary
- strengths
- improvements
- missed opportunity
- next focus
- feedback buttons

### Manager
- outcomes
- trend
- coaching indicators
- ramp/product tenure context
- sample size / evidence quality

Never default to leaderboard ordering by "best/worst employee".

### Admin / Compliance
- jurisdiction policies
- consent configuration
- retention rules
- integrations
- Network Intelligence opt-in
- audit export
- autonomous-agent feature flags

---

## 18. Feature flags that must exist

- `FEATURE_AUTONOMOUS_VOICE_AGENT`
- `FEATURE_CALL_RECORDING`
- `FEATURE_LIVE_AUDIO_FEATURES`
- `FEATURE_EMPLOYEE_MANAGER_ANALYTICS`
- `FEATURE_NETWORK_INTELLIGENCE`
- `FEATURE_CROSS_TENANT_BENCHMARKS`
- `FEATURE_AI_IDENTITY_DISCLOSURE`
- `FEATURE_EXPERIMENT_ENGINE`

Flags must be resolvable per tenant + jurisdiction + campaign.

---

## 19. Tests that are required before pilot

### Compliance tests
1. autonomous voice blocked when jurisdiction policy says disabled
2. recording blocked when required consent missing
3. withdrawal immediately disables future processing for that purpose
4. cross-tenant raw data query fails
5. Network Intelligence cell below minimum company threshold is not returned
6. current competitor-specific price never appears in benchmark output
7. emotion labels rejected from workplace analysis pipeline
8. manager endpoint never returns firing/replacement recommendation
9. AI-voice call cannot start when required identity disclosure configuration is missing
10. unresolved jurisdiction fails closed for autonomous marketing calls

### Product tests
1. live suggestion Fast Path works without Smart Path
2. LanguageSync changes wording but never infers education/intelligence
3. Reaction Delta stores measurements, not emotion conclusions
4. manager view separates result from trend/context
5. seller tenure modifies context only, never a deterministic employment score
6. downstream CRM meeting/opportunity is linked to source call
7. experiment UI distinguishes association vs experimentally supported outcome

---

## 20. Deployment gates

### Gate A — Internal demo
No real prospect data required.

### Gate B — Single seller pilot
Required:
- jurisdiction review
- consent/recording workflow where applicable
- DPA/vendor agreements
- retention configuration
- audit logs

### Gate C — Multi-seller company pilot
Additionally:
- worker transparency process
- employee analytics review
- works council / employee representation workflow where applicable
- RBAC

### Gate D — Network Intelligence
Additionally:
- explicit customer opt-in
- competition-law review
- aggregation service
- minimum cohort / delay rules
- data contribution and withdrawal lineage

### Gate E — Autonomous outbound agent
Highest review threshold.
Required:
- jurisdiction-specific telemarketing analysis
- AI voice/robocall rules
- consent basis where required
- AI identity disclosure
- opt-out handling
- campaign-level legal approval flag

---

## 21. Engineering decisions: what NOT to build

Do not build yet:
- custom foundation model
- custom TTS engine
- emotion recognition
- employee firing score
- psychographic vulnerability targeting
- autonomous global mass dialer
- raw cross-company data marketplace
- real-time competitor price intelligence

Build first:
- human live copilot
- low latency
- LanguageSync
- measurable Reaction Delta
- post-call coaching
- CRM outcome linking
- evidence quality
- customer-private learning

---

## 22. Official legal/regulatory references to keep in the engineering/legal review backlog

Primary sources currently relevant:
- EU Artificial Intelligence Act, including Article 5, Article 50 and Annex III employment-related high-risk uses (EUR-Lex / European Commission)
- EU GDPR, especially Article 22 and general transparency/lawfulness requirements (EUR-Lex)
- Germany UWG §7 telephone advertising
- Germany BetrVG §§87 and 90
- Germany BDSG §26 employee data processing
- UK ICO PECR guidance for live and automated marketing calls
- US FCC Declaratory Ruling FCC 24-17 on AI-generated voices under TCPA
- US FTC Telemarketing Sales Rule amendments covering B2B misrepresentations and recordkeeping
- Canada CRTC Unsolicited Telecommunications / ADAD rules
- Australia ACMA / Do Not Call Register and telemarketing industry standards
- Singapore PDPC DNC guidance and B2B exclusion
- India TRAI TCCCPR consolidated rules and DLT/commercial communication directions
- European Commission Horizontal Cooperation Guidelines, information exchange via third parties/platforms
- US FTC antitrust guidance on competitor information exchange

Legal counsel must validate current law at deployment time; regulation can change after this document version.
