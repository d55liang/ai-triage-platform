from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.enums import TicketStatus
from app.models.orm import Ticket

ALLOWED_COLUMNS = ["message"]


def save_ticket(session: Session, ticket: dict) -> Ticket:
    row = Ticket(**ticket)
    session.add(row)
    session.flush()
    return row


def fetch_all_tickets(session: Session) -> list[Ticket]:
    tickets = session.scalars(select(Ticket).order_by(Ticket.created_at)).all()
    return list(tickets)


def fetch_ticket(session: Session, ticket_id: UUID) -> Ticket:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise KeyError(ticket_id)
    return ticket


def remove_ticket(session: Session, ticket_id: UUID) -> Ticket:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise KeyError(ticket_id)
    session.delete(ticket)
    return ticket


def modify_ticket(session: Session, ticket_id: UUID, params: dict) -> Ticket:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise KeyError(ticket_id)
    columns = [column for column in params if column in ALLOWED_COLUMNS]
    for column in columns:
        setattr(ticket, column, params[column])
    return ticket


def modify_ticket_status(
    session: Session, ticket_id: UUID, expected: list[TicketStatus], status: TicketStatus
) -> Ticket:
    # Compare-and-set: checking the status in the UPDATE stops a concurrent change being overwritten.
    ticket = session.scalars(
        update(Ticket)
        .where(Ticket.ticket_id == ticket_id, Ticket.status.in_(expected))
        .values(status=status)
        .returning(Ticket)
    ).one_or_none()
    if ticket is None:
        # No row matched: fetch_ticket raises KeyError if it's missing, so past it the status is the problem.
        fetch_ticket(session, ticket_id)
        raise ValueError(ticket_id)
    return ticket
