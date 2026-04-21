"""Add document_events audit-log table.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False, server_default="user"),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_document_events_document_id", "document_events", ["document_id"])
    op.create_index("ix_document_events_event_type", "document_events", ["event_type"])
    op.create_index("ix_document_events_created_at", "document_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_document_events_created_at", table_name="document_events")
    op.drop_index("ix_document_events_event_type", table_name="document_events")
    op.drop_index("ix_document_events_document_id", table_name="document_events")
    op.drop_table("document_events")
