from fastapi import APIRouter, HTTPException

from app.models.request import CreateTicketRequest, UpdateTicketRequest
from app.models.response import Ticket
from app.services.ticket_service import create_ticket, delete_ticket, get_ticket, update_ticket


ticket_router = APIRouter(
    prefix="/tickets",
    tags=["tickets"]
)


@ticket_router.post("", response_model=Ticket, status_code=201)
def create_ticket_api(request: CreateTicketRequest):
    return create_ticket(
        user_id=request.user_id,
        message=request.message
    )


@ticket_router.get("/{ticket_id}", response_model=Ticket, status_code=200)
def get_ticket_api(ticket_id: str):
    try:
        ticket = get_ticket(ticket_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found.") from e
    return ticket


@ticket_router.delete("/{ticket_id}", response_model=Ticket, status_code=200)
def delete_ticket_api(ticket_id: str):
    try:
        ticket = delete_ticket(ticket_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Delete failed: ticket {ticket_id} not found.") from e
    return ticket


@ticket_router.patch("/{ticket_id}", response_model=Ticket, status_code=200)
def update_ticket_api(ticket_id: str, request: UpdateTicketRequest):
    request_dict = request.model_dump(exclude_unset=True)
    try:
        ticket = update_ticket(ticket_id, request_dict)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Update failed: ticket {ticket_id} not found.")
    return ticket
