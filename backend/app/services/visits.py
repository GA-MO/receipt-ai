"""Visit lifecycle helpers — creation, auto-attach, summary stats."""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Document, Store, Visit
from .merchants import _rule_based_clean

logger = logging.getLogger(__name__)


def find_matching_store(
    db: Session,
    merchant_normalized: str | None,
    *,
    threshold: int | None = None,
) -> Store | None:
    """Match a doc's normalized merchant against an active ``Store`` row.

    Exact match on cleaned ``normalized_name`` first; falls back to RapidFuzz
    token-set similarity (default threshold = ``merchant_fuzzy_threshold``).
    Returns ``None`` if nothing crosses the threshold — caller treats that as
    "store not in system yet, hold for manual resolution".
    """
    if not merchant_normalized:
        return None
    candidate = _rule_based_clean(merchant_normalized)
    if not candidate:
        return None

    active_stores = (
        db.query(Store)
        .filter(Store.active.is_(True))
        .all()
    )
    if not active_stores:
        return None

    cleaned_map: dict[str, Store] = {}
    for s in active_stores:
        for raw in (s.normalized_name, s.name):
            cleaned = _rule_based_clean(raw or "")
            if cleaned and cleaned not in cleaned_map:
                cleaned_map[cleaned] = s

    if candidate in cleaned_map:
        return cleaned_map[candidate]

    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        return None

    keys = list(cleaned_map.keys())
    if not keys:
        return None
    match = process.extractOne(candidate, keys, scorer=fuzz.token_set_ratio)
    cutoff = threshold if threshold is not None else settings.merchant_fuzzy_threshold
    if match and match[1] >= cutoff:
        return cleaned_map[match[0]]
    return None


def derive_doc_period(doc: Document) -> str:
    """Decide which YYYY-MM Visit this doc should attach to.

    Order:
      1. The merchant's printed ``document_date`` — what the receipt actually
         says, which is what users expect to drive the period.
      2. The ``uploaded_at`` month as a last-resort fallback so a doc that
         couldn't be dated still lands in *some* Visit.

    This is the single source of truth for "which month does this receipt
    belong to"; everything downstream (Visit reuse, monthly aggregation) keys
    off this value.
    """
    raw = (doc.document_date or "").strip()
    if len(raw) >= 7 and raw[4] == "-":
        return raw[:7]
    fallback = doc.uploaded_at or datetime.now(UTC)
    return f"{fallback.year:04d}-{fallback.month:02d}"


def get_or_create_visit_for_merchant(
    db: Session,
    store_key: str,
    *,
    report_period: str,
    store_label: str | None = None,
) -> Visit | None:
    """Find or create a ``(store_key, report_period)`` Visit *only* when the
    merchant matches an active Store master row.

    Visits are gated to known Stores — receipts from unrecognised merchants are
    held in the dashboard's "unknown stores" bucket until the user assigns or
    creates a Store. Returns ``None`` when no Store matches.
    """
    matching_store = find_matching_store(db, store_key)
    if matching_store is None:
        return None

    # Re-key the visit to the Store's canonical normalized_name so all variants
    # of "ก.เจริญ" end up under the same Visit row.
    canonical_key = (matching_store.normalized_name or matching_store.name or store_key).strip()

    visit = (
        db.query(Visit)
        .filter(
            Visit.store_id == matching_store.id,
            Visit.report_period == report_period,
            Visit.deleted_at.is_(None),
        )
        .order_by(Visit.created_at.desc())
        .first()
    )
    if visit:
        if store_label and not visit.store_label:
            visit.store_label = store_label
        return visit

    visit = Visit(
        id=str(uuid.uuid4()),
        store_id=matching_store.id,
        store_key=canonical_key,
        store_label=store_label or matching_store.name,
        report_period=report_period,
    )
    db.add(visit)
    db.flush()
    return visit


def ensure_visit_for_doc(db: Session, doc: Document) -> Visit | None:
    """Attach ``doc`` to a Visit (``store × month``) after extraction.

    Returns ``None`` (and leaves ``doc.visit_id`` unset) when:
      * ``merchant_normalized`` is missing — doc is an *orphan*, surfaces in
        the dashboard's "AI อ่านชื่อร้านไม่ได้" section.
      * The merchant doesn't match any active Store — doc is an *unknown
        store*, surfaces in the dashboard's "ร้านยังไม่อยู่ในระบบ" section
        for the user to assign or create a Store.

    When the doc already has a visit, returns the existing visit unchanged.
    """
    if doc.visit_id is not None:
        return doc.visit
    if not doc.merchant_normalized:
        return None
    period = derive_doc_period(doc)
    # ``store_label`` is intentionally NOT passed so the helper defaults to
    # ``matching_store.name`` (Store master). The raw receipt text lives on
    # ``doc.merchant_name`` for audit; the Visit label belongs to the admin's
    # canonical name in the Store master.
    visit = get_or_create_visit_for_merchant(
        db,
        store_key=doc.merchant_normalized,
        report_period=period,
    )
    if visit is None:
        return None
    doc.visit_id = visit.id
    return visit


def reattach_visit_for_doc(db: Session, doc: Document) -> Visit | None:
    """Re-run visit attachment after a user edits the doc's merchant or date.

    Detaches from the current Visit when the new ``(store, period)`` doesn't
    have a matching Store either — the doc drops back into the dashboard's
    "unknown stores" bucket.
    """
    if not doc.merchant_normalized:
        doc.visit_id = None
        return None
    period = derive_doc_period(doc)
    # ``store_label`` is intentionally NOT passed so the helper defaults to
    # ``matching_store.name`` (Store master). The raw receipt text lives on
    # ``doc.merchant_name`` for audit; the Visit label belongs to the admin's
    # canonical name in the Store master.
    visit = get_or_create_visit_for_merchant(
        db,
        store_key=doc.merchant_normalized,
        report_period=period,
    )
    if visit is None:
        doc.visit_id = None
        return None
    if doc.visit_id != visit.id:
        doc.visit_id = visit.id
    return visit


def recompute_store_label(db: Session, visit: Visit) -> None:
    """Refresh ``store_label`` / ``store_key`` on a Visit.

    When the Visit is attached to a Store master row (``store_id`` set), both
    the label and the key come from that Store — the admin's canonical name
    is the single source of truth. The most-common ``merchant_name`` from
    docs is only used as a fallback for orphan visits with no Store yet.
    """
    if visit.store_id:
        store = db.query(Store).filter(Store.id == visit.store_id).first()
        if store:
            visit.store_label = store.name
            visit.store_key = store.normalized_name or store.name
            visit.updated_at = datetime.now(UTC)
            return

    # Orphan visit (no Store master yet) — fall back to receipt consensus.
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


def check_period_mismatch(doc: Document) -> str | None:
    """If the doc's date falls outside its visit's ``report_period``, return a
    Thai-language warning. Otherwise return None.

    Tolerates missing data: if either side is unset, no warning.
    """
    visit = doc.visit
    if visit is None or not visit.report_period or not doc.document_date:
        return None
    period = visit.report_period.strip()  # YYYY-MM
    if len(period) != 7 or period[4] != "-":
        return None
    if not doc.document_date.startswith(period):
        return (
            f"⚠️ วันที่บนใบเสร็จ ({doc.document_date}) อยู่นอกเดือนรายงานของ visit "
            f"({period}) — ตรวจสอบว่าใบนี้อยู่ใน visit ถูกหรือไม่"
        )
    return None


def is_store_mismatch(doc: Document) -> bool:
    """True when the doc's normalized merchant differs from its visit's
    ``store_key`` — i.e. the receipt is from a different store than the
    visit was created for. No-op when either side is unset.
    """
    visit = doc.visit
    if visit is None or not visit.store_key or not doc.merchant_normalized:
        return False
    return doc.merchant_normalized != visit.store_key


def check_store_mismatch(doc: Document) -> str | None:
    """Thai-language warning when the receipt belongs to a different store
    than the visit. Returns None when no visit is attached or merchant data
    is missing on either side.
    """
    if not is_store_mismatch(doc):
        return None
    visit = doc.visit
    visit_label = visit.store_label or visit.store_key
    doc_label = doc.merchant_name or doc.merchant_normalized
    return (
        f"⚠️ ใบเสร็จนี้มาจากร้าน \"{doc_label}\" แต่ visit ตั้งเป็นร้าน "
        f"\"{visit_label}\" — ตรวจสอบว่าอยู่ใน visit ถูกหรือไม่"
    )


def cleanup_empty_visits(db: Session, visit_ids: Iterable[str | None]) -> int:
    """Soft-delete any visit in ``visit_ids`` that no longer has alive docs.

    Cascade hook called from doc-mutation paths (delete / purge / PATCH-reattach)
    so a visit's lifecycle tracks its last alive document. Idempotent: visits
    already trashed are skipped, visits still referenced by ≥1 alive doc are
    left alone. Returns the number of visits newly closed.
    """
    candidates = {v for v in visit_ids if v}
    if not candidates:
        return 0
    still_referenced = {
        vid
        for (vid,) in db.query(Document.visit_id)
        .filter(
            Document.visit_id.in_(candidates),
            Document.deleted_at.is_(None),
        )
        .distinct()
    }
    to_close = candidates - still_referenced
    if not to_close:
        return 0
    return (
        db.query(Visit)
        .filter(Visit.id.in_(to_close), Visit.deleted_at.is_(None))
        .update({Visit.deleted_at: datetime.now(UTC)}, synchronize_session="fetch")
    )


def sweep_empty_visits(db: Session) -> int:
    """Soft-delete every alive visit that has zero alive documents.

    Safety-net for visits that escaped the cascade (legacy data, edge cases).
    Idempotent. Returns the number of visits closed.
    """
    referenced = db.query(Document.visit_id).filter(
        Document.deleted_at.is_(None),
        Document.visit_id.isnot(None),
    )
    return (
        db.query(Visit)
        .filter(Visit.deleted_at.is_(None), Visit.id.notin_(referenced))
        .update({Visit.deleted_at: datetime.now(UTC)}, synchronize_session="fetch")
    )


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
