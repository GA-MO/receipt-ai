"""Drop document_items.product_name_raw

``product_name_normalized`` becomes the single editable product name.
Raw source text is still recoverable from ``documents.raw_extraction`` (the
full JSON payload returned by Gemini).

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfill: keep any raw value that differs from normalized, in case the
    # normalized is blank, so we don't lose the displayed text.
    op.execute(
        """
        UPDATE document_items
        SET product_name_normalized = product_name_raw
        WHERE (product_name_normalized IS NULL OR product_name_normalized = '')
          AND product_name_raw IS NOT NULL
          AND product_name_raw <> ''
        """
    )
    with op.batch_alter_table("document_items") as batch_op:
        batch_op.drop_column("product_name_raw")


def downgrade() -> None:
    with op.batch_alter_table("document_items") as batch_op:
        batch_op.add_column(sa.Column("product_name_raw", sa.String(), nullable=True))
