from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

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
