"""Move all previously-uploaded receipts into a 2026-04 visit per store.

Data migration only — schema unchanged.

Rationale: the visit-pivot rollout introduced ``visits.report_period`` after
production already had data. Existing visits were backfilled in migration
0018 from ``merchant_normalized`` but left with NULL period, which is now an
exception case in the store-first navigation flow. This migration consolidates
every store's period-NULL docs into a single 2026-04 visit so the new UX
displays them cleanly.

Other visits (period already set, or different period) are left untouched.
Orphan docs (no ``merchant_normalized``) cannot be assigned to a store and
remain in the legacy "all documents" view.

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-21
"""
from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TARGET_PERIOD = "2026-04"


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.utcnow()

    # Distinct stores that have at least one period-NULL visit (with or
    # without docs). Skipping visits without a store_id — those are orphans
    # that can't be merged into a Store.
    store_ids = bind.execute(
        sa.text(
            """
            SELECT DISTINCT store_id
              FROM visits
             WHERE report_period IS NULL
               AND deleted_at IS NULL
               AND store_id IS NOT NULL
            """
        )
    ).fetchall()

    for (store_id,) in store_ids:
        # Find or create the canonical 2026-04 visit for this store.
        existing = bind.execute(
            sa.text(
                """
                SELECT id FROM visits
                 WHERE store_id = :sid
                   AND report_period = :p
                   AND deleted_at IS NULL
                 ORDER BY created_at
                 LIMIT 1
                """
            ),
            {"sid": store_id, "p": TARGET_PERIOD},
        ).fetchone()

        if existing:
            target_id = existing[0]
        else:
            # Promote the oldest period-NULL visit to TARGET_PERIOD so we
            # keep its created_at and store_label history.
            promoted = bind.execute(
                sa.text(
                    """
                    SELECT id FROM visits
                     WHERE store_id = :sid
                       AND report_period IS NULL
                       AND deleted_at IS NULL
                     ORDER BY created_at
                     LIMIT 1
                    """
                ),
                {"sid": store_id},
            ).fetchone()
            if not promoted:
                continue
            target_id = promoted[0]
            bind.execute(
                sa.text(
                    "UPDATE visits SET report_period = :p, updated_at = :now WHERE id = :id"
                ),
                {"p": TARGET_PERIOD, "now": now, "id": target_id},
            )

        # Move every doc on a sibling period-NULL visit into the target.
        bind.execute(
            sa.text(
                """
                UPDATE documents
                   SET visit_id = :target
                 WHERE visit_id IN (
                    SELECT id FROM visits
                     WHERE store_id = :sid
                       AND report_period IS NULL
                       AND deleted_at IS NULL
                       AND id != :target
                 )
                """
            ),
            {"target": target_id, "sid": store_id},
        )

        # Soft-delete the emptied sibling visits.
        bind.execute(
            sa.text(
                """
                UPDATE visits
                   SET deleted_at = :now
                 WHERE store_id = :sid
                   AND report_period IS NULL
                   AND deleted_at IS NULL
                   AND id != :target
                """
            ),
            {"sid": store_id, "now": now, "target": target_id},
        )


def downgrade() -> None:
    # Pure data migration; not reversible deterministically.
    pass
