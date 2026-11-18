"""Builds the Triage Providers named in TRIAGE_PROVIDERS.

Its own module, so importing the Protocol (as the Triage service does) doesn't load every SDK.
"""

import os
from collections.abc import Callable

from dotenv import load_dotenv

from app.providers.anthropic_provider import AnthropicProvider
from app.providers.gemini_provider import GeminiProvider
from app.providers.triage_provider import TriageProvider

load_dotenv()

# Keyed by each class's own name, so the key and the provider name stored with every score
# can't drift apart.
PROVIDERS: dict[str, Callable[[], TriageProvider]] = {
    provider.name: provider for provider in (AnthropicProvider, GeminiProvider)
}


def build_providers() -> list[TriageProvider]:
    """One provider per name in TRIAGE_PROVIDERS, a comma-separated list such as "anthropic,gemini".

    Every name is checked before any client is built, so a bad list fails at startup rather than
    on the first Ticket.
    """
    # Read at call time, not import time, so tests can set it.
    value = os.environ["TRIAGE_PROVIDERS"]
    if not value.strip():
        raise ValueError("TRIAGE_PROVIDERS is empty")
    names = [name.strip() for name in value.split(",")]
    unknown = [name for name in names if name not in PROVIDERS]
    if unknown:
        raise ValueError(f"unknown Triage Providers {unknown}; choose from {sorted(PROVIDERS)}")
    # A repeat would call the same model twice and store every score twice.
    if len(names) != len(set(names)):
        raise ValueError(f"TRIAGE_PROVIDERS repeats a provider: {value}")
    return [PROVIDERS[name]() for name in names]
