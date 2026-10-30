from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TicketStatus


class TicketItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticket_id: Annotated[UUID, Field(description="Main ID of the ticket")]
    user_id: Annotated[str, Field(description="ID of the creator of the ticket")]
    message: Annotated[str, Field(description="Message from the creator of the ticket")]
    status: Annotated[TicketStatus, Field(description="Status of the ticket")]
    created_at: Annotated[datetime, Field(description="Creation time of the ticket")]


class TicketsResponse(BaseModel):
    data: Annotated[list[TicketItem], Field(description="List of all tickets")]
