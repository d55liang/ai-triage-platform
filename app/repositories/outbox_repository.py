from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.orm import OutboxEvent


def save_outbox_event(session: Session, event: dict) -> OutboxEvent:
    row = OutboxEvent(**event)
    session.add(row)
    session.flush()
    return row


def fetch_unpublished_events(session: Session, limit: int) -> list[OutboxEvent]:
    """Oldest first. SKIP LOCKED lets several relays run: each takes rows the others haven't locked."""
    statement = (
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(session.scalars(statement).all())


def modify_events_published(session: Session, event_ids: list[UUID]) -> None:
    session.execute(
        update(OutboxEvent)
        .where(OutboxEvent.event_id.in_(event_ids))
        .values(published_at=func.now())
    )
