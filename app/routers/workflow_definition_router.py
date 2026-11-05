from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query

from app.dependencies import SessionDep
from app.models.orm import WorkflowDefinition, WorkflowDefinitionVersion
from app.models.request import CreateWorkflowDefinitionRequest, UpdateWorkflowDefinitionRequest
from app.models.response import (
    WorkflowDefinitionItem,
    WorkflowDefinitionsResponse,
    WorkflowDefinitionVersionItem,
)
from app.services.workflow_definition_service import (
    create_workflow_definition,
    get_all_workflow_definitions,
    get_workflow_definition,
    get_workflow_definition_version,
    update_workflow_definition,
)

workflow_definition_router = APIRouter(
    prefix="/workflow-definitions", tags=["workflow-definitions"]
)


def _to_item(
    definition: WorkflowDefinition, version: WorkflowDefinitionVersion
) -> WorkflowDefinitionItem:
    # Identity and content are separate rows, so the response joins them here.
    return WorkflowDefinitionItem(
        definition_id=definition.definition_id,
        name=definition.name,
        is_enabled=definition.is_enabled,
        created_at=definition.created_at,
        current_version=WorkflowDefinitionVersionItem.model_validate(version),
    )


@workflow_definition_router.post("", response_model=WorkflowDefinitionItem, status_code=201)
def create_workflow_definition_api(
    request: CreateWorkflowDefinitionRequest, session: SessionDep
) -> WorkflowDefinitionItem:
    try:
        definition, version = create_workflow_definition(session, request.model_dump())
    except ValueError as e:
        raise HTTPException(
            status_code=409, detail=f"Create failed: name {request.name!r} is already taken."
        ) from e
    return _to_item(definition, version)


@workflow_definition_router.get("", response_model=WorkflowDefinitionsResponse, status_code=200)
def get_all_workflow_definitions_api(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkflowDefinitionsResponse:
    pairs = get_all_workflow_definitions(session, limit=limit, offset=offset)
    return WorkflowDefinitionsResponse(data=[_to_item(d, v) for d, v in pairs])


@workflow_definition_router.get(
    "/{definition_id}", response_model=WorkflowDefinitionItem, status_code=200
)
def get_workflow_definition_api(definition_id: UUID, session: SessionDep) -> WorkflowDefinitionItem:
    try:
        definition, version = get_workflow_definition(session, definition_id)
    except KeyError as e:
        raise HTTPException(
            status_code=404, detail=f"Workflow definition {definition_id} not found."
        ) from e
    return _to_item(definition, version)


@workflow_definition_router.patch(
    "/{definition_id}", response_model=WorkflowDefinitionItem, status_code=200
)
def update_workflow_definition_api(
    definition_id: UUID, request: UpdateWorkflowDefinitionRequest, session: SessionDep
) -> WorkflowDefinitionItem:
    request_dict = request.model_dump(exclude_unset=True)
    try:
        definition, version = update_workflow_definition(session, definition_id, request_dict)
    except KeyError as e:
        raise HTTPException(
            status_code=404, detail=f"Update failed: workflow definition {definition_id} not found."
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=409, detail=f"Update failed: name {request.name!r} is already taken."
        ) from e
    return _to_item(definition, version)


@workflow_definition_router.get(
    "/{definition_id}/versions/{version_number}",
    response_model=WorkflowDefinitionVersionItem,
    status_code=200,
)
def get_workflow_definition_version_api(
    definition_id: UUID,
    version_number: Annotated[int, Path(ge=1)],
    session: SessionDep,
) -> WorkflowDefinitionVersion:
    try:
        version = get_workflow_definition_version(session, definition_id, version_number)
    except KeyError as e:
        raise HTTPException(
            status_code=404,
            detail=f"Version {version_number} of workflow definition {definition_id} not found.",
        ) from e
    return version
