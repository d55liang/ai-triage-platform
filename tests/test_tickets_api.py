from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.main import app
from app.models.enums import TicketStatus
from app.models.orm import Ticket

TICKET = {"user_id": "user-1", "message": "Reset my password"}
UPDATE_MESSAGE = {"message": "Updated message"}
UPDATE_MESSAGE_NULL = {"message": None}
UPDATE_STATUS = {"status": TicketStatus.TRIAGED}
LIST_LENGTH = 10


def create_ticket(client: TestClient) -> dict:
    response = client.post("/api/tickets", json=TICKET)
    assert response.status_code == 201
    return response.json()


def get_ticket(client: TestClient, ticket_id: str) -> dict:
    response = client.get(f"/api/tickets/{ticket_id}")
    assert response.status_code == 200
    assert response.json()["ticket_id"] == ticket_id
    return response.json()


def set_status(session: Session, ticket_id: str, status: TicketStatus) -> None:
    """Only cancelling changes a status through the API so far, so tests set the rest directly."""
    session.get(Ticket, UUID(ticket_id)).status = status
    session.flush()


def test_create_ticket(client: TestClient) -> None:
    ticket = create_ticket(client)

    assert ticket["user_id"] == TICKET["user_id"]
    assert ticket["message"] == TICKET["message"]
    assert ticket["status"] == TicketStatus.QUEUED
    assert ticket["created_at"] is not None


def test_get_ticket(client: TestClient) -> None:
    ticket = create_ticket(client)

    response = client.get(f"/api/tickets/{ticket['ticket_id']}")

    assert response.status_code == 200
    assert response.json() == ticket


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_tickets(client: TestClient) -> None:
    tickets = [create_ticket(client) for _ in range(LIST_LENGTH)]

    response = client.get("/api/tickets")
    assert response.status_code == 200

    ids = {ticket["ticket_id"] for ticket in response.json()["data"]}
    assert ids == {ticket["ticket_id"] for ticket in tickets}


def test_update_ticket_message(client: TestClient) -> None:
    ticket = create_ticket(client)

    response = client.patch(f"/api/tickets/{ticket['ticket_id']}", json=UPDATE_MESSAGE)

    assert response.status_code == 200
    updated_ticket = get_ticket(client, ticket["ticket_id"])
    assert updated_ticket["message"] == UPDATE_MESSAGE["message"]


def test_patch_cannot_change_status(client: TestClient) -> None:
    ticket = create_ticket(client)

    response = client.patch(f"/api/tickets/{ticket['ticket_id']}", json=UPDATE_STATUS)

    assert response.status_code == 200
    updated_ticket = get_ticket(client, ticket["ticket_id"])
    assert updated_ticket["status"] == ticket["status"]


def test_patch_rejects_null_message(client: TestClient) -> None:
    ticket = create_ticket(client)

    response = client.patch(f"/api/tickets/{ticket['ticket_id']}", json=UPDATE_MESSAGE_NULL)
    assert response.status_code == 422


def test_delete_ticket(client: TestClient) -> None:
    ticket = create_ticket(client)

    response_delete = client.delete(f"/api/tickets/{ticket['ticket_id']}")
    assert response_delete.status_code == 200
    assert response_delete.json() == ticket

    response_get = client.get(f"/api/tickets/{ticket['ticket_id']}")
    assert response_get.status_code == 404


@pytest.mark.parametrize(
    "status",
    [
        TicketStatus.QUEUED,
        TicketStatus.TRIAGING,
        TicketStatus.UNMATCHED,
    ],
)
def test_cancel_ticket(client: TestClient, session: Session, status: TicketStatus) -> None:
    ticket = create_ticket(client)
    set_status(session, ticket["ticket_id"], status)

    response = client.post(f"/api/tickets/{ticket['ticket_id']}/cancel")

    assert response.status_code == 200
    assert response.json() == {**ticket, "status": TicketStatus.CANCELLED}
    assert get_ticket(client, ticket["ticket_id"])["status"] == TicketStatus.CANCELLED


def test_cancel_ticket_twice_succeeds(client: TestClient) -> None:
    ticket = create_ticket(client)

    response_first = client.post(f"/api/tickets/{ticket['ticket_id']}/cancel")
    response_second = client.post(f"/api/tickets/{ticket['ticket_id']}/cancel")

    assert response_first.status_code == 200
    assert response_second.status_code == 200
    assert response_second.json() == response_first.json()


# A TRIAGED Ticket always has a Run, so its cancel tests are in test_workflow_runs_api.py.
@pytest.mark.parametrize("status", [TicketStatus.FAILED])
def test_cancel_rejected_for_status(
    client: TestClient, session: Session, status: TicketStatus
) -> None:
    ticket = create_ticket(client)
    set_status(session, ticket["ticket_id"], status)

    response = client.post(f"/api/tickets/{ticket['ticket_id']}/cancel")

    assert response.status_code == 409
    assert get_ticket(client, ticket["ticket_id"])["status"] == status


def test_unknown_ticket_returns_404(client: TestClient) -> None:
    ticket_id = uuid4()

    response_get = client.get(f"/api/tickets/{ticket_id}")
    assert response_get.status_code == 404

    response_patch = client.patch(f"/api/tickets/{ticket_id}", json=UPDATE_MESSAGE)
    assert response_patch.status_code == 404

    response_delete = client.delete(f"/api/tickets/{ticket_id}")
    assert response_delete.status_code == 404

    response_cancel = client.post(f"/api/tickets/{ticket_id}/cancel")
    assert response_cancel.status_code == 404


def test_malformed_ticket_id_returns_422(client: TestClient) -> None:
    malformed_id = "123abc"

    response_get = client.get(f"/api/tickets/{malformed_id}")
    assert response_get.status_code == 422

    response_cancel = client.post(f"/api/tickets/{malformed_id}/cancel")
    assert response_cancel.status_code == 422


def test_create_ticket_commits() -> None:
    """Uses the real get_session, so the row persists and must be removed here."""
    response = TestClient(app).post("/api/tickets", json=TICKET)
    assert response.status_code == 201
    ticket_id = UUID(response.json()["ticket_id"])

    try:
        with SessionLocal() as session:
            assert session.get(Ticket, ticket_id) is not None
    finally:
        with SessionLocal.begin() as session:
            session.execute(delete(Ticket).where(Ticket.ticket_id == ticket_id))
