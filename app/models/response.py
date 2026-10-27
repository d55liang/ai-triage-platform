from typing import Annotated

from pydantic import BaseModel, Field

from app.models.enums import TicketStatus


class TicketItem(BaseModel):
    ticket_id: Annotated[str, Field(description="Main ID of the ticket")]
    user_id: Annotated[str, Field(description="ID of the creator of the ticket")]
    message: Annotated[str, Field(description="Message from the creator of the ticket")]
    status: Annotated[TicketStatus, Field(description="Status of the ticket")]
    created_at: Annotated[str, Field(description="Creation time of the ticket")]


class TicketsResponse(BaseModel):
    data: Annotated[list[TicketItem], Field(description="List of all tickets")]
