"""Add merchant_aliases table for learning from user corrections.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "merchant_aliases",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_text", sa.String(), nullable=False),
        sa.Column("canonical_name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("hit_count", sa.Numeric(10, 0), server_default="1", nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_merchant_aliases_source_text",
        "merchant_aliases",
        ["source_text"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_merchant_aliases_source_text", table_name="merchant_aliases")
    op.drop_table("merchant_aliases")
