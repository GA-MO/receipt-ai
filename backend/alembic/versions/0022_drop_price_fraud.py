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


def _drop_if_present(table: str, columns: list[str]) -> None:
    """Drop only the columns this database actually has.

    These columns predate the migration chain — they were created by
    ``Base.metadata.create_all`` in development, never by a revision. A database
    built purely from migrations therefore never had them, and an unconditional
    drop makes ``alembic upgrade head`` fail on every fresh deploy.
    """
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
    present = [c for c in columns if c in existing]
    if not present:
        return
    with op.batch_alter_table(table) as batch_op:
        for column in present:
            batch_op.drop_column(column)


def upgrade() -> None:
    _drop_if_present(
        "documents", ["subtotal", "discount", "vat", "grand_total", "fraud_flags"]
    )
    _drop_if_present("document_items", ["unit_price", "line_total"])


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
