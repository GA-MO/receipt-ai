"""Add auto_attach_visit flag for the bulk inbox flow.

When the user uploads via the inbox ("dump a day of receipts"), the worker
must skip the implicit ``ensure_visit_for_doc`` call so the docs sit
unattached until the user confirms grouping in the UI.

Default is TRUE so existing single-doc upload flows keep auto-attaching.

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(
            sa.Column(
                "auto_attach_visit",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_column("auto_attach_visit")
