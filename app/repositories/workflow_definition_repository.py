from uuid import UUID

from sqlalchemy import Select, and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.orm import WorkflowDefinition, WorkflowDefinitionVersion

ALLOWED_COLUMNS = ["name"]

DefinitionWithVersion = tuple[WorkflowDefinition, WorkflowDefinitionVersion]


def _select_with_current_version() -> Select[DefinitionWithVersion]:
    # The current version is the highest version_number; there is no pointer to keep in sync.
    latest = (
        select(
            WorkflowDefinitionVersion.definition_id,
            func.max(WorkflowDefinitionVersion.version_number).label("version_number"),
        )
        .group_by(WorkflowDefinitionVersion.definition_id)
        .subquery()
    )
    return (
        select(WorkflowDefinition, WorkflowDefinitionVersion)
        .join(latest, latest.c.definition_id == WorkflowDefinition.definition_id)
        .join(
            WorkflowDefinitionVersion,
            and_(
                WorkflowDefinitionVersion.definition_id == latest.c.definition_id,
                WorkflowDefinitionVersion.version_number == latest.c.version_number,
            ),
        )
    )


def _flush_unique_name(session: Session, name: str) -> None:
    # Flushing here, not at commit, turns a duplicate name into a 409 instead of a 500.
    try:
        session.flush()
    except IntegrityError as e:
        raise ValueError(name) from e


def save_workflow_definition(session: Session, definition: dict) -> WorkflowDefinition:
    row = WorkflowDefinition(**definition)
    session.add(row)
    _flush_unique_name(session, row.name)
    return row


def save_workflow_definition_version(session: Session, version: dict) -> WorkflowDefinitionVersion:
    row = WorkflowDefinitionVersion(**version)
    session.add(row)
    # A publish that raced past the base_version check collides on
    # UNIQUE (definition_id, version_number).
    try:
        session.flush()
    except IntegrityError as e:
        # Turns a version collision into a 409 instead of a 500.
        raise ValueError(version["version_number"]) from e
    return row


def fetch_all_workflow_definitions(
    session: Session, limit: int, offset: int
) -> list[DefinitionWithVersion]:
    # definition_id breaks created_at ties, so pages don't overlap.
    statement = (
        _select_with_current_version()
        .order_by(WorkflowDefinition.created_at, WorkflowDefinition.definition_id)
        .limit(limit)
        .offset(offset)
    )
    return list(session.execute(statement))


def fetch_workflow_definition(session: Session, definition_id: UUID) -> DefinitionWithVersion:
    statement = _select_with_current_version().where(
        WorkflowDefinition.definition_id == definition_id
    )
    row = session.execute(statement).one_or_none()
    if row is None:
        raise KeyError(definition_id)
    return row


def fetch_workflow_definition_version(
    session: Session, definition_id: UUID, version_number: int
) -> WorkflowDefinitionVersion:
    version = session.scalars(
        select(WorkflowDefinitionVersion).where(
            WorkflowDefinitionVersion.definition_id == definition_id,
            WorkflowDefinitionVersion.version_number == version_number,
        )
    ).one_or_none()
    if version is None:
        raise KeyError((definition_id, version_number))
    return version


def modify_workflow_definition(
    session: Session, definition_id: UUID, params: dict
) -> WorkflowDefinition:
    definition = session.get(WorkflowDefinition, definition_id)
    if definition is None:
        raise KeyError(definition_id)
    columns = [column for column in params if column in ALLOWED_COLUMNS]
    for column in columns:
        setattr(definition, column, params[column])
    _flush_unique_name(session, definition.name)
    return definition


def modify_workflow_definition_enabled(
    session: Session, definition_id: UUID, is_enabled: bool
) -> WorkflowDefinition:
    # A plain set, not a compare-and-set: every starting state is allowed, so last commit wins.
    definition = session.get(WorkflowDefinition, definition_id)
    if definition is None:
        raise KeyError(definition_id)
    definition.is_enabled = is_enabled
    session.flush()
    return definition
