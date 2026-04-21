"""Add products.manufacturer for brand-share analytics.

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(sa.Column("manufacturer", sa.String(), nullable=True))
    op.create_index("ix_products_manufacturer", "products", ["manufacturer"])
    # Default every existing row to Boonrawd; the next seed pass will
    # overwrite competitor SKUs with their real manufacturer.
    op.execute("UPDATE products SET manufacturer = 'Boonrawd' WHERE manufacturer IS NULL")


def downgrade() -> None:
    op.drop_index("ix_products_manufacturer", table_name="products")
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_column("manufacturer")
