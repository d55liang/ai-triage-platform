"""The triage worker's handling of one message, with fake providers and the rolled-back session.

Each of the worker's transactions is a savepoint here, so a test still undoes everything. The
receive-and-delete loop itself isn't tested; returning means the worker deletes the message.
"""

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import Ticket, TriageResult, WorkflowRun
from app.services.triage_service import claim_ticket
from app.workers.triage import Transaction, handle_message
from tests.fakes import FakeProvider

TICKET = {"user_id": "user-1", "message": "My laptop died, I need a new one"}
WORKFLOW_DEFINITION = {
    "name": "Laptop Request",
    "description": "Order a new laptop for the User",
    "confidence_threshold": "0.80",
    "steps": [{"name": "Place order", "instructions": "Order the laptop from the approved vendor"}],
    "required_inputs": [],
    "sample_requests": ["My laptop died, I need a new one"],
}


@pytest.fixture
def transaction(session: Session) -> Transaction:
    """Stands in for SessionLocal.begin: a savepoint on the test session."""

    @contextmanager
    def savepoint() -> Iterator[Session]:
        try:
            with session.begin_nested():
                yield session
        except Exception:
            # As in the client override: drop values a rolled-back UPDATE ... RETURNING refreshed.
            session.expire_all()
            raise

    return savepoint


@pytest.fixture
def runner() -> Iterator[asyncio.Runner]:
    with asyncio.Runner() as runner:
        yield runner


def create_ticket(client: TestClient) -> UUID:
    """A QUEUED Ticket, with one enabled Workflow Definition to score against."""
    response = client.post("/api/workflow-definitions", json=WORKFLOW_DEFINITION)
    assert response.status_code == 201
    response = client.post("/api/tickets", json=TICKET)
    assert response.status_code == 201
    return UUID(response.json()["ticket_id"])


def queued_message(ticket_id: UUID) -> str:
    """The body the relay sends for a ticket.queued event."""
    return json.dumps(
        {
            "event_id": str(uuid4()),
            "event_type": "ticket.queued",
            "payload": {"ticket_id": str(ticket_id)},
        }
    )


def get_ticket(session: Session, ticket_id: UUID) -> Ticket:
    return session.scalars(select(Ticket).where(Ticket.ticket_id == ticket_id)).one()


def count_rows(session: Session, model: type[TriageResult | WorkflowRun], ticket_id: UUID) -> int:
    return len(session.scalars(select(model).where(model.ticket_id == ticket_id)).all())


def test_agreement_triages_ticket(
    client: TestClient, session: Session, transaction: Transaction, runner: asyncio.Runner
) -> None:
    ticket_id = create_ticket(client)
    providers = [FakeProvider("a"), FakeProvider("b")]

    handle_message(queued_message(ticket_id), providers, runner, transaction)

    assert get_ticket(session, ticket_id).status == "TRIAGED"
    assert count_rows(session, WorkflowRun, ticket_id) == 1


def test_disagreement_leaves_ticket_unmatched(
    client: TestClient, session: Session, transaction: Transaction, runner: asyncio.Runner
) -> None:
    ticket_id = create_ticket(client)
    providers = [FakeProvider("a"), FakeProvider("b", confidence="0.10")]

    handle_message(queued_message(ticket_id), providers, runner, transaction)

    assert get_ticket(session, ticket_id).status == "UNMATCHED"
    assert count_rows(session, WorkflowRun, ticket_id) == 0


def test_ticket_claimed_elsewhere_is_left_alone(
    client: TestClient, session: Session, transaction: Transaction, runner: asyncio.Runner
) -> None:
    ticket_id = create_ticket(client)
    assert claim_ticket(session, ticket_id) is not None
    provider = FakeProvider("a")

    handle_message(queued_message(ticket_id), [provider], runner, transaction)

    assert provider.calls == []
    assert get_ticket(session, ticket_id).status == "TRIAGING"


def test_cancelled_ticket_is_left_alone(
    client: TestClient, session: Session, transaction: Transaction, runner: asyncio.Runner
) -> None:
    ticket_id = create_ticket(client)
    assert client.post(f"/api/tickets/{ticket_id}/cancel").status_code == 200
    provider = FakeProvider("a")

    handle_message(queued_message(ticket_id), [provider], runner, transaction)

    assert provider.calls == []
    assert get_ticket(session, ticket_id).status == "CANCELLED"


def test_provider_failure_releases_claim(
    client: TestClient, session: Session, transaction: Transaction, runner: asyncio.Runner
) -> None:
    ticket_id = create_ticket(client)
    providers = [FakeProvider("a"), FakeProvider("b", error=RuntimeError("provider down"))]

    with pytest.raises(ExceptionGroup):
        handle_message(queued_message(ticket_id), providers, runner, transaction)

    assert get_ticket(session, ticket_id).status == "QUEUED"
    assert count_rows(session, TriageResult, ticket_id) == 0


@pytest.mark.parametrize(
    "change",
    [{"event_type": "ticket.triaged"}, {"payload": {}}],
    ids=["other-event-type", "no-ticket-id"],
)
def test_malformed_message_is_rejected(
    client: TestClient,
    session: Session,
    transaction: Transaction,
    runner: asyncio.Runner,
    change: dict[str, object],
) -> None:
    ticket_id = create_ticket(client)
    body = json.dumps({**json.loads(queued_message(ticket_id)), **change})
    provider = FakeProvider("a")

    with pytest.raises(ValidationError):
        handle_message(body, [provider], runner, transaction)

    assert provider.calls == []
    assert get_ticket(session, ticket_id).status == "QUEUED"


def test_message_that_is_not_json_is_rejected(
    transaction: Transaction, runner: asyncio.Runner
) -> None:
    with pytest.raises(ValidationError):
        handle_message("not json", [FakeProvider("a")], runner, transaction)
