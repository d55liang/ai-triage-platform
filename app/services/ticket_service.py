import uuid

from app.models.enums import TicketStatus
from app.repositories.ticket_repository import fetch_all_tickets, fetch_ticket, modify_ticket, save_ticket, remove_ticket


def create_ticket(user_id: str, message: str):
    ticket_id = str(uuid.uuid4())
    ticket = {
        "ticket_id": ticket_id,
        "user_id": user_id,
        "message": message,
        "status": TicketStatus.CREATED
    }
    return save_ticket(ticket)


def get_all_tickets():
    return fetch_all_tickets()


def get_ticket(ticket_id: str):
    try:
        ticket = fetch_ticket(ticket_id)
    except KeyError as e:
        raise KeyError(e) from e
    return ticket


def delete_ticket(ticket_id: str):
    try:
        ticket = remove_ticket(ticket_id)
    except KeyError as e:
        raise KeyError(e) from e
    return ticket


def update_ticket(ticket_id: str, params: dict):
    try:
        ticket = modify_ticket(ticket_id, params)
    except KeyError as e:
        raise KeyError(e) from e
    return ticket
