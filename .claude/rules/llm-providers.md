---
paths:
  - "app/providers/**"
  - "tests/test_*_provider.py"
---

# LLM provider rules

Rationale is in `DESIGN.md` §18 (*Triage Provider adapters*).

## Clients

- Use each SDK's **async** client (`AsyncAnthropic`, `genai.Client().aio`), created once per provider instance and reused. Never call a sync client inside `async def score`: it blocks the event loop, and `score_ticket`'s timeout can't cancel it (`python.md`).
- Turn SDK retries off: `max_retries=0` on Anthropic, `HttpOptions(retry_options=HttpRetryOptions(attempts=1))` on Gemini. Leaving Gemini's retry options unset still retries dropped connections. `score_ticket`'s `asyncio.timeout` is the only deadline, and releasing the claim for SQS redelivery is the only retry. Don't set a separate SDK timeout.
- API keys come from the environment (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`), read by the SDK itself. `GOOGLE_API_KEY` overrides `GEMINI_API_KEY` if both are set, so don't set it. Never pass a key in code or log one.

## Requests

- Every provider sends the shared `SYSTEM_PROMPT`, `build_user_message` and `build_score_schema` from `app/providers/triage_prompt.py`. Change the prompt there, never in one adapter, so scores stay comparable.
- Structured output with the per-request schema, never free text parsed by hand. Anthropic: `output_config={"format": {"type": "json_schema", "schema": ...}}` on `messages.create`. Gemini: `response_mime_type="application/json"` and `response_json_schema=...` on `GenerateContentConfig`. The schema has no `minimum`/`maximum`, which Anthropic doesn't support; `MatchResult` checks the range.
- No `temperature`, `top_p` or `top_k`. Anthropic API version `2026-10-21` (SDK 2.x) rejects them, and Gemini 3.5 Flash-Lite ignores them. Tune reasoning instead: `output_config.effort="low"` on Anthropic, `ThinkingConfig(thinking_level=MINIMAL)` on Gemini, both set explicitly.
- Gemini: `automatic_continuation=False`, so one call is one billed request inside the deadline.
- Thinking tokens count against `max_tokens` (Gemini: `max_output_tokens`); leave headroom, since hitting the limit fails the attempt.
- Never send a Confidence Threshold to a provider. Thresholds are compared in code.

## Responses

- Accept an answer only when the model finished normally (Anthropic: `stop_reason == "end_turn"`; Gemini: no `block_reason` and `finish_reason == STOP`). Anything else, or no text, raises `ValueError`. Gemini's `response.text` already skips thought parts.
- Parse with `parse_scores`, which reads numbers as `Decimal` and validates each `MatchResult`. Which candidates were scored is checked by `score_ticket`.
- Let SDK exceptions propagate unchanged; `score_ticket` collects them into an `ExceptionGroup`.

## Models

- Model IDs are constants in each adapter (`claude-haiku-5-5`, `gemini-3.5-flash-lite`) and are stored with every score. Use the exact ID with no date suffix.
