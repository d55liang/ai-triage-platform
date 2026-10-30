from typing import Annotated

from pydantic import BaseModel, Field


class CreateTicketRequest(BaseModel):
    user_id: Annotated[str, Field(description="ID of the creator of the ticket")]
    message: Annotated[str, Field(description="Message from the creator of the ticket")]


class UpdateTicketRequest(BaseModel):
    message: Annotated[str, Field(description="Message from the creator of the ticket")] = None
