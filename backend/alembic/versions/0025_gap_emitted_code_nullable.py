"""Make catalog_gap_events.emitted_code nullable.

The original gap recorder only fired when Gemini hallucinated a code that
didn't exist. We now also want to surface items where Gemini correctly
abstained (no code) but the item is in a primary product category — these
are legitimate "should we add this SKU?" signals (e.g. competitor liquor
brands seen on receipts). Such rows have no emitted code, so the column
must allow NULL.

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("catalog_gap_events") as batch_op:
        batch_op.alter_column("emitted_code", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    # Best-effort: only drop NOT NULL constraint can be re-added if no NULL rows exist.
    with op.batch_alter_table("catalog_gap_events") as batch_op:
        batch_op.alter_column("emitted_code", existing_type=sa.String(), nullable=False)
