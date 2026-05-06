"""Add resolved_at to catalog_gap_events + new typo_recovery_events table.

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("catalog_gap_events") as batch_op:
        batch_op.add_column(sa.Column("resolved_at", sa.DateTime(), nullable=True))
    op.create_index(
        "ix_catalog_gap_events_resolved_at",
        "catalog_gap_events",
        ["resolved_at"],
    )

    op.create_table(
        "typo_recovery_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("emitted_code", sa.String(), nullable=False),
        sa.Column("recovered_code", sa.String(), nullable=False),
        sa.Column("product_name", sa.String(), nullable=True),
        sa.Column("seen_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_typo_recovery_events_document_id", "typo_recovery_events", ["document_id"])
    op.create_index("ix_typo_recovery_events_emitted_code", "typo_recovery_events", ["emitted_code"])
    op.create_index("ix_typo_recovery_events_recovered_code", "typo_recovery_events", ["recovered_code"])
    op.create_index("ix_typo_recovery_events_seen_at", "typo_recovery_events", ["seen_at"])


def downgrade() -> None:
    op.drop_index("ix_typo_recovery_events_seen_at", table_name="typo_recovery_events")
    op.drop_index("ix_typo_recovery_events_recovered_code", table_name="typo_recovery_events")
    op.drop_index("ix_typo_recovery_events_emitted_code", table_name="typo_recovery_events")
    op.drop_index("ix_typo_recovery_events_document_id", table_name="typo_recovery_events")
    op.drop_table("typo_recovery_events")

    op.drop_index("ix_catalog_gap_events_resolved_at", table_name="catalog_gap_events")
    with op.batch_alter_table("catalog_gap_events") as batch_op:
        batch_op.drop_column("resolved_at")
