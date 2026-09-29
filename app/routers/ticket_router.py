from fastapi import APIRouter

from app.models.ticket import CreateTicketRequest, Ticket
from app.services.ticket_service import create_ticket


router = APIRouter(
    prefix="/tickets",
    tags=["tickets"]
)


@router.post("", response_model=Ticket, status_code=201)
def create_ticket_api(request: CreateTicketRequest):
    return create_ticket(
        user_id=request.user_id,
        message=request.message
    )
