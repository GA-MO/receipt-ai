"""Add category column to documents

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("category", sa.String(), nullable=True))
    op.create_index("ix_documents_category", "documents", ["category"])


def downgrade() -> None:
    op.drop_index("ix_documents_category", table_name="documents")
    op.drop_column("documents", "category")
