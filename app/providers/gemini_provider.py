from google import genai
from google.genai import types

from app.models.triage import Candidate, MatchResult
from app.providers.triage_prompt import (
    SYSTEM_PROMPT,
    build_score_schema,
    build_user_message,
    parse_scores,
)

MODEL = "gemini-3.5-flash-lite"
# Same limit as Claude: thinking tokens count against it, and hitting it fails the attempt.
MAX_OUTPUT_TOKENS = 2048


def build_config(candidates: list[Candidate]) -> types.GenerateContentConfig:
    """The config for generate_content."""
    # No temperature: Gemini 3.5 Flash-Lite ignores sampling parameters. Minimal thinking is the
    # current default, set explicitly so a default change can't alter scoring.
    # automatic_continuation off: one score call is one billed request inside the deadline.
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_json_schema=build_score_schema(candidates),
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
        max_output_tokens=MAX_OUTPUT_TOKENS,
        automatic_continuation=False,
    )


def read_answer(response: types.GenerateContentResponse) -> str:
    """The JSON text, or ValueError unless the model finished normally.

    A blocked prompt has no candidates, and a SAFETY or MAX_TOKENS finish can return text that
    doesn't match the schema.
    """
    if response.prompt_feedback and response.prompt_feedback.block_reason:
        raise ValueError(f"Gemini blocked the prompt: {response.prompt_feedback.block_reason}")
    if not response.candidates:
        raise ValueError("Gemini returned no candidates")
    finish_reason = response.candidates[0].finish_reason
    if finish_reason != types.FinishReason.STOP:
        raise ValueError(f"Gemini stopped with {finish_reason}")
    # .text joins the answer's text parts and skips thought parts.
    if not response.text:
        raise ValueError("Gemini returned no text")
    return response.text


class GeminiProvider:
    """Scores with Gemini Flash-Lite through Gemini's structured outputs."""

    name = "gemini"
    model = MODEL

    def __init__(self) -> None:
        # Reads GEMINI_API_KEY (GOOGLE_API_KEY wins if both are set) and raises without one.
        # attempts=1 turns retries off; left unset, the SDK still retries dropped connections.
        self._client = genai.Client(
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))
        )

    async def score(self, request: str, candidates: list[Candidate]) -> list[MatchResult]:
        response = await self._client.aio.models.generate_content(
            model=MODEL,
            contents=build_user_message(request, candidates),
            config=build_config(candidates),
        )
        return parse_scores(read_answer(response))
