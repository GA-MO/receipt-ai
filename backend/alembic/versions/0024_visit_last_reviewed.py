"""Add Visit.last_reviewed_at for re-open detection.

When the user marks a visit "review complete" we stamp this column. New docs
that auto-attach later have ``uploaded_at > last_reviewed_at``, which the
dashboard uses to surface the visit as "needs attention" until the user
confirms the new docs are still part of the visit.

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("visits") as batch_op:
        batch_op.add_column(sa.Column("last_reviewed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("visits") as batch_op:
        batch_op.drop_column("last_reviewed_at")
