"""The Gemini Triage Provider: what it sends, how it reads the answer, and one live call.

Only the live test reaches the API; it's marked llm and runs only with pytest -m llm.
"""

import asyncio
from uuid import uuid4

import pytest
from google.genai import types

from app.models.triage import Candidate
from app.providers.gemini_provider import GeminiProvider, build_config, read_answer
from app.providers.triage_prompt import SYSTEM_PROMPT, build_score_schema

REQUEST = "My laptop died, I need a new one"
LAPTOP = Candidate(
    version_id=uuid4(),
    name="Laptop Request",
    description="Order a new laptop for the User",
    sample_requests=["I need a new laptop", "My laptop is broken"],
)
MONITOR = Candidate(
    version_id=uuid4(),
    name="Monitor Request",
    description="Order an extra monitor for the User's desk",
    sample_requests=["I'd like a second screen", "Can I get a bigger monitor?"],
)
CANDIDATES = [LAPTOP, MONITOR]


def make_response(
    parts: list[dict[str, object]], finish_reason: str = "STOP"
) -> types.GenerateContentResponse:
    """A response as the API sends it, validated into the SDK's own type."""
    return types.GenerateContentResponse.model_validate(
        {
            "candidates": [
                {"content": {"role": "model", "parts": parts}, "finish_reason": finish_reason}
            ]
        }
    )


def test_config_sends_the_shared_prompt_and_schema() -> None:
    config = build_config(CANDIDATES)

    assert config.system_instruction == SYSTEM_PROMPT
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == build_score_schema(CANDIDATES)
    assert config.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL
    assert config.automatic_continuation is False


def test_config_sets_no_sampling_parameters() -> None:
    # Gemini 3.5 Flash-Lite ignores them; leaving them unset keeps that visible.
    config = build_config(CANDIDATES)

    assert config.temperature is None
    assert config.top_p is None
    assert config.top_k is None


def test_client_retries_are_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    # Private attribute: the SDK exposes no public getter, and the version is pinned.
    http_options = GeminiProvider()._client._api_client._http_options

    assert http_options.retry_options.attempts == 1


def test_answer_is_the_text_after_thinking() -> None:
    response = make_response([{"text": "Laptop fits.", "thought": True}, {"text": '{"a": 0.9}'}])

    assert read_answer(response) == '{"a": 0.9}'


@pytest.mark.parametrize(
    "response",
    [
        types.GenerateContentResponse.model_validate(
            {"prompt_feedback": {"block_reason": "PROHIBITED_CONTENT"}}
        ),
        make_response([{"text": '{"a": 0.'}], "MAX_TOKENS"),
        make_response([], "SAFETY"),
        make_response([]),
    ],
    ids=["blocked", "max-tokens", "safety", "no-text"],
)
def test_unfinished_answer_is_rejected(response: types.GenerateContentResponse) -> None:
    with pytest.raises(ValueError):
        read_answer(response)


@pytest.mark.llm
def test_live_scores_every_candidate() -> None:
    scores = asyncio.run(GeminiProvider().score(REQUEST, CANDIDATES))

    by_id = {score.version_id: score.match_confidence for score in scores}
    assert by_id.keys() == {LAPTOP.version_id, MONITOR.version_id}
    assert by_id[LAPTOP.version_id] > by_id[MONITOR.version_id]
