"""Add visits table + documents.visit_id; backfill Visit per merchant_normalized.

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-21
"""
import uuid
from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "visits",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("store_key", sa.String(), nullable=True),
        sa.Column("store_label", sa.String(), nullable=True),
        sa.Column("rep_name", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_visits_store_key", "visits", ["store_key"])
    op.create_index("ix_visits_created_at", "visits", ["created_at"])
    op.create_index("ix_visits_deleted_at", "visits", ["deleted_at"])

    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("visit_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_documents_visit_id",
            "visits",
            ["visit_id"],
            ["id"],
        )
    op.create_index("ix_documents_visit_id", "documents", ["visit_id"])
    op.create_index(
        "ix_documents_visit_id_date",
        "documents",
        ["visit_id", "document_date"],
    )

    _backfill_visits()


def _backfill_visits() -> None:
    """One Visit per distinct merchant_normalized; assign visit_id to its docs.

    Docs with merchant_normalized IS NULL remain unassigned (orphans surfaced in
    the legacy documents view).
    """
    bind = op.get_bind()
    now = datetime.utcnow()

    rows = bind.execute(
        sa.text(
            """
            SELECT merchant_normalized,
                   MIN(merchant_name)    AS store_label,
                   MIN(uploaded_at)      AS first_seen
              FROM documents
             WHERE merchant_normalized IS NOT NULL
               AND merchant_normalized <> ''
             GROUP BY merchant_normalized
            """
        )
    ).fetchall()

    for row in rows:
        store_key = row[0]
        store_label = row[1] or store_key
        created_at = row[2] or now
        visit_id = str(uuid.uuid4())

        bind.execute(
            sa.text(
                """
                INSERT INTO visits (id, store_key, store_label, created_at, updated_at)
                VALUES (:id, :store_key, :store_label, :created_at, :created_at)
                """
            ),
            {
                "id": visit_id,
                "store_key": store_key,
                "store_label": store_label,
                "created_at": created_at,
            },
        )
        bind.execute(
            sa.text(
                "UPDATE documents SET visit_id = :vid WHERE merchant_normalized = :mn"
            ),
            {"vid": visit_id, "mn": store_key},
        )


def downgrade() -> None:
    op.drop_index("ix_documents_visit_id_date", table_name="documents")
    op.drop_index("ix_documents_visit_id", table_name="documents")
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_constraint("fk_documents_visit_id", type_="foreignkey")
        batch_op.drop_column("visit_id")

    op.drop_index("ix_visits_deleted_at", table_name="visits")
    op.drop_index("ix_visits_created_at", table_name="visits")
    op.drop_index("ix_visits_store_key", table_name="visits")
    op.drop_table("visits")
