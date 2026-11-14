---
status: accepted
---

# Triage requires every Triage Provider to agree

Triage asks several Triage Providers (today the Anthropic API and Gemini Flash) to score each Ticket independently, and creates a Workflow Run only when every one of them selects the same Workflow Definition at or above its Confidence Threshold. Anything else, including disagreement, leaves the Ticket UNMATCHED, and the Intake Agent asks the User to clarify. A wrong Run starts work nobody asked for, while an UNMATCHED Ticket costs one question, so precision is worth more than recall here. Every provider's selection is stored in `triage_results`, which also gives a running comparison of the providers.

## Considered options

- **One primary provider, with offline evaluation on a labelled set:** cheaper and faster, but one model's mistakes go straight to Runs.
- **Shadow mode:** other providers score in production but never decide; a comparison without the precision gain.
- **A separate `DISPUTED` status for disagreement:** more precise, but the User gets the same clarifying questions as for UNMATCHED.

## Consequences

- Cost is the sum of the providers, latency is the slowest one, and an outage of any provider fails Triage until it recovers. Gemini's free-tier rate limit caps Triage throughput.
- UNMATCHED means both "nothing qualified" and "the providers disagreed"; only `triage_results` tells them apart.
- Changing the rule later changes what every past UNMATCHED meant, so historical outcomes must be read with the rule in force at the time.
