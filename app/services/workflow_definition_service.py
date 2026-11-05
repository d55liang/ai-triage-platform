from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models.orm import WorkflowDefinitionVersion
from app.repositories.workflow_definition_repository import (
    DefinitionWithVersion,
    fetch_all_workflow_definitions,
    fetch_workflow_definition,
    fetch_workflow_definition_version,
    modify_workflow_definition,
    save_workflow_definition,
    save_workflow_definition_version,
)


def create_workflow_definition(session: Session, params: dict) -> DefinitionWithVersion:
    # A definition never exists without a version, so both are saved in the caller's transaction.
    definition_id = uuid4()
    content = {key: value for key, value in params.items() if key != "name"}
    definition = save_workflow_definition(
        session, {"definition_id": definition_id, "name": params["name"]}
    )
    version = save_workflow_definition_version(
        session,
        {"version_id": uuid4(), "definition_id": definition_id, "version_number": 1, **content},
    )
    return definition, version


def get_all_workflow_definitions(
    session: Session, limit: int, offset: int
) -> list[DefinitionWithVersion]:
    return fetch_all_workflow_definitions(session, limit=limit, offset=offset)


def get_workflow_definition(session: Session, definition_id: UUID) -> DefinitionWithVersion:
    return fetch_workflow_definition(session, definition_id)


def update_workflow_definition(
    session: Session, definition_id: UUID, params: dict
) -> DefinitionWithVersion:
    modify_workflow_definition(session, definition_id, params)
    return fetch_workflow_definition(session, definition_id)


def get_workflow_definition_version(
    session: Session, definition_id: UUID, version_number: int
) -> WorkflowDefinitionVersion:
    return fetch_workflow_definition_version(session, definition_id, version_number)
