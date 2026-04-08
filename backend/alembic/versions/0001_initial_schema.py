"""Initial schema - documents and document_items tables

Revision ID: 0001
Revises:
Create Date: 2026-04-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("file_type", sa.String(), server_default="image"),
        sa.Column("file_hash", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default="pending"),
        sa.Column("uploaded_at", sa.DateTime(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column("raw_extraction", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), server_default=sa.text("1")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("merchant_name", sa.String(), nullable=True),
        sa.Column("document_number", sa.String(), nullable=True),
        sa.Column("document_date", sa.String(), nullable=True),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=True),
        sa.Column("discount", sa.Numeric(12, 2), nullable=True),
        sa.Column("vat", sa.Numeric(12, 2), nullable=True),
        sa.Column("grand_total", sa.Numeric(12, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_documents_file_hash", "documents", ["file_hash"])
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_document_number", "documents", ["document_number"])

    op.create_table(
        "document_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column("product_name_raw", sa.String(), nullable=True),
        sa.Column("product_name_normalized", sa.String(), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_table("document_items")
    op.drop_index("ix_documents_document_number", table_name="documents")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index("ix_documents_file_hash", table_name="documents")
    op.drop_table("documents")
