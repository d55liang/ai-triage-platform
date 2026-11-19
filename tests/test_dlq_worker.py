"""The DLQ consumer's handling of one dead letter, with the rolled-back session.

Each of its transactions is a savepoint here. Returning means the consumer deletes the message.
"""

import json
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import Transaction
from app.models.enums import TicketStatus
from app.models.orm import Ticket, WorkflowRun
from app.models.triage import MatchResult
from app.services.triage_service import ProviderScores, claim_ticket, finish_triage
from app.workers.dlq import handle_dead_letter

TICKET = {"user_id": "user-1", "message": "My laptop died, I need a new one"}
WORKFLOW_DEFINITION = {
    "name": "Laptop Request",
    "description": "Order a new laptop for the User",
    "confidence_threshold": "0.80",
    "steps": [{"name": "Place order", "instructions": "Order the laptop from the approved vendor"}],
    "required_inputs": [],
    "sample_requests": ["My laptop died, I need a new one"],
}


def create_ticket(client: TestClient) -> UUID:
    """A QUEUED Ticket, with one enabled Workflow Definition it could match."""
    response = client.post("/api/workflow-definitions", json=WORKFLOW_DEFINITION)
    assert response.status_code == 201
    response = client.post("/api/tickets", json=TICKET)
    assert response.status_code == 201
    return UUID(response.json()["ticket_id"])


def dead_letter(ticket_id: UUID) -> str:
    """A ticket.queued message as SQS moves it to the DLQ: unchanged."""
    return json.dumps(
        {
            "event_id": str(uuid4()),
            "event_type": "ticket.queued",
            "payload": {"ticket_id": str(ticket_id)},
        }
    )


def get_status(session: Session, ticket_id: UUID) -> str:
    return session.scalar(select(Ticket.status).where(Ticket.ticket_id == ticket_id))


def test_queued_ticket_is_failed(
    client: TestClient, session: Session, transaction: Transaction
) -> None:
    # Every attempt failed and released its claim.
    ticket_id = create_ticket(client)

    handle_dead_letter(dead_letter(ticket_id), transaction)

    assert get_status(session, ticket_id) == "FAILED"


def test_triaging_ticket_is_failed(
    client: TestClient, session: Session, transaction: Transaction
) -> None:
    # A worker crashed on the last receive, so its claim was never released.
    ticket_id = create_ticket(client)
    assert claim_ticket(session, ticket_id) is not None

    handle_dead_letter(dead_letter(ticket_id), transaction)

    assert get_status(session, ticket_id) == "FAILED"


def test_slow_worker_cannot_finish_failed_ticket(
    client: TestClient, session: Session, transaction: Transaction
) -> None:
    ticket_id = create_ticket(client)
    claim = claim_ticket(session, ticket_id)
    assert claim is not None
    handle_dead_letter(dead_letter(ticket_id), transaction)
    # Every candidate well above its threshold, so the slow worker would create a Run if it could.
    scores = ProviderScores(
        "a",
        "a-model",
        [
            MatchResult(version_id=version.version_id, match_confidence="0.95")
            for _, version in claim.candidates
        ],
    )

    with transaction():
        assert finish_triage(session, claim, [scores]) is None

    assert get_status(session, ticket_id) == "FAILED"
    assert (
        session.scalars(select(WorkflowRun).where(WorkflowRun.ticket_id == ticket_id)).all() == []
    )


@pytest.mark.parametrize(
    "status",
    [TicketStatus.TRIAGED, TicketStatus.UNMATCHED, TicketStatus.CANCELLED, TicketStatus.FAILED],
)
def test_ticket_that_moved_on_is_left_alone(
    client: TestClient, session: Session, transaction: Transaction, status: TicketStatus
) -> None:
    ticket_id = create_ticket(client)
    session.execute(update(Ticket).where(Ticket.ticket_id == ticket_id).values(status=status))

    handle_dead_letter(dead_letter(ticket_id), transaction)

    assert get_status(session, ticket_id) == status


def test_missing_ticket_is_ignored(transaction: Transaction) -> None:
    handle_dead_letter(dead_letter(uuid4()), transaction)


@pytest.mark.parametrize(
    "body",
    ["not json", json.dumps({"event_type": "ticket.queued", "payload": {}})],
    ids=["not-json", "no-ticket-id"],
)
def test_malformed_message_is_dropped(transaction: Transaction, body: str) -> None:
    # Unlike the triage worker, no exception: a dead letter has nowhere further to go.
    handle_dead_letter(body, transaction)
