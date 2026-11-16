from typing import Protocol

from app.models.triage import Candidate, MatchResult


class TriageProvider(Protocol):
    """One AI model that scores a Ticket against the candidates; adapters implement it per SDK."""

    name: str
    # The exact model ID, stored with every score.
    model: str

    # Async so a timeout can cancel the call itself. Implementations must await the SDK's async
    # client: a blocking call here would stall the event loop, and the timeout couldn't stop it.
    async def score(self, request: str, candidates: list[Candidate]) -> list[MatchResult]: ...
