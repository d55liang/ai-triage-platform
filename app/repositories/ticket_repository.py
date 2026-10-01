tickets = {}


def save_ticket(ticket: dict):
    tickets[ticket["ticket_id"]] = ticket
    return ticket


def fetch_ticket(ticket_id: str):
    try:
        ticket = tickets[ticket_id]
    except KeyError as e:
        raise KeyError(e) from e
    return ticket


def remove_ticket(ticket_id: str):
    try:
        ticket = tickets[ticket_id]
    except KeyError as e:
        raise KeyError(e) from e
    del tickets[ticket_id]
    ticket["status"]="DELETED"
    return ticket


def modify_ticket(ticket_id: str, params: dict):
    try:
        ticket = tickets[ticket_id]
    except KeyError as e:
        raise KeyError(e) from e
    for param in params:
        tickets[ticket_id][param] = params[param]
    return tickets[ticket_id]
