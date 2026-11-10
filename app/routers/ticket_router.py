from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep
from app.models.orm import Ticket
from app.models.request import CreateTicketRequest, UpdateTicketRequest
from app.models.response import TicketItem, TicketsResponse, WorkflowRunItem
from app.routers.workflow_run_router import to_workflow_run_item
from app.services.ticket_service import (
    cancel_ticket,
    create_ticket,
    delete_ticket,
    get_all_tickets,
    get_ticket,
    update_ticket,
)
from app.services.workflow_run_service import get_workflow_run_for_ticket

ticket_router = APIRouter(prefix="/tickets", tags=["tickets"])


@ticket_router.post("", response_model=TicketItem, status_code=201)
def create_ticket_api(request: CreateTicketRequest, session: SessionDep) -> Ticket:
    return create_ticket(session, user_id=request.user_id, message=request.message)


@ticket_router.get("", response_model=TicketsResponse, status_code=200)
def get_all_tickets_api(session: SessionDep) -> dict[str, list[Ticket]]:
    return {"data": get_all_tickets(session)}


@ticket_router.get("/{ticket_id}", response_model=TicketItem, status_code=200)
def get_ticket_api(ticket_id: UUID, session: SessionDep) -> Ticket:
    try:
        ticket = get_ticket(session, ticket_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found.") from e
    return ticket


@ticket_router.delete("/{ticket_id}", response_model=TicketItem, status_code=200)
def delete_ticket_api(ticket_id: UUID, session: SessionDep) -> Ticket:
    try:
        ticket = delete_ticket(session, ticket_id)
    except KeyError as e:
        raise HTTPException(
            status_code=404, detail=f"Delete failed: ticket {ticket_id} not found."
        ) from e
    return ticket


@ticket_router.patch("/{ticket_id}", response_model=TicketItem, status_code=200)
def update_ticket_api(ticket_id: UUID, request: UpdateTicketRequest, session: SessionDep) -> Ticket:
    request_dict = request.model_dump(exclude_unset=True)
    try:
        ticket = update_ticket(session, ticket_id, request_dict)
    except KeyError as e:
        raise HTTPException(
            status_code=404, detail=f"Update failed: ticket {ticket_id} not found."
        ) from e
    return ticket


@ticket_router.post("/{ticket_id}/cancel", response_model=TicketItem, status_code=200)
def cancel_ticket_api(ticket_id: UUID, session: SessionDep) -> Ticket:
    try:
        ticket = cancel_ticket(session, ticket_id)
    except KeyError as e:
        raise HTTPException(
            status_code=404, detail=f"Cancel failed: ticket {ticket_id} not found."
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=409, detail=f"Cancel failed: ticket {ticket_id} cannot be cancelled."
        ) from e
    return ticket


@ticket_router.get("/{ticket_id}/workflow-run", response_model=WorkflowRunItem, status_code=200)
def get_ticket_workflow_run_api(ticket_id: UUID, session: SessionDep) -> WorkflowRunItem:
    try:
        run, version = get_workflow_run_for_ticket(session, ticket_id)
    except KeyError as e:
        # One 404 whether the Ticket is missing or has no Run yet.
        raise HTTPException(
            status_code=404, detail=f"No workflow run found for ticket {ticket_id}."
        ) from e
    return to_workflow_run_item(run, version)
