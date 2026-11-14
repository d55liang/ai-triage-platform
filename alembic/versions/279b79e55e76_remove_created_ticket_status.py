"""remove created ticket status

Revision ID: 279b79e55e76
Revises: 14ce19121a96
Create Date: 2026-11-13 20:22:03.101952

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '279b79e55e76'
down_revision: Union[str, Sequence[str], None] = '14ce19121a96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(op.f("ck_tickets_ticket_status"), "tickets", type_="check")
    op.create_check_constraint(op.f("ck_tickets_ticket_status"), "tickets", "status IN ('QUEUED', 'TRIAGING', 'TRIAGED', 'UNMATCHED', 'FAILED', 'CANCELLED')")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("ck_tickets_ticket_status"), "tickets", type_="check")
    op.create_check_constraint(op.f("ck_tickets_ticket_status"), "tickets", "status IN ('CREATED', 'QUEUED', 'TRIAGING', 'TRIAGED', 'UNMATCHED', 'FAILED', 'CANCELLED')")
