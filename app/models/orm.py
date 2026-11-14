import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import OutboxEventType, TicketStatus, WorkflowRunStatus


class Ticket(Base):
    __tablename__ = "tickets"

    ticket_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[str]
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[TicketStatus] = mapped_column(
        Enum(
            TicketStatus, name="ticket_status", native_enum=False, create_constraint=True, length=20
        )
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowDefinition(Base):
    """Identity only; content lives in immutable versions."""

    __tablename__ = "workflow_definitions"

    definition_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    is_enabled: Mapped[bool] = mapped_column(server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowDefinitionVersion(Base):
    """Never updated after insert; editing a definition adds a version."""

    __tablename__ = "workflow_definition_versions"
    __table_args__ = (
        # Named explicitly: the "uq" convention only includes the first column.
        # Its index also serves the definition_id foreign key.
        UniqueConstraint(
            "definition_id",
            "version_number",
            name="uq_workflow_definition_versions_definition_id_version_number",
        ),
        CheckConstraint(
            "confidence_threshold > 0 AND confidence_threshold <= 1",
            name="confidence_threshold_range",
        ),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    # Named explicitly: the "fk" convention exceeds Postgres's 63-character limit here.
    definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "workflow_definitions.definition_id",
            ondelete="RESTRICT",
            name="fk_workflow_definition_versions_definition_id",
        )
    )
    version_number: Mapped[int]
    description: Mapped[str] = mapped_column(Text)
    confidence_threshold: Mapped[Decimal] = mapped_column(Numeric(3, 2))
    # Shapes are validated by Pydantic at the API.
    steps: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    required_inputs: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    sample_requests: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowRun(Base):
    """One per Ticket, pinned to the Workflow Definition Version Triage selected."""

    __tablename__ = "workflow_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    # The unique constraint's index also serves the foreign key.
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.ticket_id", ondelete="RESTRICT"), unique=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_definition_versions.version_id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[WorkflowRunStatus] = mapped_column(
        Enum(
            WorkflowRunStatus,
            name="workflow_run_status",
            native_enum=False,
            create_constraint=True,
            length=20,
        )
    )
    # Required Input values by key; validated against the version by the service.
    inputs: Mapped[dict[str, str | float | bool]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxEvent(Base):
    """An event saved in the same transaction as the change it announces; the relay publishes it.

    No foreign key to the subject: events of any type share the table, and published rows are
    pruned on their own schedule.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        # The relay reads only unpublished rows, oldest first; published rows drop out of the index.
        Index(
            "ix_outbox_events_unpublished",
            "created_at",
            postgresql_where=text("published_at IS NULL"),
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    event_type: Mapped[OutboxEventType] = mapped_column(
        Enum(
            OutboxEventType,
            name="outbox_event_type",
            native_enum=False,
            create_constraint=True,
            length=50,
            # Store "ticket.queued", not the member name "TICKET_QUEUED".
            values_callable=lambda members: [member.value for member in members],
        )
    )
    payload: Mapped[dict[str, str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
