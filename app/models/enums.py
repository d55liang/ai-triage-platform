from enum import StrEnum


class TicketStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    TRIAGING = "TRIAGING"
    TRIAGED = "TRIAGED"
    UNMATCHED = "UNMATCHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RequiredInputType(StrEnum):
    # Lowercase to match JSON Schema, so a Required Input maps straight into a tool schema.
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
