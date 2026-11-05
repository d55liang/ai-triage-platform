from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from app.models.enums import RequiredInputType


class CreateTicketRequest(BaseModel):
    user_id: Annotated[str, Field(description="ID of the creator of the ticket")]
    message: Annotated[str, Field(description="Message from the creator of the ticket")]


class UpdateTicketRequest(BaseModel):
    message: Annotated[str, Field(description="Message from the creator of the ticket")] = None


class StepRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=100, description="Short name of the step")]
    instructions: Annotated[
        str, Field(min_length=1, max_length=2000, description="What to do in this step")
    ]


class RequiredInputRequest(BaseModel):
    key: Annotated[
        str,
        Field(
            pattern=r"^[a-z][a-z0-9_]{0,49}$",
            description="snake_case name of the input, unique within the version",
        ),
    ]
    description: Annotated[
        str, Field(min_length=1, max_length=500, description="What the input means")
    ]
    type: Annotated[RequiredInputType, Field(description="Type of the input's value")]


class CreateWorkflowDefinitionRequest(BaseModel):
    name: Annotated[
        str, Field(min_length=1, max_length=100, description="Unique name of the definition")
    ]
    description: Annotated[
        str,
        Field(
            min_length=1, max_length=2000, description="What the workflow is for, read by Triage"
        ),
    ]
    confidence_threshold: Annotated[
        Decimal,
        Field(
            gt=0,
            le=1,
            max_digits=3,
            decimal_places=2,
            description="Minimum Match Confidence for Triage to select this definition",
        ),
    ]
    steps: Annotated[
        list[StepRequest], Field(min_length=1, max_length=20, description="Ordered steps")
    ]
    required_inputs: Annotated[
        list[RequiredInputRequest],
        Field(max_length=20, description="Values a Workflow Run needs before it can start"),
    ]
    sample_requests: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=500)]],
        Field(
            min_length=1,
            max_length=5,
            description="Examples of how a User might phrase this request, read by Triage",
        ),
    ]

    @field_validator("required_inputs")
    @classmethod
    def keys_are_unique(
        cls, required_inputs: list[RequiredInputRequest]
    ) -> list[RequiredInputRequest]:
        keys = [required_input.key for required_input in required_inputs]
        if len(keys) != len(set(keys)):
            raise ValueError("Required Input keys must be unique")
        return required_inputs


class UpdateWorkflowDefinitionRequest(BaseModel):
    name: Annotated[
        str, Field(min_length=1, max_length=100, description="Unique name of the definition")
    ] = None
