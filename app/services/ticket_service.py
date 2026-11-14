from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models.enums import TicketStatus, WorkflowRunStatus
from app.models.orm import Ticket
from app.repositories.ticket_repository import (
    fetch_all_tickets,
    fetch_ticket,
    modify_ticket,
    modify_ticket_status,
    remove_ticket,
    save_ticket,
)
from app.repositories.workflow_run_repository import (
    fetch_workflow_run_by_ticket,
    modify_workflow_run_status,
)

# CANCELLED is included so a retried cancel succeeds. TRIAGED is cancellable because
# cancelling also cancels the Ticket's Workflow Run.
CANCELLABLE_STATUSES = [
    TicketStatus.QUEUED,
    TicketStatus.TRIAGING,
    TicketStatus.TRIAGED,
    TicketStatus.UNMATCHED,
    TicketStatus.CANCELLED,
]
# COMPLETED and FAILED are left out: finished work can't be withdrawn, so its Ticket can't
# be cancelled either.
CANCELLABLE_RUN_STATUSES = [
    WorkflowRunStatus.AWAITING_INPUTS,
    WorkflowRunStatus.READY,
    WorkflowRunStatus.RUNNING,
    WorkflowRunStatus.CANCELLED,
]


def create_ticket(session: Session, user_id: str, message: str) -> Ticket:
    ticket_id = uuid4()
    ticket = {
        "ticket_id": ticket_id,
        "user_id": user_id,
        "message": message,
        "status": TicketStatus.QUEUED,
    }
    return save_ticket(session, ticket)


def get_all_tickets(session: Session) -> list[Ticket]:
    return fetch_all_tickets(session)


def get_ticket(session: Session, ticket_id: UUID) -> Ticket:
    return fetch_ticket(session, ticket_id)


def delete_ticket(session: Session, ticket_id: UUID) -> Ticket:
    return remove_ticket(session, ticket_id)


def update_ticket(session: Session, ticket_id: UUID, params: dict) -> Ticket:
    return modify_ticket(session, ticket_id, params)


def cancel_ticket(session: Session, ticket_id: UUID) -> Ticket:
    # The Ticket first, then its Run: Triage locks them in the same order, so they can't deadlock.
    # Holding the Ticket's lock also means Triage can't add a Run before the lookup below.
    ticket = modify_ticket_status(session, ticket_id, CANCELLABLE_STATUSES, TicketStatus.CANCELLED)
    try:
        run, _ = fetch_workflow_run_by_ticket(session, ticket_id)
    except KeyError:
        # Never triaged, so there is no Run to cancel.
        return ticket
    # Raises ValueError for a finished Run; the caller rolls back the Ticket's change too.
    modify_workflow_run_status(
        session, run.run_id, CANCELLABLE_RUN_STATUSES, WorkflowRunStatus.CANCELLED
    )
    return ticket
