import uuid

from app.repositories.ticket_repository import save_ticket


def create_ticket(user_id: str, message: str):
    # TODO:
    # 1. Generate a unique ticket_id
    ticket_id = str(uuid.uuid4())
    # 2. Create the ticket object
    ticket = {
        "ticket_id": ticket_id,
        "user_id": user_id,
        "message": message,
        "status": "CREATED"
    }
    # 3. Set status to "CREATED"
    # 4. Save the ticket using the repository
    return save_ticket(ticket)
    # 5. Return the saved ticket
