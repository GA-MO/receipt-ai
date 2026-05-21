"""Drop price and fraud columns the pivot no longer uses.

The visit-centric workflow tracks ``product × quantity`` per store-month;
prices and fraud signals are out of scope. Drop:

- ``documents.subtotal``
- ``documents.discount``
- ``documents.vat``
- ``documents.grand_total``
- ``documents.fraud_flags``
- ``document_items.unit_price``
- ``document_items.line_total``

This migration is destructive — historical numeric values cannot be
recovered after a downgrade.

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_column("subtotal")
        batch_op.drop_column("discount")
        batch_op.drop_column("vat")
        batch_op.drop_column("grand_total")
        batch_op.drop_column("fraud_flags")

    with op.batch_alter_table("document_items") as batch_op:
        batch_op.drop_column("unit_price")
        batch_op.drop_column("line_total")


def downgrade() -> None:
    with op.batch_alter_table("document_items") as batch_op:
        batch_op.add_column(sa.Column("line_total", sa.Numeric(12, 2), nullable=True))
        batch_op.add_column(sa.Column("unit_price", sa.Numeric(12, 2), nullable=True))

    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("fraud_flags", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("grand_total", sa.Numeric(12, 2), nullable=True))
        batch_op.add_column(sa.Column("vat", sa.Numeric(12, 2), nullable=True))
        batch_op.add_column(sa.Column("discount", sa.Numeric(12, 2), nullable=True))
        batch_op.add_column(sa.Column("subtotal", sa.Numeric(12, 2), nullable=True))
