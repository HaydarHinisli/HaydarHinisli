# Pilot and Metrics

## 1. Pilot thesis

Can the same seller achieve better qualified conversation outcomes with REPLICA than without REPLICA?

## 2. Start narrow

Use:
- 1 product/offer
- 1 target segment
- 1–3 sellers
- comparable lead source
- 4–6 weeks

## 3. Product quality metrics

### Live quality
- RSL P50 / P95: end-of-turn → UI rendered
- Helpful Suggestion Rate: `good + usable` / rated suggestions
- Adoption Rate: suggestions actually used / shown
- Bad Suggestion Rate
- fallback/error rate

### Conversation quality
- 30-second conversation continuation
- discovery reached
- objection-to-continuation rate
- prospect question rate
- seller turn-length trend

These are diagnostic, not ultimate success metrics.

### Business outcomes
Priority order:
1. held meeting rate
2. qualified opportunity rate
3. proposal/deal progression
4. closed-won / revenue

Meeting booking alone is insufficient.

## 4. Baseline design

Preferred:
- randomize comparable leads/calls into control vs REPLICA
- same seller participates in both arms
- stratify by segment/campaign if needed

If randomization is impossible:
- matched cohorts
- fixed time windows
- control for lead source, role, offer, seller and campaign
- label results as observational, not causal

## 5. Report format for pilot customer

Show only a few top-line numbers:
- calls analyzed
- suggestion latency P50/P95
- helpful suggestion rate
- adoption rate
- held meeting rate control vs REPLICA
- qualified opportunity rate control vs REPLICA

Then include evidence level and sample size.

## 6. Pilot kill criteria

Stop/pivot if after sufficient usage:
- seller ignores most recommendations
- bad suggestion rate remains high
- P95 latency causes awkward pauses
- no improvement in conversation progression after iteration
- no plausible path to business outcome uplift

## 7. Never overclaim

Do not say:
- "REPLICA caused +20% revenue" from a before/after chart only
- "the Prospect was angry" from voice data
- "seller has low potential" from short-term KPIs

Say:
- observed
- associated
- experimentally supported
- replicated
