from pydantic import BaseModel


class CreateTicketRequest(BaseModel):
    user_id: str
    message: str


class Ticket(BaseModel):
    ticket_id: str
    user_id: str
    message: str
    status: str
