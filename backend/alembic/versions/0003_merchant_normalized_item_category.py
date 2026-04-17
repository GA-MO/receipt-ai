"""Add merchant_normalized to documents and category to document_items

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("merchant_normalized", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_documents_merchant_normalized",
        "documents",
        ["merchant_normalized"],
    )

    op.add_column(
        "document_items",
        sa.Column("category", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_document_items_category",
        "document_items",
        ["category"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_items_category", table_name="document_items")
    op.drop_column("document_items", "category")

    op.drop_index("ix_documents_merchant_normalized", table_name="documents")
    op.drop_column("documents", "merchant_normalized")
