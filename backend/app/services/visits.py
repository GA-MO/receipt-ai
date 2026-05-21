"""Visit lifecycle helpers — creation, auto-attach, summary stats."""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Document, Store, Visit

logger = logging.getLogger(__name__)


def get_or_create_visit_for_merchant(
    db: Session,
    store_key: str,
    *,
    store_label: str | None = None,
) -> Visit:
    """Find an existing live Visit for ``store_key`` or create one.

    Used by the legacy single-file ``POST /api/documents/upload`` flow to keep
    the new Visit-centric UX working without forcing callers to know about
    Visits up front.
    """
    visit = (
        db.query(Visit)
        .filter(Visit.store_key == store_key, Visit.deleted_at.is_(None))
        .order_by(Visit.created_at.desc())
        .first()
    )
    if visit:
        if store_label and not visit.store_label:
            visit.store_label = store_label
        return visit

    # If a Store master row matches this normalized merchant, link the new
    # Visit to it so the admin sees auto-discovered stores under their entry.
    matching_store = (
        db.query(Store)
        .filter(Store.normalized_name == store_key, Store.active.is_(True))
        .first()
    )
    visit = Visit(
        id=str(uuid.uuid4()),
        store_id=matching_store.id if matching_store else None,
        store_key=store_key,
        store_label=store_label or (matching_store.name if matching_store else store_key),
    )
    db.add(visit)
    db.flush()
    return visit


def ensure_visit_for_doc(db: Session, doc: Document) -> Visit | None:
    """Attach ``doc`` to a Visit after extraction, if not already attached.

    Returns the Visit it was attached to (or already on). No-op if
    ``merchant_normalized`` is missing — those docs stay orphan.
    """
    if doc.visit_id is not None:
        return doc.visit
    if not doc.merchant_normalized:
        return None
    visit = get_or_create_visit_for_merchant(
        db,
        store_key=doc.merchant_normalized,
        store_label=doc.merchant_name,
    )
    doc.visit_id = visit.id
    return visit


def recompute_store_label(db: Session, visit: Visit) -> None:
    """Pick the most-common merchant_name across the visit's live docs.

    Called after bulk uploads finish so a Visit reflects the merchant text
    most receipts agreed on.
    """
    docs = (
        db.query(Document)
        .filter(Document.visit_id == visit.id, Document.deleted_at.is_(None))
        .all()
    )
    labels = [d.merchant_name for d in docs if d.merchant_name]
    keys = [d.merchant_normalized for d in docs if d.merchant_normalized]
    if labels:
        visit.store_label = Counter(labels).most_common(1)[0][0]
    if keys:
        visit.store_key = Counter(keys).most_common(1)[0][0]
    visit.updated_at = datetime.now(UTC)


def visit_doc_date_range(db: Session, visit_id: str) -> tuple[str | None, str | None]:
    """Return (earliest, latest) ``document_date`` for the visit's live docs."""
    row = (
        db.query(
            func.min(Document.document_date),
            func.max(Document.document_date),
        )
        .filter(Document.visit_id == visit_id, Document.deleted_at.is_(None))
        .first()
    )
    if not row:
        return None, None
    return row[0], row[1]
