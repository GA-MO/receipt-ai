"""Add document_items.review_reason — why a line is flagged, shown on the row.

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("document_items") as batch:
        batch.add_column(sa.Column("review_reason", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("document_items") as batch:
        batch.drop_column("review_reason")
