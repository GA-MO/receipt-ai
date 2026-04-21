"""Add document_items.product_name_raw for alias-source stability.

The new column stores exactly what Gemini OCR'd from the receipt before any
PRODUCT_CATALOG normalization. We backfill from ``product_name_normalized``
for existing rows (best-effort — raw signal wasn't captured previously).

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("document_items") as batch_op:
        batch_op.add_column(sa.Column("product_name_raw", sa.String(), nullable=True))
    op.execute(
        "UPDATE document_items SET product_name_raw = product_name_normalized "
        "WHERE product_name_raw IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("document_items") as batch_op:
        batch_op.drop_column("product_name_raw")
