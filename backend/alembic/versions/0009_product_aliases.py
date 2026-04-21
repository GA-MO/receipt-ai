"""Add product_aliases table for per-item learning.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_aliases",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_text", sa.String(), nullable=False),
        sa.Column("canonical_name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("hit_count", sa.Numeric(10, 0), server_default="1", nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_product_aliases_source_text",
        "product_aliases",
        ["source_text"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_product_aliases_source_text", table_name="product_aliases")
    op.drop_table("product_aliases")
