from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.enums import TicketStatus
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


@dataclass(frozen=True)
class Claim:
    """What a worker holds between claiming a Ticket and finishing or releasing it."""

    ticket_id: UUID
    # The fencing token: finishing or releasing only matches while the Ticket still has it.
    claimed_at: datetime
    request: str
    # As they were at claim time, so a Run pins the version that was actually scored.
    candidates: list[DefinitionWithVersion]


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
