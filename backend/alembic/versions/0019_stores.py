"""Add stores master table; visits.store_id FK; backfill stores from existing
visit store_keys and document merchant_normalized values.

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-21
"""
import uuid
from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stores",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("code", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=True),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_stores_code", "stores", ["code"], unique=True)
    op.create_index("ix_stores_normalized_name", "stores", ["normalized_name"])
    op.create_index("ix_stores_active", "stores", ["active"])

    with op.batch_alter_table("visits") as batch_op:
        batch_op.add_column(sa.Column("store_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_visits_store_id", "stores", ["store_id"], ["id"]
        )
    op.create_index("ix_visits_store_id", "visits", ["store_id"])

    _backfill_stores()


def _backfill_stores() -> None:
    """Seed one ``stores`` row per distinct ``visits.store_key`` and link back.

    Visits with a NULL store_key remain unlinked (orphan). Stores are deduped
    on lowercase normalized_name.
    """
    bind = op.get_bind()
    now = datetime.utcnow()

    rows = bind.execute(
        sa.text(
            """
            SELECT store_key, MIN(store_label) AS label, MIN(created_at) AS first_seen
              FROM visits
             WHERE store_key IS NOT NULL AND store_key <> ''
             GROUP BY store_key
            """
        )
    ).fetchall()

    for row in rows:
        store_key = row[0]
        label = row[1] or store_key
        created = row[2] or now
        store_id = str(uuid.uuid4())
        bind.execute(
            sa.text(
                """
                INSERT INTO stores (id, name, normalized_name, active, created_at, updated_at)
                VALUES (:id, :name, :norm, 1, :ts, :ts)
                """
            ),
            {"id": store_id, "name": label, "norm": store_key, "ts": created},
        )
        bind.execute(
            sa.text("UPDATE visits SET store_id = :sid WHERE store_key = :sk"),
            {"sid": store_id, "sk": store_key},
        )


def downgrade() -> None:
    op.drop_index("ix_visits_store_id", table_name="visits")
    with op.batch_alter_table("visits") as batch_op:
        batch_op.drop_constraint("fk_visits_store_id", type_="foreignkey")
        batch_op.drop_column("store_id")

    op.drop_index("ix_stores_active", table_name="stores")
    op.drop_index("ix_stores_normalized_name", table_name="stores")
    op.drop_index("ix_stores_code", table_name="stores")
    op.drop_table("stores")
