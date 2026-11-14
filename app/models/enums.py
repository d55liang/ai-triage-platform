from enum import StrEnum


class TicketStatus(StrEnum):
    QUEUED = "QUEUED"
    TRIAGING = "TRIAGING"
    TRIAGED = "TRIAGED"
    UNMATCHED = "UNMATCHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WorkflowRunStatus(StrEnum):
    AWAITING_INPUTS = "AWAITING_INPUTS"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RequiredInputType(StrEnum):
    # Lowercase to match JSON Schema, so a Required Input maps straight into a tool schema.
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
