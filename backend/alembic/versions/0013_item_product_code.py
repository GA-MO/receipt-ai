"""Add document_items.product_code (Singha Online SKU link).

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("document_items") as batch_op:
        batch_op.add_column(sa.Column("product_code", sa.String(), nullable=True))
    op.create_index(
        "ix_document_items_product_code",
        "document_items",
        ["product_code"],
    )
    # Backfill: match item names to catalog canonicals (case/space insensitive).
    op.execute(
        """
        UPDATE document_items
        SET product_code = (
            SELECT p.code FROM products p
            WHERE p.active = 1
              AND LOWER(TRIM(p.canonical_name)) = LOWER(TRIM(document_items.product_name_normalized))
            LIMIT 1
        )
        WHERE product_code IS NULL
          AND product_name_normalized IS NOT NULL
          AND product_name_normalized <> ''
        """
    )


def downgrade() -> None:
    op.drop_index("ix_document_items_product_code", table_name="document_items")
    with op.batch_alter_table("document_items") as batch_op:
        batch_op.drop_column("product_code")
