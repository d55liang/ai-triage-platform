"""Triage service tests. No worker exists yet, so they call the service directly.

Inside a test's transaction now() never changes, so a lease can't expire by waiting: tests move
claimed_at back by hand instead.
"""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.models.enums import TicketStatus
from app.models.orm import Ticket
from app.services.triage_service import Claim, claim_ticket, release_claim

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
    response = client.post("/api/tickets", json=TICKET)
    assert response.status_code == 201
    return UUID(response.json()["ticket_id"])


def create_definition(client: TestClient, name: str) -> UUID:
    response = client.post("/api/workflow-definitions", json={**WORKFLOW_DEFINITION, "name": name})
    assert response.status_code == 201
    return UUID(response.json()["definition_id"])


def get_ticket_status(client: TestClient, ticket_id: UUID) -> str:
    response = client.get(f"/api/tickets/{ticket_id}")
    assert response.status_code == 200
    return response.json()["status"]


def expire_claim(session: Session, claim: Claim) -> Claim:
    """Moves the lease 60 s into the past and returns the claim with the matching token."""
    claimed_at = session.scalars(
        update(Ticket)
        .where(Ticket.ticket_id == claim.ticket_id)
        .values(claimed_at=func.now() - timedelta(seconds=60))
        .returning(Ticket.claimed_at)
    ).one()
    return replace(claim, claimed_at=claimed_at)


def test_claim_queued_ticket(client: TestClient, session: Session) -> None:
    ticket_id = create_ticket(client)

    claim = claim_ticket(session, ticket_id)

    assert claim is not None
    assert claim.ticket_id == ticket_id
    assert claim.claimed_at is not None
    assert claim.request == TICKET["message"]
    assert get_ticket_status(client, ticket_id) == TicketStatus.TRIAGING


def test_claim_includes_only_enabled_definitions(client: TestClient, session: Session) -> None:
    enabled_id = create_definition(client, "Laptop Request")
    disabled_id = create_definition(client, "Monitor Request")
    assert client.post(f"/api/workflow-definitions/{disabled_id}/disable").status_code == 200
    ticket_id = create_ticket(client)

    claim = claim_ticket(session, ticket_id)

    candidate_ids = [definition.definition_id for definition, _ in claim.candidates]
    assert enabled_id in candidate_ids
    assert disabled_id not in candidate_ids


def test_claim_is_given_once(client: TestClient, session: Session) -> None:
    ticket_id = create_ticket(client)
    claim_ticket(session, ticket_id)

    # A duplicate delivery of the same message.
    assert claim_ticket(session, ticket_id) is None


def test_claim_cancelled_ticket(client: TestClient, session: Session) -> None:
    ticket_id = create_ticket(client)
    assert client.post(f"/api/tickets/{ticket_id}/cancel").status_code == 200

    assert claim_ticket(session, ticket_id) is None
    assert get_ticket_status(client, ticket_id) == TicketStatus.CANCELLED


def test_claim_unknown_ticket(session: Session) -> None:
    assert claim_ticket(session, uuid4()) is None


def test_claim_takes_over_expired_lease(client: TestClient, session: Session) -> None:
    ticket_id = create_ticket(client)
    stale = expire_claim(session, claim_ticket(session, ticket_id))

    claim = claim_ticket(session, ticket_id)

    assert claim is not None
    assert claim.claimed_at > stale.claimed_at
    assert get_ticket_status(client, ticket_id) == TicketStatus.TRIAGING


def test_release_returns_ticket_to_queued(client: TestClient, session: Session) -> None:
    ticket_id = create_ticket(client)
    claim = claim_ticket(session, ticket_id)

    release_claim(session, claim)

    assert get_ticket_status(client, ticket_id) == TicketStatus.QUEUED
    assert claim_ticket(session, ticket_id) is not None


def test_release_after_takeover_leaves_new_owner(client: TestClient, session: Session) -> None:
    ticket_id = create_ticket(client)
    stale = expire_claim(session, claim_ticket(session, ticket_id))
    claim_ticket(session, ticket_id)

    # The old owner's token no longer matches, so its release changes nothing.
    release_claim(session, stale)

    assert get_ticket_status(client, ticket_id) == TicketStatus.TRIAGING


def test_release_after_cancel_does_nothing(client: TestClient, session: Session) -> None:
    ticket_id = create_ticket(client)
    claim = claim_ticket(session, ticket_id)
    assert client.post(f"/api/tickets/{ticket_id}/cancel").status_code == 200

    release_claim(session, claim)

    assert get_ticket_status(client, ticket_id) == TicketStatus.CANCELLED
