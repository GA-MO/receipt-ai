"""Add catalog_gap_events for tracking Gemini-emitted unknown product codes.

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalog_gap_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("emitted_code", sa.String(), nullable=False),
        sa.Column("product_name", sa.String(), nullable=True),
        sa.Column("product_name_raw", sa.String(), nullable=True),
        sa.Column("seen_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_catalog_gap_events_document_id", "catalog_gap_events", ["document_id"]
    )
    op.create_index(
        "ix_catalog_gap_events_emitted_code", "catalog_gap_events", ["emitted_code"]
    )
    op.create_index("ix_catalog_gap_events_seen_at", "catalog_gap_events", ["seen_at"])


def downgrade() -> None:
    op.drop_index("ix_catalog_gap_events_seen_at", table_name="catalog_gap_events")
    op.drop_index("ix_catalog_gap_events_emitted_code", table_name="catalog_gap_events")
    op.drop_index("ix_catalog_gap_events_document_id", table_name="catalog_gap_events")
    op.drop_table("catalog_gap_events")
