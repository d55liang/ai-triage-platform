import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.enums import TicketStatus
from app.models.triage import Candidate, MatchResult
from app.providers.triage_provider import TriageProvider
from app.repositories.ticket_repository import (
    fetch_ticket,
    modify_ticket_claim,
    modify_ticket_status,
)
from app.repositories.workflow_definition_repository import (
    DefinitionWithVersion,
    fetch_enabled_workflow_definitions,
)

# Longer than one attempt (providers in parallel, 20 s timeout) and shorter than the queue's 60 s
# visibility timeout, so the first redelivery after a crash can take the Ticket over.
CLAIM_LEASE = timedelta(seconds=45)
# One attempt must fit inside the lease, which must fit inside the visibility timeout:
# PROVIDER_TIMEOUT (20 s) < CLAIM_LEASE (45 s) < visibility timeout (60 s).
PROVIDER_TIMEOUT = timedelta(seconds=20)


@dataclass(frozen=True)
class Claim:
    """What a worker holds between claiming a Ticket and finishing or releasing it."""

    ticket_id: UUID
    # The fencing token: finishing or releasing only matches while the Ticket still has it.
    claimed_at: datetime
    request: str
    # As they were at claim time, so a Run pins the version that was actually scored.
    candidates: list[DefinitionWithVersion]


@dataclass(frozen=True)
class ProviderScores:
    """One Triage Provider's scores for every candidate, with what's needed to store them."""

    provider: str
    model: str
    scores: list[MatchResult]


def claim_ticket(session: Session, ticket_id: UUID) -> Claim | None:
    """Claims a QUEUED Ticket, or one whose lease expired; None if another worker holds it or the
    Ticket has moved on (cancelled, finished or deleted)."""
    claimed_at = modify_ticket_claim(session, ticket_id, CLAIM_LEASE)
    if claimed_at is None:
        return None
    ticket = fetch_ticket(session, ticket_id)
    candidates = fetch_enabled_workflow_definitions(session)
    return Claim(ticket_id, claimed_at, ticket.message, candidates)


def release_claim(session: Session, claim: Claim) -> None:
    """Hands a failed attempt's Ticket back to QUEUED, so the redelivery can claim it at once."""
    # ValueError: the Ticket was cancelled or another worker took over the lease. KeyError: it was
    # deleted. Either way nothing of ours is left to release.
    with suppress(ValueError, KeyError):
        modify_ticket_status(
            session,
            claim.ticket_id,
            [TicketStatus.TRIAGING],
            TicketStatus.QUEUED,
            claimed_at=claim.claimed_at,
        )


async def score_ticket(
    providers: list[TriageProvider],
    request: str,
    candidates: list[DefinitionWithVersion],
    timeout: timedelta = PROVIDER_TIMEOUT,
) -> list[ProviderScores]:
    """Asks every provider to score every candidate, concurrently, within one timeout.

    The only async step in Triage; it takes no session, so no transaction is open during the LLM
    calls. Raises TimeoutError, an ExceptionGroup of provider errors, or ValueError for output that
    doesn't score each candidate exactly once.
    """
    if not candidates:
        return []
    visible = [
        Candidate(
            version_id=version.version_id,
            name=definition.name,
            description=version.description,
            sample_requests=version.sample_requests,
        )
        for definition, version in candidates
    ]
    # The timeout cancels pending calls at their await; the TaskGroup cancels the others when one
    # fails. Either way no call outlives the attempt.
    async with asyncio.timeout(timeout.total_seconds()), asyncio.TaskGroup() as group:
        tasks = [group.create_task(provider.score(request, visible)) for provider in providers]

    expected = {candidate.version_id for candidate in visible}
    results = []
    for provider, task in zip(providers, tasks, strict=True):
        scores = task.result()
        scored = [score.version_id for score in scores]
        if len(scored) != len(set(scored)) or set(scored) != expected:
            raise ValueError(f"{provider.name} did not score each candidate exactly once")
        results.append(ProviderScores(provider.name, provider.model, scores))
    return results
