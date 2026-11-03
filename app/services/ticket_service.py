from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models.enums import TicketStatus
from app.models.orm import Ticket
from app.repositories.ticket_repository import (
    fetch_all_tickets,
    fetch_ticket,
    modify_ticket,
    modify_ticket_status,
    remove_ticket,
    save_ticket,
)

# CANCELLED is included so a retried cancel succeeds.
# TRIAGED is excluded until cancelling can also cancel the Workflow Run.
CANCELLABLE_STATUSES = [
    TicketStatus.CREATED,
    TicketStatus.QUEUED,
    TicketStatus.TRIAGING,
    TicketStatus.UNMATCHED,
    TicketStatus.CANCELLED,
]


def create_ticket(session: Session, user_id: str, message: str) -> Ticket:
    ticket_id = uuid4()
    ticket = {
        "ticket_id": ticket_id,
        "user_id": user_id,
        "message": message,
        "status": TicketStatus.CREATED,
    }
    return save_ticket(session, ticket)


def get_all_tickets(session: Session) -> list[Ticket]:
    return fetch_all_tickets(session)


def get_ticket(session: Session, ticket_id: UUID) -> Ticket:
    return fetch_ticket(session, ticket_id)


def delete_ticket(session: Session, ticket_id: UUID) -> Ticket:
    return remove_ticket(session, ticket_id)


def update_ticket(session: Session, ticket_id: UUID, params: dict) -> Ticket:
    return modify_ticket(session, ticket_id, params)


def cancel_ticket(session: Session, ticket_id: UUID) -> Ticket:
    return modify_ticket_status(session, ticket_id, CANCELLABLE_STATUSES, TicketStatus.CANCELLED)
