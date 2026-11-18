"""Building Triage Providers from TRIAGE_PROVIDERS. Building a client sends no request."""

import pytest

from app.providers.anthropic_provider import AnthropicProvider
from app.providers.factory import build_providers
from app.providers.gemini_provider import GeminiProvider


@pytest.fixture(autouse=True)
def api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    # GeminiProvider raises without a key; GOOGLE_API_KEY would take priority over this one.
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


def test_builds_each_named_provider_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIAGE_PROVIDERS", "anthropic,gemini")

    providers = build_providers()

    assert [type(p) for p in providers] == [AnthropicProvider, GeminiProvider]


def test_ignores_spaces_around_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIAGE_PROVIDERS", " gemini , anthropic ")

    providers = build_providers()

    assert [p.name for p in providers] == ["gemini", "anthropic"]


def test_builds_a_single_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIAGE_PROVIDERS", "anthropic")

    providers = build_providers()

    assert [p.name for p in providers] == ["anthropic"]


@pytest.mark.parametrize(
    "names",
    ["", "openai", "anthropic,anthropic", "anthropic,"],
    ids=["empty", "unknown", "duplicate", "trailing-comma"],
)
def test_invalid_list_is_rejected(monkeypatch: pytest.MonkeyPatch, names: str) -> None:
    monkeypatch.setenv("TRIAGE_PROVIDERS", names)

    with pytest.raises(ValueError):
        build_providers()


def test_unset_variable_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRIAGE_PROVIDERS", raising=False)

    with pytest.raises(KeyError):
        build_providers()
