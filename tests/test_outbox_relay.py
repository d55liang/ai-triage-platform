import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import OutboxEventType
from app.models.orm import OutboxEvent
from app.queue import TRIAGE_QUEUE_URL, sqs_client
from app.services.outbox_service import publish_pending_events

TICKET = {"user_id": "user-1", "message": "My laptop died, I need a new one"}


@pytest.fixture(autouse=True)
def empty_queue() -> Iterator[None]:
    """The queue isn't rolled back with the database, so each test starts and ends with it empty."""
    sqs_client.purge_queue(QueueUrl=TRIAGE_QUEUE_URL)
    yield
    sqs_client.purge_queue(QueueUrl=TRIAGE_QUEUE_URL)


def receive_bodies() -> list[dict]:
    response = sqs_client.receive_message(
        QueueUrl=TRIAGE_QUEUE_URL, MaxNumberOfMessages=10, WaitTimeSeconds=1
    )
    return [json.loads(message["Body"]) for message in response.get("Messages", [])]


def get_event(session: Session, ticket_id: str) -> OutboxEvent:
    return session.scalars(
        select(OutboxEvent).where(OutboxEvent.payload["ticket_id"].astext == ticket_id)
    ).one()


def test_publish_sends_queued_ticket_event(client: TestClient, session: Session) -> None:
    ticket_id = client.post("/api/tickets", json=TICKET).json()["ticket_id"]
    event = get_event(session, ticket_id)

    assert publish_pending_events(session) == 1

    assert receive_bodies() == [
        {
            "event_id": str(event.event_id),
            "event_type": OutboxEventType.TICKET_QUEUED,
            "payload": {"ticket_id": ticket_id},
        }
    ]
    assert get_event(session, ticket_id).published_at is not None


def test_published_event_is_not_sent_again(client: TestClient, session: Session) -> None:
    client.post("/api/tickets", json=TICKET)
    publish_pending_events(session)
    receive_bodies()

    assert publish_pending_events(session) == 0
    assert receive_bodies() == []


def test_publish_sends_at_most_one_batch(client: TestClient, session: Session) -> None:
    for _ in range(11):
        client.post("/api/tickets", json=TICKET)

    assert publish_pending_events(session) == 10
    assert publish_pending_events(session) == 1
