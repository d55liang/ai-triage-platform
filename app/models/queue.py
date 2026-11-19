from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import OutboxEventType


class TicketPayload(BaseModel):
    ticket_id: Annotated[UUID, Field(description="ID of the Ticket the event is about")]


class TicketQueuedMessage(BaseModel):
    """The envelope the relay sends for a ticket.queued event, validated as the worker receives it.

    Any other event type fails validation, so a message on the wrong queue ends in the DLQ.
    """

    event_id: Annotated[UUID, Field(description="ID of the outbox event the message came from")]
    event_type: Annotated[
        Literal[OutboxEventType.TICKET_QUEUED], Field(description="Always ticket.queued")
    ]
    payload: Annotated[TicketPayload, Field(description="The event's data: only IDs")]
