from sqlalchemy.orm import Session

from app.models.orm import OutboxEvent


def save_outbox_event(session: Session, event: dict) -> OutboxEvent:
    row = OutboxEvent(**event)
    session.add(row)
    session.flush()
    return row
