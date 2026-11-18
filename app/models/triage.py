from decimal import ROUND_HALF_EVEN, Decimal
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field


def _round_to_hundredths(value: Decimal) -> Decimal:
    # Match NUMERIC(3,2): the value compared with the threshold is exactly the value stored.
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


class Candidate(BaseModel):
    """What a Triage Provider sees of a Workflow Definition: never its threshold.

    A model that saw the threshold could steer its score toward it.
    """

    version_id: Annotated[UUID, Field(description="ID of the Workflow Definition Version to score")]
    name: Annotated[str, Field(description="Name of the Workflow Definition")]
    description: Annotated[str, Field(description="What the Workflow Definition handles")]
    sample_requests: Annotated[
        list[str], Field(description="Examples of how a User might phrase this need")
    ]


class MatchResult(BaseModel):
    """One Triage Provider's Match Confidence for one candidate, validated at the boundary."""

    version_id: Annotated[UUID, Field(description="ID of the Workflow Definition Version scored")]
    # The range is checked before rounding, so 1.004 is rejected rather than rounded into range.
    match_confidence: Annotated[
        Decimal,
        Field(ge=0, le=1, description="How sure the provider is that the Ticket belongs here"),
        AfterValidator(_round_to_hundredths),
    ]
