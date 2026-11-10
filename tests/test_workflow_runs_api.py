"""Workflow Run tests. Only Triage creates Runs, so creation tests call the service directly."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import TicketStatus, WorkflowRunStatus
from app.models.orm import Ticket, WorkflowRun
from app.services.workflow_run_service import create_workflow_run

TICKET = {"user_id": "user-1", "message": "My laptop died, I need a new one"}
WORKFLOW_DEFINITION = {
    "name": "Laptop Request",
    "description": "Order a new laptop for the User",
    "confidence_threshold": "0.80",
    "steps": [{"name": "Place order", "instructions": "Order the laptop from the approved vendor"}],
    "required_inputs": [{"key": "budget", "description": "Maximum spend in USD", "type": "number"}],
    "sample_requests": ["My laptop died, I need a new one"],
}


def create_triaging_ticket(client: TestClient, session: Session) -> UUID:
    response = client.post("/api/tickets", json=TICKET)
    assert response.status_code == 201
    ticket_id = UUID(response.json()["ticket_id"])
    set_status(session, ticket_id, TicketStatus.TRIAGING)
    return ticket_id


def set_status(session: Session, ticket_id: UUID, status: TicketStatus) -> None:
    """No Triage worker exists yet, so tests set the Ticket Status directly."""
    session.get(Ticket, ticket_id).status = status
    session.flush()


def get_ticket_status(client: TestClient, ticket_id: UUID) -> str:
    response = client.get(f"/api/tickets/{ticket_id}")
    assert response.status_code == 200
    return response.json()["status"]


def create_definition(client: TestClient, **overrides: object) -> tuple[UUID, UUID]:
    """Returns the definition ID and the ID of its version 1."""
    response = client.post("/api/workflow-definitions", json={**WORKFLOW_DEFINITION, **overrides})
    assert response.status_code == 201
    definition = response.json()
    return UUID(definition["definition_id"]), UUID(definition["current_version"]["version_id"])


def create_run(session: Session, ticket_id: UUID, version_id: UUID) -> WorkflowRun:
    # The savepoint stands in for Triage's transaction: on an error it undoes this call only,
    # so a test can check that the Ticket Status change was rolled back too.
    with session.begin_nested():
        return create_workflow_run(session, ticket_id, version_id)


def get_runs(session: Session, ticket_id: UUID) -> list[WorkflowRun]:
    return list(session.scalars(select(WorkflowRun).where(WorkflowRun.ticket_id == ticket_id)))


def test_create_run(client: TestClient, session: Session) -> None:
    ticket_id = create_triaging_ticket(client, session)
    _, version_id = create_definition(client)

    run = create_run(session, ticket_id, version_id)

    assert run.ticket_id == ticket_id
    assert run.version_id == version_id
    assert run.status == WorkflowRunStatus.AWAITING_INPUTS
    assert run.inputs == {}
    assert run.created_at is not None
    assert get_ticket_status(client, ticket_id) == TicketStatus.TRIAGED


def test_create_run_without_required_inputs_is_ready(client: TestClient, session: Session) -> None:
    ticket_id = create_triaging_ticket(client, session)
    _, version_id = create_definition(client, required_inputs=[])

    run = create_run(session, ticket_id, version_id)

    assert run.status == WorkflowRunStatus.READY


@pytest.mark.parametrize(
    "status",
    [
        TicketStatus.CREATED,
        TicketStatus.QUEUED,
        TicketStatus.UNMATCHED,
        TicketStatus.FAILED,
        TicketStatus.CANCELLED,
    ],
)
def test_create_run_requires_triaging_ticket(
    client: TestClient, session: Session, status: TicketStatus
) -> None:
    ticket_id = create_triaging_ticket(client, session)
    set_status(session, ticket_id, status)
    _, version_id = create_definition(client)

    with pytest.raises(ValueError):
        create_run(session, ticket_id, version_id)

    assert get_runs(session, ticket_id) == []
    assert get_ticket_status(client, ticket_id) == status


def test_second_run_for_same_ticket_is_rejected(client: TestClient, session: Session) -> None:
    ticket_id = create_triaging_ticket(client, session)
    _, version_id = create_definition(client)
    create_run(session, ticket_id, version_id)

    # The Ticket is now TRIAGED, so the compare-and-set rejects it before UNIQUE (ticket_id) could.
    with pytest.raises(ValueError):
        create_run(session, ticket_id, version_id)

    assert len(get_runs(session, ticket_id)) == 1


def test_create_run_for_missing_ticket(client: TestClient, session: Session) -> None:
    _, version_id = create_definition(client)

    with pytest.raises(KeyError):
        create_run(session, uuid4(), version_id)


def test_create_run_for_missing_version_rolls_back(client: TestClient, session: Session) -> None:
    ticket_id = create_triaging_ticket(client, session)

    with pytest.raises(KeyError):
        create_run(session, ticket_id, uuid4())

    assert get_ticket_status(client, ticket_id) == TicketStatus.TRIAGING


def test_create_run_for_disabled_definition_rolls_back(
    client: TestClient, session: Session
) -> None:
    ticket_id = create_triaging_ticket(client, session)
    definition_id, version_id = create_definition(client)
    response = client.post(f"/api/workflow-definitions/{definition_id}/disable")
    assert response.status_code == 200

    with pytest.raises(ValueError):
        create_run(session, ticket_id, version_id)

    assert get_runs(session, ticket_id) == []
    assert get_ticket_status(client, ticket_id) == TicketStatus.TRIAGING


# Reading Runs, through HTTP only from here on.


def create_run_for_new_ticket(
    client: TestClient, session: Session, **overrides: object
) -> tuple[WorkflowRun, UUID]:
    """Returns the Run and the ID of its Workflow Definition."""
    ticket_id = create_triaging_ticket(client, session)
    definition_id, version_id = create_definition(client, **overrides)
    return create_run(session, ticket_id, version_id), definition_id


def test_get_workflow_run(client: TestClient, session: Session) -> None:
    run, definition_id = create_run_for_new_ticket(client, session)

    response = client.get(f"/api/workflow-runs/{run.run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == str(run.run_id)
    assert body["ticket_id"] == str(run.ticket_id)
    assert body["version_id"] == str(run.version_id)
    assert body["definition_id"] == str(definition_id)
    assert body["version_number"] == 1
    assert body["status"] == WorkflowRunStatus.AWAITING_INPUTS
    assert body["inputs"] == {}
    assert body["missing_inputs"] == ["budget"]
    assert "created_at" in body


def test_missing_inputs_follow_version_order(client: TestClient, session: Session) -> None:
    # Deliberately not alphabetical, so the order must come from the version.
    required_inputs = [
        {"key": "needed_by", "description": "Date the laptop is needed", "type": "date"},
        {"key": "budget", "description": "Maximum spend in USD", "type": "number"},
    ]
    run, _ = create_run_for_new_ticket(client, session, required_inputs=required_inputs)

    response = client.get(f"/api/workflow-runs/{run.run_id}")

    assert response.json()["missing_inputs"] == ["needed_by", "budget"]


def test_ready_run_has_no_missing_inputs(client: TestClient, session: Session) -> None:
    run, _ = create_run_for_new_ticket(client, session, required_inputs=[])

    response = client.get(f"/api/workflow-runs/{run.run_id}")

    assert response.json()["status"] == WorkflowRunStatus.READY
    assert response.json()["missing_inputs"] == []


def test_run_keeps_its_version_after_publish(client: TestClient, session: Session) -> None:
    run, definition_id = create_run_for_new_ticket(client, session)
    content = {key: value for key, value in WORKFLOW_DEFINITION.items() if key != "name"}
    response = client.post(
        f"/api/workflow-definitions/{definition_id}/versions",
        json={**content, "required_inputs": [], "base_version": 1},
    )
    assert response.status_code == 201

    response = client.get(f"/api/workflow-runs/{run.run_id}")

    assert response.json()["version_number"] == 1
    assert response.json()["missing_inputs"] == ["budget"]


def test_get_run_of_disabled_definition(client: TestClient, session: Session) -> None:
    run, definition_id = create_run_for_new_ticket(client, session)
    response = client.post(f"/api/workflow-definitions/{definition_id}/disable")
    assert response.status_code == 200

    response = client.get(f"/api/workflow-runs/{run.run_id}")

    assert response.status_code == 200
    assert response.json()["run_id"] == str(run.run_id)


def test_get_unknown_workflow_run_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/workflow-runs/{uuid4()}")

    assert response.status_code == 404


def test_get_workflow_run_with_malformed_id_returns_422(client: TestClient) -> None:
    response = client.get("/api/workflow-runs/not-a-uuid")

    assert response.status_code == 422


def test_get_ticket_workflow_run(client: TestClient, session: Session) -> None:
    run, _ = create_run_for_new_ticket(client, session)

    response = client.get(f"/api/tickets/{run.ticket_id}/workflow-run")

    assert response.status_code == 200
    assert response.json() == client.get(f"/api/workflow-runs/{run.run_id}").json()


def test_get_workflow_run_of_untriaged_ticket_returns_404(
    client: TestClient, session: Session
) -> None:
    ticket_id = create_triaging_ticket(client, session)

    response = client.get(f"/api/tickets/{ticket_id}/workflow-run")

    assert response.status_code == 404


def test_get_workflow_run_of_unknown_ticket_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/tickets/{uuid4()}/workflow-run")

    assert response.status_code == 404


def test_get_ticket_workflow_run_with_malformed_id_returns_422(client: TestClient) -> None:
    response = client.get("/api/tickets/not-a-uuid/workflow-run")

    assert response.status_code == 422


# Submitting Required Inputs.

ALL_TYPES = [
    {"key": "model", "description": "Laptop model", "type": "string"},
    {"key": "budget", "description": "Maximum spend in USD", "type": "number"},
    {"key": "approved", "description": "Whether the manager approved", "type": "boolean"},
    {"key": "needed_by", "description": "Date the laptop is needed", "type": "date"},
]
VALID_INPUTS = {"model": "MacBook Pro", "budget": 1500, "approved": True, "needed_by": "2026-12-01"}


def submit_inputs(client: TestClient, run_id: UUID, inputs: object) -> Response:
    return client.post(f"/api/workflow-runs/{run_id}/inputs", json={"inputs": inputs})


def get_run(client: TestClient, run_id: UUID) -> dict:
    response = client.get(f"/api/workflow-runs/{run_id}")
    assert response.status_code == 200
    return response.json()


def set_run_status(session: Session, run_id: UUID, status: WorkflowRunStatus) -> None:
    """Only submitting inputs changes a Run's status so far, so tests set the rest directly."""
    session.get(WorkflowRun, run_id).status = status
    session.flush()


def test_submit_all_inputs_makes_run_ready(client: TestClient, session: Session) -> None:
    run, _ = create_run_for_new_ticket(client, session, required_inputs=ALL_TYPES)

    response = submit_inputs(client, run.run_id, VALID_INPUTS)

    assert response.status_code == 200
    body = response.json()
    assert body["inputs"] == VALID_INPUTS
    assert body["missing_inputs"] == []
    assert body["status"] == WorkflowRunStatus.READY
    assert get_run(client, run.run_id) == body


def test_submit_partial_inputs_keeps_run_waiting(client: TestClient, session: Session) -> None:
    run, _ = create_run_for_new_ticket(client, session, required_inputs=ALL_TYPES)

    response = submit_inputs(client, run.run_id, {"budget": 1500})

    assert response.status_code == 200
    body = response.json()
    assert body["inputs"] == {"budget": 1500}
    assert body["missing_inputs"] == ["model", "approved", "needed_by"]
    assert body["status"] == WorkflowRunStatus.AWAITING_INPUTS


def test_submissions_merge_until_complete(client: TestClient, session: Session) -> None:
    run, _ = create_run_for_new_ticket(client, session, required_inputs=ALL_TYPES)

    submit_inputs(client, run.run_id, {"model": "MacBook Pro", "budget": 1500})
    response = submit_inputs(client, run.run_id, {"approved": True, "needed_by": "2026-12-01"})

    assert response.status_code == 200
    assert response.json()["inputs"] == VALID_INPUTS
    assert response.json()["status"] == WorkflowRunStatus.READY


def test_resubmitting_a_key_overwrites_it(client: TestClient, session: Session) -> None:
    run, _ = create_run_for_new_ticket(client, session, required_inputs=ALL_TYPES)
    submit_inputs(client, run.run_id, {"budget": 2000})

    response = submit_inputs(client, run.run_id, {"budget": 1500})

    assert response.status_code == 200
    assert response.json()["inputs"] == {"budget": 1500}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("model", "MacBook Pro"),
        ("budget", 1500),
        ("budget", 1499.99),
        ("budget", 0),
        ("approved", True),
        ("approved", False),
        ("needed_by", "2026-12-01"),
    ],
)
def test_submit_accepts_valid_value(
    client: TestClient, session: Session, key: str, value: object
) -> None:
    run, _ = create_run_for_new_ticket(client, session, required_inputs=ALL_TYPES)

    response = submit_inputs(client, run.run_id, {key: value})

    assert response.status_code == 200
    assert response.json()["inputs"] == {key: value}
    # A falsy value such as 0 or false still counts as supplied.
    assert key not in response.json()["missing_inputs"]


@pytest.mark.parametrize(
    "inputs",
    [
        {},
        {"unknown": "value"},
        {"budget": None},
        {"model": ""},
        {"model": 5},
        {"budget": "1500"},
        {"budget": True},
        {"approved": "yes"},
        {"approved": 1},
        {"needed_by": "next week"},
        {"needed_by": "2026-13-01"},
        {"needed_by": 20261201},
        {"budget": 1500, "unknown": "value"},
    ],
    ids=[
        "empty",
        "unknown key",
        "null",
        "empty string",
        "number for string",
        "string for number",
        "bool for number",
        "string for boolean",
        "number for boolean",
        "text for date",
        "invalid date",
        "number for date",
        "valid and unknown key",
    ],
)
def test_submit_rejects_invalid_inputs(client: TestClient, session: Session, inputs: dict) -> None:
    run, _ = create_run_for_new_ticket(client, session, required_inputs=ALL_TYPES)

    response = submit_inputs(client, run.run_id, inputs)

    assert response.status_code == 422
    assert get_run(client, run.run_id)["inputs"] == {}


@pytest.mark.parametrize("body", [{}, {"inputs": ["budget"]}, {"inputs": "budget"}])
def test_submit_rejects_malformed_body(client: TestClient, session: Session, body: dict) -> None:
    run, _ = create_run_for_new_ticket(client, session, required_inputs=ALL_TYPES)

    response = client.post(f"/api/workflow-runs/{run.run_id}/inputs", json=body)

    assert response.status_code == 422


def test_submit_after_ready_returns_409(client: TestClient, session: Session) -> None:
    run, _ = create_run_for_new_ticket(client, session, required_inputs=ALL_TYPES)
    submit_inputs(client, run.run_id, VALID_INPUTS)

    response = submit_inputs(client, run.run_id, {"budget": 1000})

    assert response.status_code == 409
    assert get_run(client, run.run_id)["inputs"] == VALID_INPUTS


@pytest.mark.parametrize(
    "status",
    [
        WorkflowRunStatus.RUNNING,
        WorkflowRunStatus.COMPLETED,
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.CANCELLED,
    ],
)
def test_submit_to_run_not_awaiting_inputs_returns_409(
    client: TestClient, session: Session, status: WorkflowRunStatus
) -> None:
    run, _ = create_run_for_new_ticket(client, session, required_inputs=ALL_TYPES)
    set_run_status(session, run.run_id, status)

    response = submit_inputs(client, run.run_id, {"budget": 1500})

    assert response.status_code == 409
    assert get_run(client, run.run_id)["inputs"] == {}


def test_submit_to_unknown_run_returns_404(client: TestClient) -> None:
    response = submit_inputs(client, uuid4(), {"budget": 1500})

    assert response.status_code == 404


def test_submit_with_malformed_run_id_returns_422(client: TestClient) -> None:
    response = client.post("/api/workflow-runs/not-a-uuid/inputs", json={"inputs": {}})

    assert response.status_code == 422


# Cancelling a Ticket with a Run.


def cancel_ticket(client: TestClient, ticket_id: UUID) -> Response:
    return client.post(f"/api/tickets/{ticket_id}/cancel")


@pytest.mark.parametrize(
    "run_status",
    [WorkflowRunStatus.AWAITING_INPUTS, WorkflowRunStatus.READY, WorkflowRunStatus.RUNNING],
)
def test_cancel_triaged_ticket_cancels_its_run(
    client: TestClient, session: Session, run_status: WorkflowRunStatus
) -> None:
    run, _ = create_run_for_new_ticket(client, session)
    set_run_status(session, run.run_id, run_status)

    response = cancel_ticket(client, run.ticket_id)

    assert response.status_code == 200
    assert response.json()["status"] == TicketStatus.CANCELLED
    assert get_ticket_status(client, run.ticket_id) == TicketStatus.CANCELLED
    assert get_run(client, run.run_id)["status"] == WorkflowRunStatus.CANCELLED


@pytest.mark.parametrize("run_status", [WorkflowRunStatus.COMPLETED, WorkflowRunStatus.FAILED])
def test_cancel_ticket_with_finished_run_returns_409(
    client: TestClient, session: Session, run_status: WorkflowRunStatus
) -> None:
    run, _ = create_run_for_new_ticket(client, session)
    set_run_status(session, run.run_id, run_status)

    response = cancel_ticket(client, run.ticket_id)

    assert response.status_code == 409
    # Both writes are undone, so neither the Ticket nor its Run changes.
    assert get_ticket_status(client, run.ticket_id) == TicketStatus.TRIAGED
    assert get_run(client, run.run_id)["status"] == run_status


def test_cancel_triaged_ticket_twice_succeeds(client: TestClient, session: Session) -> None:
    run, _ = create_run_for_new_ticket(client, session)

    response_first = cancel_ticket(client, run.ticket_id)
    response_second = cancel_ticket(client, run.ticket_id)

    assert response_first.status_code == 200
    assert response_second.status_code == 200
    assert response_second.json() == response_first.json()
    assert get_run(client, run.run_id)["status"] == WorkflowRunStatus.CANCELLED


def test_cancelled_run_rejects_inputs(client: TestClient, session: Session) -> None:
    run, _ = create_run_for_new_ticket(client, session)
    cancel_ticket(client, run.ticket_id)

    response = submit_inputs(client, run.run_id, {"budget": 1500})

    assert response.status_code == 409
    assert get_run(client, run.run_id)["inputs"] == {}


# Deleting a Ticket with a Run.


@pytest.mark.parametrize(
    "run_status", [WorkflowRunStatus.AWAITING_INPUTS, WorkflowRunStatus.CANCELLED]
)
def test_delete_ticket_with_run_returns_409(
    client: TestClient, session: Session, run_status: WorkflowRunStatus
) -> None:
    # Even a cancelled Run keeps its Ticket: nothing a Run references is deleted.
    run, _ = create_run_for_new_ticket(client, session)
    set_run_status(session, run.run_id, run_status)

    response = client.delete(f"/api/tickets/{run.ticket_id}")

    assert response.status_code == 409
    assert get_ticket_status(client, run.ticket_id) == TicketStatus.TRIAGED
    assert get_run(client, run.run_id)["status"] == run_status
