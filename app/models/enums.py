from enum import StrEnum


class TicketStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    TRIAGING = "TRIAGING"
    TRIAGED = "TRIAGED"
    UNMATCHED = "UNMATCHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
