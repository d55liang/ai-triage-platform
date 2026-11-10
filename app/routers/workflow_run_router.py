from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep
from app.models.orm import WorkflowDefinitionVersion, WorkflowRun
from app.models.response import WorkflowRunItem
from app.services.workflow_run_service import get_missing_inputs, get_workflow_run

workflow_run_router = APIRouter(prefix="/workflow-runs", tags=["workflow-runs"])


def to_workflow_run_item(run: WorkflowRun, version: WorkflowDefinitionVersion) -> WorkflowRunItem:
    # Public because ticket_router returns a Ticket's Run in the same shape.
    return WorkflowRunItem(
        run_id=run.run_id,
        ticket_id=run.ticket_id,
        version_id=run.version_id,
        definition_id=version.definition_id,
        version_number=version.version_number,
        status=run.status,
        inputs=run.inputs,
        missing_inputs=get_missing_inputs(run, version),
        created_at=run.created_at,
    )


@workflow_run_router.get("/{run_id}", response_model=WorkflowRunItem, status_code=200)
def get_workflow_run_api(run_id: UUID, session: SessionDep) -> WorkflowRunItem:
    try:
        run, version = get_workflow_run(session, run_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Workflow run {run_id} not found.") from e
    return to_workflow_run_item(run, version)
