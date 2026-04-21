"""Add documents.deleted_at for soft-delete / recycle bin.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.create_index(
        "ix_documents_deleted_at",
        "documents",
        ["deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_deleted_at", table_name="documents")
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_column("deleted_at")
