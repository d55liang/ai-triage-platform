from uuid import UUID

from sqlalchemy import Select, literal, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.models.enums import WorkflowRunStatus
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


def _modify_if_status(
    session: Session, run_id: UUID, expected: list[WorkflowRunStatus], values: dict
) -> WorkflowRun:
    # Compare-and-set: checking the status in the UPDATE stops a concurrent change being overwritten.
    run = session.scalars(
        update(WorkflowRun)
        .where(WorkflowRun.run_id == run_id, WorkflowRun.status.in_(expected))
        .values(**values)
        .returning(WorkflowRun)
    ).one_or_none()
    if run is None:
        # No row matched: fetch_workflow_run raises KeyError if it's missing, so past it the
        # status is the problem.
        fetch_workflow_run(session, run_id)
        raise ValueError(run_id)
    return run


def modify_workflow_run_inputs(
    session: Session, run_id: UUID, expected: list[WorkflowRunStatus], inputs: dict
) -> WorkflowRun:
    # Postgres merges with || against the committed row, so a concurrent submission's
    # values are kept; a key submitted again is overwritten.
    merged = WorkflowRun.inputs.op("||")(literal(inputs, JSONB))
    return _modify_if_status(session, run_id, expected, {"inputs": merged})


def modify_workflow_run_status(
    session: Session, run_id: UUID, expected: list[WorkflowRunStatus], status: WorkflowRunStatus
) -> WorkflowRun:
    return _modify_if_status(session, run_id, expected, {"status": status})
