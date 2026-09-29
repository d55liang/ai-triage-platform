tickets = {}


def save_ticket(ticket: dict):
    tickets[ticket["ticket_id"]] = ticket
    return ticket
