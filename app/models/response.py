from typing import Annotated

from pydantic import BaseModel, Field


class Ticket(BaseModel):
    ticket_id: Annotated[str, Field(description="Main ID of the ticket")]
    user_id: Annotated[str, Field(description="ID of the creator of the ticket")]
    message: Annotated[str, Field(description="Message from the creator of the ticket")]
    status: Annotated[str, Field(description="Status of the ticket")]
