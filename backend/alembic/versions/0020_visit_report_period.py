"""Add visits.report_period (YYYY-MM) for the reporting month a visit covers.

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("visits") as batch_op:
        batch_op.add_column(sa.Column("report_period", sa.String(), nullable=True))
    op.create_index("ix_visits_report_period", "visits", ["report_period"])


def downgrade() -> None:
    op.drop_index("ix_visits_report_period", table_name="visits")
    with op.batch_alter_table("visits") as batch_op:
        batch_op.drop_column("report_period")
