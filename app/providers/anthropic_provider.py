from anthropic import AsyncAnthropic
from anthropic.types import Message

from app.models.triage import Candidate, MatchResult
from app.providers.triage_prompt import (
    SYSTEM_PROMPT,
    build_score_schema,
    build_user_message,
    parse_scores,
)

MODEL = "claude-haiku-5-5"
# The JSON is ~50 tokens per candidate, but thinking tokens count against the same limit, and
# hitting it fails the whole attempt.
MAX_TOKENS = 2048


def build_request(request: str, candidates: list[Candidate]) -> dict[str, object]:
    """The keyword arguments for messages.create."""
    # No temperature: API version 2026-10-21 rejects sampling parameters. Low effort keeps
    # adaptive thinking short for a classification task without turning it off.
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": build_user_message(request, candidates)}],
        "output_config": {
            "effort": "low",
            "format": {"type": "json_schema", "schema": build_score_schema(candidates)},
        },
    }


def read_answer(message: Message) -> str:
    """The JSON text, or ValueError unless the model finished normally.

    The schema is only guaranteed on end_turn: a refusal or a max_tokens cut-off can return text
    that doesn't match it.
    """
    if message.stop_reason != "end_turn":
        raise ValueError(f"Anthropic stopped with {message.stop_reason}")
    texts = [block.text for block in message.content if block.type == "text"]
    if not texts:
        raise ValueError("Anthropic returned no text")
    return texts[0]


class AnthropicProvider:
    """Scores with Claude Haiku through Anthropic's structured outputs."""

    name = "anthropic"
    model = MODEL

    def __init__(self) -> None:
        # Reads ANTHROPIC_API_KEY. Retries off: score_ticket's timeout is the only deadline, and
        # releasing the claim for SQS redelivery is the only retry.
        self._client = AsyncAnthropic(max_retries=0)

    async def score(self, request: str, candidates: list[Candidate]) -> list[MatchResult]:
        message = await self._client.messages.create(**build_request(request, candidates))
        return parse_scores(read_answer(message))
