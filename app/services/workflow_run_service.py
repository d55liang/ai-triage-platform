from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models.enums import TicketStatus, WorkflowRunStatus
from app.models.orm import WorkflowDefinitionVersion, WorkflowRun
from app.repositories.ticket_repository import modify_ticket_status
from app.repositories.workflow_definition_repository import fetch_workflow_definition_version_by_id
from app.repositories.workflow_run_repository import (
    RunWithVersion,
    fetch_workflow_run,
    fetch_workflow_run_by_ticket,
    save_workflow_run,
)


def create_workflow_run(session: Session, ticket_id: UUID, version_id: UUID) -> WorkflowRun:
    # Called by Triage. The caller owns the transaction, so if any step raises,
    # the Ticket stays TRIAGING and no Run is saved.
    modify_ticket_status(session, ticket_id, [TicketStatus.TRIAGING], TicketStatus.TRIAGED)
    # A plain read is enough: a disable that commits after it is the same as disabling
    # just after the Run was created, which only stops new selections.
    definition, version = fetch_workflow_definition_version_by_id(session, version_id)
    if not definition.is_enabled:
        raise ValueError(definition.definition_id)
    status = (
        WorkflowRunStatus.AWAITING_INPUTS if version.required_inputs else WorkflowRunStatus.READY
    )
    run = {"run_id": uuid4(), "ticket_id": ticket_id, "version_id": version_id, "status": status}
    return save_workflow_run(session, run)


def get_workflow_run(session: Session, run_id: UUID) -> RunWithVersion:
    return fetch_workflow_run(session, run_id)


def get_workflow_run_for_ticket(session: Session, ticket_id: UUID) -> RunWithVersion:
    return fetch_workflow_run_by_ticket(session, ticket_id)


def get_missing_inputs(run: WorkflowRun, version: WorkflowDefinitionVersion) -> list[str]:
    # In the version's order, so the Intake Agent asks for them in the order the Admin chose.
    return [item["key"] for item in version.required_inputs if item["key"] not in run.inputs]
