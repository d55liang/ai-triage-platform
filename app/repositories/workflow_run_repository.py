from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.orm import WorkflowDefinitionVersion, WorkflowRun

RunWithVersion = tuple[WorkflowRun, WorkflowDefinitionVersion]


def _select_with_version() -> Select[RunWithVersion]:
    # The version is needed for definition_id, version_number and the missing inputs.
    return select(WorkflowRun, WorkflowDefinitionVersion).join(
        WorkflowDefinitionVersion, WorkflowDefinitionVersion.version_id == WorkflowRun.version_id
    )


def save_workflow_run(session: Session, run: dict) -> WorkflowRun:
    row = WorkflowRun(**run)
    session.add(row)
    session.flush()
    return row


def fetch_workflow_run(session: Session, run_id: UUID) -> RunWithVersion:
    statement = _select_with_version().where(WorkflowRun.run_id == run_id)
    row = session.execute(statement).one_or_none()
    if row is None:
        raise KeyError(run_id)
    return row


def fetch_workflow_run_by_ticket(session: Session, ticket_id: UUID) -> RunWithVersion:
    # UNIQUE (ticket_id) guarantees at most one row.
    statement = _select_with_version().where(WorkflowRun.ticket_id == ticket_id)
    row = session.execute(statement).one_or_none()
    if row is None:
        raise KeyError(ticket_id)
    return row
