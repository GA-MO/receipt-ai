"""Add products table (catalog from singhaonline.com).

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("code", sa.String(), nullable=True),
        sa.Column("canonical_name", sa.String(), nullable=False),
        sa.Column("name_en", sa.String(), nullable=True),
        sa.Column("brand_th", sa.String(), nullable=True),
        sa.Column("brand_en", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("sub_category", sa.String(), nullable=True),
        sa.Column("size", sa.String(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("aliases", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("product_type", sa.String(), nullable=True),
        sa.Column("source", sa.String(), server_default="singhaonline"),
        sa.Column("active", sa.Boolean(), server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_products_code", "products", ["code"], unique=True)
    op.create_index("ix_products_canonical_name", "products", ["canonical_name"], unique=True)
    op.create_index("ix_products_brand_th", "products", ["brand_th"])
    op.create_index("ix_products_category", "products", ["category"])
    op.create_index("ix_products_active", "products", ["active"])


def downgrade() -> None:
    op.drop_index("ix_products_active", table_name="products")
    op.drop_index("ix_products_category", table_name="products")
    op.drop_index("ix_products_brand_th", table_name="products")
    op.drop_index("ix_products_canonical_name", table_name="products")
    op.drop_index("ix_products_code", table_name="products")
    op.drop_table("products")
