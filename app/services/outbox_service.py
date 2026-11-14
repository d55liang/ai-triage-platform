import json
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.enums import OutboxEventType
from app.queue import TRIAGE_QUEUE_URL, send_messages
from app.repositories.outbox_repository import fetch_unpublished_events, modify_events_published

# SendMessageBatch takes at most 10 messages, so one batch is one call per queue.
BATCH_SIZE = 10
EVENT_QUEUES = {OutboxEventType.TICKET_QUEUED: TRIAGE_QUEUE_URL}


def publish_pending_events(session: Session) -> int:
    """Sends the oldest unpublished events and marks the ones SQS accepted; returns how many.

    Runs in the caller's transaction, which holds the events' row locks until it commits.
    """
    events = fetch_unpublished_events(session, BATCH_SIZE)
    # Message bodies by event ID, grouped by the queue each event type goes to.
    batches: dict[str, dict[str, str]] = {}
    for event in events:
        # An envelope, so a consumer of a queue with several event types can tell them apart.
        body = {
            "event_id": str(event.event_id),
            "event_type": event.event_type,
            "payload": event.payload,
        }
        messages = batches.setdefault(EVENT_QUEUES[event.event_type], {})
        messages[str(event.event_id)] = json.dumps(body)

    sent: list[UUID] = []
    for queue_url, messages in batches.items():
        sent += [UUID(key) for key in send_messages(queue_url, messages)]
    if sent:
        modify_events_published(session, sent)
    return len(sent)
