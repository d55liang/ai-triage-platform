"""Test doubles shared across test files."""

import asyncio
from decimal import Decimal

from app.models.triage import Candidate, MatchResult


class FakeProvider:
    """Scores every candidate with one value, unless told to raise, hang or wait at a barrier."""

    def __init__(
        self,
        name: str,
        confidence: str = "0.90",
        error: Exception | None = None,
        hang: bool = False,
        barrier: asyncio.Barrier | None = None,
        results: list[MatchResult] | None = None,
    ) -> None:
        self.name = name
        self.model = f"{name}-model"
        self.confidence = Decimal(confidence)
        self.error = error
        self.hang = hang
        self.barrier = barrier
        self.results = results
        self.calls: list[tuple[str, list[Candidate]]] = []
        self.cancelled = False

    async def score(self, request: str, candidates: list[Candidate]) -> list[MatchResult]:
        self.calls.append((request, candidates))
        try:
            if self.barrier is not None:
                await self.barrier.wait()
            if self.hang:
                await asyncio.Event().wait()
            if self.error is not None:
                # Yield first, so the other provider is mid-call when this one fails.
                await asyncio.sleep(0)
                raise self.error
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self.results is not None:
            return self.results
        return [
            MatchResult(version_id=c.version_id, match_confidence=self.confidence)
            for c in candidates
        ]
