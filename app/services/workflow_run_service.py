import json
from datetime import date
from typing import Annotated, TypedDict
from uuid import UUID, uuid4

from pydantic import ConfigDict, Field, TypeAdapter, with_config
from sqlalchemy.orm import Session

from app.models.enums import RequiredInputType, TicketStatus, WorkflowRunStatus
from app.models.orm import WorkflowDefinitionVersion, WorkflowRun
from app.repositories.ticket_repository import modify_ticket_status
from app.repositories.workflow_definition_repository import fetch_workflow_definition_version_by_id
from app.repositories.workflow_run_repository import (
    RunWithVersion,
    fetch_workflow_run,
    fetch_workflow_run_by_ticket,
    modify_workflow_run_inputs,
    modify_workflow_run_status,
    save_workflow_run,
)

INPUT_TYPES: dict[RequiredInputType, object] = {
    RequiredInputType.STRING: Annotated[str, Field(min_length=1)],
    RequiredInputType.NUMBER: float,
    RequiredInputType.BOOLEAN: bool,
    RequiredInputType.DATE: date,
}


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


def _validate_inputs(
    version: WorkflowDefinitionVersion, inputs: dict[str, object]
) -> dict[str, str | float | bool]:
    # A TypedDict, not create_model: valid keys such as model_dump would clash with BaseModel.
    # total=False allows partial submissions; values have no "| None", so null is rejected.
    # Strict, so "1500" is not a number and true is not a number either.
    fields = {item["key"]: INPUT_TYPES[item["type"]] for item in version.required_inputs}
    schema = with_config(ConfigDict(strict=True, extra="forbid"))(
        TypedDict("RequiredInputs", fields, total=False)
    )
    adapter = TypeAdapter(schema)
    # JSON mode, because strict mode only accepts a date given as a string when parsing JSON.
    validated = adapter.validate_json(json.dumps(inputs))
    return adapter.dump_python(validated, mode="json")


def submit_workflow_run_inputs(
    session: Session, run_id: UUID, inputs: dict[str, object]
) -> RunWithVersion:
    # Raises KeyError for an unknown Run, ValidationError for invalid values, and ValueError
    # when the Run is not AWAITING_INPUTS.
    run, version = fetch_workflow_run(session, run_id)
    validated = _validate_inputs(version, inputs)
    # One UPDATE merges the values while the Run is AWAITING_INPUTS, so concurrent
    # submissions can't lose each other's values.
    run = modify_workflow_run_inputs(
        session, run_id, [WorkflowRunStatus.AWAITING_INPUTS], validated
    )
    # The UPDATE keeps the row locked until commit, so this sees every merged value.
    if not get_missing_inputs(run, version):
        run = modify_workflow_run_status(
            session, run_id, [WorkflowRunStatus.AWAITING_INPUTS], WorkflowRunStatus.READY
        )
    return run, version
