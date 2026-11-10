from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import RequiredInputType, TicketStatus, WorkflowRunStatus


class TicketItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticket_id: Annotated[UUID, Field(description="Main ID of the ticket")]
    user_id: Annotated[str, Field(description="ID of the creator of the ticket")]
    message: Annotated[str, Field(description="Message from the creator of the ticket")]
    status: Annotated[TicketStatus, Field(description="Status of the ticket")]
    created_at: Annotated[datetime, Field(description="Creation time of the ticket")]


class TicketsResponse(BaseModel):
    data: Annotated[list[TicketItem], Field(description="List of all tickets")]


class StepItem(BaseModel):
    name: Annotated[str, Field(description="Short name of the step")]
    instructions: Annotated[str, Field(description="What to do in this step")]


class RequiredInputItem(BaseModel):
    key: Annotated[str, Field(description="snake_case name of the input")]
    description: Annotated[str, Field(description="What the input means")]
    type: Annotated[RequiredInputType, Field(description="Type of the input's value")]


class WorkflowDefinitionVersionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version_id: Annotated[UUID, Field(description="Main ID of the version")]
    version_number: Annotated[int, Field(description="1 for the first version, then 2, 3, ...")]
    description: Annotated[str, Field(description="What the workflow is for, read by Triage")]
    confidence_threshold: Annotated[
        Decimal,
        Field(description="Minimum Match Confidence for Triage to select this definition"),
    ]
    steps: Annotated[list[StepItem], Field(description="Ordered steps")]
    required_inputs: Annotated[
        list[RequiredInputItem],
        Field(description="Values a Workflow Run needs before it can start"),
    ]
    sample_requests: Annotated[
        list[str], Field(description="Examples of how a User might phrase this request")
    ]
    created_at: Annotated[datetime, Field(description="Creation time of the version")]


class WorkflowDefinitionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    definition_id: Annotated[UUID, Field(description="Main ID of the definition")]
    name: Annotated[str, Field(description="Unique name of the definition")]
    is_enabled: Annotated[bool, Field(description="Whether Triage may select this definition")]
    created_at: Annotated[datetime, Field(description="Creation time of the definition")]
    current_version: Annotated[
        WorkflowDefinitionVersionItem, Field(description="Highest-numbered version")
    ]


class WorkflowDefinitionsResponse(BaseModel):
    data: Annotated[list[WorkflowDefinitionItem], Field(description="Page of workflow definitions")]


class WorkflowRunItem(BaseModel):
    # Built from a Run, its version and a computed list, so there is no from_attributes.
    run_id: Annotated[UUID, Field(description="Main ID of the run")]
    ticket_id: Annotated[UUID, Field(description="Ticket the run was created for")]
    version_id: Annotated[UUID, Field(description="Workflow Definition Version the run follows")]
    definition_id: Annotated[UUID, Field(description="Workflow Definition the version belongs to")]
    version_number: Annotated[int, Field(description="Number of the version the run follows")]
    status: Annotated[WorkflowRunStatus, Field(description="Status of the run")]
    inputs: Annotated[
        dict[str, str | float | bool], Field(description="Required Input values supplied so far")
    ]
    missing_inputs: Annotated[
        list[str], Field(description="Keys of the Required Inputs not yet supplied")
    ]
    created_at: Annotated[datetime, Field(description="Creation time of the run")]
