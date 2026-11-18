"""The Anthropic Triage Provider: what it sends, how it reads the answer, and one live call.

Only the live test reaches the API; it's marked llm and runs only with pytest -m llm.
"""

import asyncio
from uuid import uuid4

import pytest
from anthropic.types import Message

from app.models.triage import Candidate
from app.providers.anthropic_provider import (
    MODEL,
    AnthropicProvider,
    build_request,
    read_answer,
)
from app.providers.triage_prompt import SYSTEM_PROMPT, build_score_schema, build_user_message

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


def make_message(content: list[dict[str, str]], stop_reason: str = "end_turn") -> Message:
    """A response as the API sends it, validated into the SDK's own type."""
    return Message.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": MODEL,
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }
    )


def test_request_sends_the_shared_prompt_and_schema() -> None:
    request = build_request(REQUEST, CANDIDATES)

    assert request["model"] == MODEL
    assert request["system"] == SYSTEM_PROMPT
    assert request["messages"] == [
        {"role": "user", "content": build_user_message(REQUEST, CANDIDATES)}
    ]
    assert request["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": build_score_schema(CANDIDATES)},
    }


def test_request_sets_no_sampling_parameters() -> None:
    # API version 2026-10-21 rejects them on every model.
    request = build_request(REQUEST, CANDIDATES)

    assert not {"temperature", "top_p", "top_k"} & request.keys()


def test_answer_is_the_text_after_thinking() -> None:
    message = make_message(
        [
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "text", "text": '{"a": 0.9}'},
        ]
    )

    assert read_answer(message) == '{"a": 0.9}'


@pytest.mark.parametrize(
    ("content", "stop_reason"),
    [
        ([{"type": "text", "text": "I can't help with that."}], "refusal"),
        ([{"type": "text", "text": '{"a": 0.'}], "max_tokens"),
        ([{"type": "thinking", "thinking": "", "signature": "sig"}], "end_turn"),
    ],
    ids=["refusal", "max-tokens", "no-text"],
)
def test_unfinished_answer_is_rejected(content: list[dict[str, str]], stop_reason: str) -> None:
    with pytest.raises(ValueError):
        read_answer(make_message(content, stop_reason))


@pytest.mark.llm
def test_live_scores_every_candidate() -> None:
    scores = asyncio.run(AnthropicProvider().score(REQUEST, CANDIDATES))

    by_id = {score.version_id: score.match_confidence for score in scores}
    assert by_id.keys() == {LAPTOP.version_id, MONITOR.version_id}
    assert by_id[LAPTOP.version_id] > by_id[MONITOR.version_id]
