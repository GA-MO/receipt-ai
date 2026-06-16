"""Drop & Review inbox — the "dump a day of receipts" workflow.

The user uploads a pile of receipts. The worker extracts each one and auto-
attaches it to a Visit (``store_normalized × YYYY-MM``). The user later
reviews each Visit, fixing the merchant or date inline if AI got it wrong.

This router exposes:

* ``POST /api/inbox`` — bulk-upload many files in one shot.
* ``GET /api/inbox/dashboard`` — the home-page summary: orphans, non-receipts,
  errors, and Visits keyed by month.
* ``POST /api/inbox/documents/{id}/name`` — quick-name an orphan and trigger
  visit attachment.
* ``DELETE /api/inbox/documents/{id}`` — soft-delete a doc that shouldn't have
  been uploaded.
* ``POST /api/inbox/non-receipts/purge`` — bulk-clean non-receipts older than
  the configured retention window (default 7 days).

Visit confirmation is no longer a step — the Visit list itself is where the
user does the work, with mismatch warnings catching AI errors.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Document, DocumentItem, Store, Visit
from ..schemas import (
    DocumentListItem,
    VisitListItem,
)
from ..services.audit import record as record_event
from ..services.merchants import assign_normalized_merchant
from ..services.storage import save_bytes, validate_and_hash
from ..services.visits import (
    cleanup_empty_visits,
    ensure_visit_for_doc,
    is_store_mismatch,
    reattach_visit_for_doc,
    recompute_store_label,
    visit_doc_date_range,
)
from .documents import _enqueue_processing

logger = logging.getLogger(__name__)

router = APIRouter()


NON_RECEIPT_RETENTION_DAYS = 7


def _doc_to_list_item(doc: Document, item_count: int) -> DocumentListItem:
    return DocumentListItem(
        id=doc.id,
        filename=doc.filename,
        file_type=doc.file_type,
        status=doc.status,
        uploaded_at=doc.uploaded_at,
        merchant_name=doc.merchant_name,
        merchant_normalized=doc.merchant_normalized,
        document_date=doc.document_date,
        category=doc.category,
        confidence=doc.confidence,
        needs_review=doc.needs_review,
        item_count=item_count,
        visit_id=doc.visit_id,
        period_mismatch=False,
        store_mismatch=is_store_mismatch(doc),
    )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@router.post("", status_code=201)
def upload_inbox(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Bulk-upload many receipts at once. Each file kicks off async extraction
    and the worker auto-attaches the doc to a Visit once the merchant is read.

    Returns the document IDs created plus per-file failures so the UI can
    surface them. Duplicates (same file_hash) are reported, not re-processed.
    """
    created_ids: list[str] = []
    duplicates: list[dict] = []
    failures: list[dict] = []

    for upload in files:
        try:
            validated = validate_and_hash(upload, max_bytes=settings.max_file_size_bytes)
        except HTTPException as exc:
            failures.append({"filename": upload.filename, "detail": str(exc.detail)})
            continue
        except Exception as exc:  # noqa: BLE001
            failures.append({"filename": upload.filename, "detail": str(exc)})
            continue

        existing = (
            db.query(Document)
            .filter(
                Document.file_hash == validated.file_hash,
                Document.deleted_at.is_(None),
            )
            .first()
        )
        if existing:
            duplicates.append(
                {
                    "filename": upload.filename,
                    "existing_document_id": existing.id,
                    "existing_visit_id": existing.visit_id,
                }
            )
            continue

        doc_id = str(uuid.uuid4())
        original_ext = os.path.splitext(upload.filename or "")[1].lower()
        ext = validated.extension or original_ext
        filename = f"{doc_id}{ext}"
        file_path = os.path.join(settings.upload_dir, filename)
        save_bytes(file_path, validated.data)

        display_name = upload.filename or filename
        if ext != original_ext and original_ext:
            base, _ = os.path.splitext(display_name)
            display_name = f"{base}{ext}"

        doc = Document(
            id=doc_id,
            filename=display_name,
            file_path=file_path,
            file_type=validated.file_type,
            file_hash=validated.file_hash,
            status="processing",
            auto_attach_visit=True,
        )
        db.add(doc)
        db.flush()
        record_event(
            db,
            doc_id,
            "uploaded",
            actor="user",
            payload={
                "filename": display_name,
                "size_bytes": validated.size,
                "file_type": validated.file_type,
                "via": "inbox",
            },
        )
        _enqueue_processing(doc_id, file_path, background_tasks)
        created_ids.append(doc_id)

    db.commit()

    return {
        "document_ids": created_ids,
        "duplicates": duplicates,
        "failures": failures,
    }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def _visit_to_list_item(
    visit: Visit, doc_count: int, reviewed_count: int, new_doc_count: int,
    earliest: str | None, latest: str | None, needs_review_count: int = 0,
) -> dict:
    """A Visit row enriched with the ``new_doc_count`` signal — number of docs
    uploaded after the user last marked the visit reviewed. The dashboard uses
    it to flag visits as "needs attention" without exposing the timestamp.
    ``needs_review_count`` is how many docs in the visit the AI is unsure about
    (explicit needs_review or low confidence) — surfaced so the user can tell at
    a glance which stores still hold receipts worth a look."""
    base = VisitListItem(
        id=visit.id,
        store_id=visit.store_id,
        store_key=visit.store_key,
        store_label=visit.store_label,
        report_period=visit.report_period,
        rep_name=visit.rep_name,
        notes=visit.notes,
        created_at=visit.created_at,
        updated_at=visit.updated_at,
        document_count=doc_count,
        reviewed_count=reviewed_count,
        earliest_doc_date=earliest,
        latest_doc_date=latest,
    ).model_dump()
    base["new_doc_count"] = new_doc_count
    base["needs_review_count"] = needs_review_count
    base["last_reviewed_at"] = visit.last_reviewed_at.isoformat() if visit.last_reviewed_at else None
    return base


@router.get("/dashboard")
def get_dashboard(
    month: str | None = None,
    db: Session = Depends(get_db),
):
    """Home-page summary: things needing attention + recent visits.

    ``month`` (``YYYY-MM``) filters visits to one reporting period. Orphans /
    non-receipts / errors are global (not month-scoped) so the user can always
    see them regardless of which month they're viewing.
    """
    # "Orphan" = AI couldn't read the merchant. User names it themselves.
    orphans = (
        db.query(Document)
        .filter(
            Document.status == "extracted",
            Document.visit_id.is_(None),
            Document.merchant_normalized.is_(None),
            Document.deleted_at.is_(None),
        )
        .order_by(Document.uploaded_at.desc())
        .limit(50)
        .all()
    )
    # "Unknown store" = AI read a merchant but it doesn't match any active
    # Store master row. User picks an existing Store or creates a new one.
    unknown_stores = (
        db.query(Document)
        .filter(
            Document.status == "extracted",
            Document.visit_id.is_(None),
            Document.merchant_normalized.isnot(None),
            Document.deleted_at.is_(None),
        )
        .order_by(Document.uploaded_at.desc())
        .limit(50)
        .all()
    )
    non_receipts = (
        db.query(Document)
        .filter(
            Document.status == "not_receipt",
            Document.deleted_at.is_(None),
        )
        .order_by(Document.uploaded_at.desc())
        .limit(50)
        .all()
    )
    errors = (
        db.query(Document)
        .filter(
            Document.status == "error",
            Document.deleted_at.is_(None),
        )
        .order_by(Document.uploaded_at.desc())
        .limit(50)
        .all()
    )
    processing = (
        db.query(Document)
        .filter(
            Document.status.in_(("pending", "processing")),
            Document.deleted_at.is_(None),
        )
        .order_by(Document.uploaded_at.desc())
        .all()
    )

    # Item-count subquery for thumbnails / list views.
    all_docs = (
        list(orphans)
        + list(unknown_stores)
        + list(non_receipts)
        + list(errors)
        + list(processing)
    )
    item_counts: dict[str, int] = {}
    if all_docs:
        rows = (
            db.query(DocumentItem.document_id, func.count(DocumentItem.id))
            .filter(DocumentItem.document_id.in_([d.id for d in all_docs]))
            .group_by(DocumentItem.document_id)
            .all()
        )
        item_counts = dict(rows)

    # Visits — optionally filtered by month. Each visit gets a ``new_doc_count``
    # = docs uploaded after the visit was last reviewed.
    visit_q = db.query(Visit).filter(Visit.deleted_at.is_(None))
    if month:
        visit_q = visit_q.filter(Visit.report_period == month)
    visits = visit_q.order_by(Visit.updated_at.desc()).limit(200).all()

    visit_rows = []
    for v in visits:
        doc_count = (
            db.query(func.count(Document.id))
            .filter(Document.visit_id == v.id, Document.deleted_at.is_(None))
            .scalar()
            or 0
        )
        reviewed = (
            db.query(func.count(Document.id))
            .filter(
                Document.visit_id == v.id,
                Document.deleted_at.is_(None),
                Document.status == "reviewed",
            )
            .scalar()
            or 0
        )
        if v.last_reviewed_at:
            new_count = (
                db.query(func.count(Document.id))
                .filter(
                    Document.visit_id == v.id,
                    Document.deleted_at.is_(None),
                    Document.uploaded_at > v.last_reviewed_at,
                )
                .scalar()
                or 0
            )
        else:
            new_count = 0
        # Docs the AI flagged or read with low confidence — "worth a look".
        needs_review_count = (
            db.query(func.count(Document.id))
            .filter(
                Document.visit_id == v.id,
                Document.deleted_at.is_(None),
                (Document.needs_review.is_(True)) | (Document.confidence < 0.7),
            )
            .scalar()
            or 0
        )
        earliest, latest = visit_doc_date_range(db, v.id)
        visit_rows.append(
            _visit_to_list_item(
                v, doc_count, reviewed, new_count, earliest, latest, needs_review_count
            )
        )

    # Distinct months available for the picker.
    months = [
        r[0]
        for r in (
            db.query(Visit.report_period)
            .filter(Visit.deleted_at.is_(None), Visit.report_period.isnot(None))
            .distinct()
            .order_by(Visit.report_period.desc())
            .all()
        )
        if r[0]
    ]

    return {
        "month": month,
        "available_months": months,
        "orphans": [_doc_to_list_item(d, item_counts.get(d.id, 0)) for d in orphans],
        "unknown_stores": [
            _doc_to_list_item(d, item_counts.get(d.id, 0)) for d in unknown_stores
        ],
        "non_receipts": [_doc_to_list_item(d, item_counts.get(d.id, 0)) for d in non_receipts],
        "errors": [_doc_to_list_item(d, item_counts.get(d.id, 0)) for d in errors],
        "processing": [_doc_to_list_item(d, item_counts.get(d.id, 0)) for d in processing],
        "visits": visit_rows,
        "counts": {
            "orphans": len(orphans),
            "unknown_stores": len(unknown_stores),
            "non_receipts": len(non_receipts),
            "errors": len(errors),
            "processing": len(processing),
            "visits": len(visit_rows),
            "attention": sum(1 for v in visit_rows if v["new_doc_count"] > 0),
        },
    }


# ---------------------------------------------------------------------------
# Orphan handling
# ---------------------------------------------------------------------------


@router.post("/documents/{doc_id}/name", response_model=DocumentListItem)
def name_orphan(
    doc_id: str,
    body: dict,
    db: Session = Depends(get_db),
):
    """Quick-name an orphan: user types the store name, system normalizes and
    attaches the doc to the matching ``store × month`` Visit (creates one if
    needed).
    """
    name = (body.get("merchant_name") or "").strip()
    if not name:
        raise HTTPException(400, "กรุณาใส่ชื่อร้าน")

    doc = (
        db.query(Document)
        .filter(Document.id == doc_id, Document.deleted_at.is_(None))
        .first()
    )
    if not doc:
        raise HTTPException(404, "ไม่พบเอกสาร")
    if doc.visit_id is not None:
        raise HTTPException(400, "เอกสารนี้ผูกกับ visit แล้ว")

    doc.merchant_name = name
    assign_normalized_merchant(doc, db)
    ensure_visit_for_doc(db, doc)
    record_event(
        db,
        doc_id,
        "orphan_named",
        actor="user",
        payload={
            "merchant_name": name,
            "merchant_normalized": doc.merchant_normalized,
            "visit_id": doc.visit_id,
        },
    )
    db.commit()
    db.refresh(doc)
    item_count = (
        db.query(DocumentItem)
        .filter(DocumentItem.document_id == doc.id)
        .count()
    )
    return _doc_to_list_item(doc, item_count)


@router.post("/documents/{doc_id}/assign-store", response_model=DocumentListItem)
def assign_store_to_doc(
    doc_id: str,
    body: dict,
    db: Session = Depends(get_db),
):
    """Resolve an "unknown store" doc by linking it to an existing Store
    master row, then auto-create / find the matching ``store × month`` Visit.
    Body: ``{store_id: str}``.
    """
    store_id = (body.get("store_id") or "").strip()
    if not store_id:
        raise HTTPException(400, "store_id is required")

    doc = (
        db.query(Document)
        .filter(Document.id == doc_id, Document.deleted_at.is_(None))
        .first()
    )
    if not doc:
        raise HTTPException(404, "ไม่พบเอกสาร")
    store = db.query(Store).filter(Store.id == store_id, Store.active.is_(True)).first()
    if not store:
        raise HTTPException(404, "ไม่พบร้านในระบบ")

    # User has explicitly told us this doc belongs to ``store`` — overwrite the
    # AI's (possibly wrong) reading with the Store master's canonical name on
    # both fields so display + matching agree. Future re-extractions will keep
    # this corrected identity because product_aliases pin merchant_normalized.
    old_visit_id = doc.visit_id
    old_merchant = doc.merchant_name
    doc.merchant_name = store.name
    doc.merchant_normalized = (store.normalized_name or store.name).strip()
    new_visit = reattach_visit_for_doc(db, doc)
    record_event(
        db,
        doc_id,
        "store_assigned",
        actor="user",
        payload={
            "store_id": store.id,
            "store_name": store.name,
            "old_merchant": old_merchant,
            "old_visit_id": old_visit_id,
            "visit_id": doc.visit_id,
        },
    )
    # Sync the new visit's display label to the chosen store, and close the
    # old visit if this was its last alive doc.
    if new_visit is not None:
        recompute_store_label(db, new_visit)
    if old_visit_id and old_visit_id != doc.visit_id:
        db.flush()
        cleanup_empty_visits(db, [old_visit_id])
    db.commit()
    db.refresh(doc)
    item_count = (
        db.query(DocumentItem).filter(DocumentItem.document_id == doc.id).count()
    )
    return _doc_to_list_item(doc, item_count)


@router.post("/documents/{doc_id}/create-store", response_model=DocumentListItem)
def create_store_from_doc(
    doc_id: str,
    body: dict,
    db: Session = Depends(get_db),
):
    """Create a new Store master row from an "unknown store" doc, then attach
    the doc to its Visit. Body: ``{name: str, code?: str, normalized_name?: str}``.
    """
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    code = (body.get("code") or "").strip() or None
    normalized_name = (body.get("normalized_name") or name).strip()

    doc = (
        db.query(Document)
        .filter(Document.id == doc_id, Document.deleted_at.is_(None))
        .first()
    )
    if not doc:
        raise HTTPException(404, "ไม่พบเอกสาร")

    if code:
        clash = db.query(Store).filter(Store.code == code).first()
        if clash:
            raise HTTPException(409, f"code {code} มีอยู่แล้ว")

    store = Store(
        id=str(uuid.uuid4()),
        name=name,
        code=code,
        normalized_name=normalized_name,
        active=True,
    )
    db.add(store)
    db.flush()

    # User just defined this Store from scratch — adopt its name as the doc's
    # canonical identity, replacing whatever the AI read (which was wrong
    # enough to land in the unknown-stores bucket).
    old_visit_id = doc.visit_id
    old_merchant = doc.merchant_name
    doc.merchant_name = name
    doc.merchant_normalized = normalized_name
    new_visit = reattach_visit_for_doc(db, doc)
    record_event(
        db,
        doc_id,
        "store_created_from_doc",
        actor="user",
        payload={
            "store_id": store.id,
            "store_name": store.name,
            "old_merchant": old_merchant,
            "old_visit_id": old_visit_id,
            "visit_id": doc.visit_id,
        },
    )
    if new_visit is not None:
        recompute_store_label(db, new_visit)
    if old_visit_id and old_visit_id != doc.visit_id:
        db.flush()
        cleanup_empty_visits(db, [old_visit_id])
    db.commit()
    db.refresh(doc)
    item_count = (
        db.query(DocumentItem).filter(DocumentItem.document_id == doc.id).count()
    )
    return _doc_to_list_item(doc, item_count)


@router.delete("/documents/{doc_id}")
def discard_inbox_doc(doc_id: str, db: Session = Depends(get_db)):
    """Soft-delete an orphan / non-receipt / error doc."""
    doc = (
        db.query(Document)
        .filter(Document.id == doc_id, Document.deleted_at.is_(None))
        .first()
    )
    if not doc:
        raise HTTPException(404, "Document not found")
    doc.deleted_at = datetime.now(UTC)
    record_event(db, doc_id, "inbox_discarded", actor="user")
    db.commit()
    return {"id": doc_id, "deleted_at": doc.deleted_at.isoformat()}


# ---------------------------------------------------------------------------
# Visit lifecycle
# ---------------------------------------------------------------------------


@router.post("/visits/{visit_id}/mark-reviewed")
def mark_visit_reviewed(visit_id: str, db: Session = Depends(get_db)):
    """Stamp ``last_reviewed_at`` so the dashboard stops nagging until new docs
    arrive *after* this moment. Pairs with the dashboard's
    ``new_doc_count`` signal."""
    visit = (
        db.query(Visit)
        .filter(Visit.id == visit_id, Visit.deleted_at.is_(None))
        .first()
    )
    if not visit:
        raise HTTPException(404, "Visit not found")
    visit.last_reviewed_at = datetime.now(UTC)
    db.commit()
    return {"id": visit.id, "last_reviewed_at": visit.last_reviewed_at.isoformat()}


# ---------------------------------------------------------------------------
# Non-receipt cleanup
# ---------------------------------------------------------------------------


@router.post("/non-receipts/purge")
def purge_non_receipts(
    older_than_days: int = NON_RECEIPT_RETENTION_DAYS,
    db: Session = Depends(get_db),
):
    """Soft-delete non-receipts older than ``older_than_days``. Called by the
    frontend on dashboard load (best-effort cleanup) and can also be triggered
    by a cron. Returns the number of docs affected.
    """
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    candidates = (
        db.query(Document)
        .filter(
            Document.status == "not_receipt",
            Document.deleted_at.is_(None),
            Document.uploaded_at < cutoff,
        )
        .all()
    )
    for d in candidates:
        d.deleted_at = datetime.now(UTC)
        record_event(
            db,
            d.id,
            "non_receipt_purged",
            actor="system",
            payload={"older_than_days": older_than_days},
        )
    db.commit()
    return {"purged": len(candidates), "cutoff": cutoff.isoformat()}
