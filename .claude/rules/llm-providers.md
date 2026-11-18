---
paths:
  - "app/providers/**"
  - "tests/test_*_provider.py"
---

# LLM provider rules

Rationale is in `DESIGN.md` §18 (*Triage Provider adapters*).

## Clients

- Use each SDK's **async** client (`AsyncAnthropic`), created once per provider instance and reused. Never call a sync client inside `async def score`: it blocks the event loop, and `score_ticket`'s timeout can't cancel it (`python.md`).
- Turn SDK retries off (`max_retries=0`). `score_ticket`'s `asyncio.timeout` is the only deadline, and releasing the claim for SQS redelivery is the only retry. Don't set a separate SDK timeout.
- API keys come from the environment (`ANTHROPIC_API_KEY`), read by the SDK itself. Never pass a key in code or log one.

## Requests

- Every provider sends the shared `SYSTEM_PROMPT`, `build_user_message` and `build_score_schema` from `app/providers/triage_prompt.py`. Change the prompt there, never in one adapter, so scores stay comparable.
- Structured output with the per-request schema, never free text parsed by hand. Anthropic: `output_config={"format": {"type": "json_schema", "schema": ...}}` on `messages.create`. The schema has no `minimum`/`maximum`, which Anthropic doesn't support; `MatchResult` checks the range.
- No `temperature`, `top_p` or `top_k`. Anthropic API version `2026-10-21` (SDK 2.x) rejects them. Tune with `output_config.effort` instead; Triage uses `"low"`.
- Thinking tokens count against `max_tokens`; leave headroom, since hitting the limit fails the attempt.
- Never send a Confidence Threshold to a provider. Thresholds are compared in code.

## Responses

- Accept an answer only when the model finished normally (Anthropic: `stop_reason == "end_turn"`). A refusal or a `max_tokens` cut-off raises `ValueError`.
- Parse with `parse_scores`, which reads numbers as `Decimal` and validates each `MatchResult`. Which candidates were scored is checked by `score_ticket`.
- Let SDK exceptions propagate unchanged; `score_ticket` collects them into an `ExceptionGroup`.

## Models

- Model IDs are constants in each adapter (`claude-haiku-5-5`) and are stored with every score. Use the exact ID with no date suffix.
