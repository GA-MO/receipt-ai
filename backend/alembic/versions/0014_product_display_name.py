"""Add products.display_name (smart short name) column.

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(sa.Column("display_name", sa.String(), nullable=True))
    op.create_index("ix_products_display_name", "products", ["display_name"])


def downgrade() -> None:
    op.drop_index("ix_products_display_name", table_name="products")
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_column("display_name")
