import asyncio
import json
import logging
import os
import concurrent.futures
import uuid
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ..config import settings
from ..database import SessionLocal, get_db
from ..events import event_bus
from ..models import Document, DocumentEvent, DocumentItem
from ..schemas import (
    BulkActionResult,
    BulkIds,
    DocumentItemBase,
    DocumentItemCreate,
    DocumentItemUpdate,
    DocumentListItem,
    DocumentResponse,
    DocumentUpdate,
)
from ..services.extraction import extract_receipt
from ..services.aliases import apply_alias_to_extraction
from ..services.product_aliases import (
    apply_aliases_to_items as apply_product_aliases,
    normalize_key as product_normalize_key,
    upsert_alias as upsert_product_alias,
)
from ..services.audit import record as record_event
from ..models import CatalogGapEvent, Product, TypoRecoveryEvent
from ..services.catalog import find_code_by_name, is_canonical_name, selling_unit_by_code
from ..services.merchants import assign_normalized_merchant
from ..services.visits import (
    check_period_mismatch,
    check_store_mismatch,
    cleanup_empty_visits,
    ensure_visit_for_doc,
    reattach_visit_for_doc,
)


def _resolve_product_code(
    db: Session, item: DocumentItemBase, document_id: str | None = None
) -> str | None:
    """Resolve a SKU code for an extracted line item.

    Trust order:

    1. Gemini-emitted ``product_code`` is *valid* (active row) → use it.
    2. Gemini-emitted ``product_code`` is *invalid* but the normalized name
       has an *exact* catalog match → typo recovery. Trust the name over the
       code (Gemini occasionally transposes digits; the name field is more
       reliable). Returns the code resolved from the name.
    3. Gemini-emitted ``product_code`` is *invalid* AND name has no exact
       catalog match → genuine catalog gap. Return ``None``. Fuzzy fallback
       here would silently pick a wrong-size or wrong-variant SKU.
    4. Gemini *abstained* (no code emitted) → fuzzy-match the normalized
       name against ``products.canonical_name``/``display_name``. This
       handles older extraction paths and items where Gemini chose name-only.
    """
    emitted = (item.product_code or "").strip() or None
    name = item.product_name_normalized

    if emitted:
        exists = (
            db.query(Product.code)
            .filter(Product.code == emitted, Product.active.is_(True))
            .first()
        )
        if exists:
            return emitted
        # Distinguish typo'd code from genuine catalog gap by checking
        # whether the *name* the model emitted is itself a known canonical.
        if name and is_canonical_name(db, name):
            recovered = find_code_by_name(db, name)
            if recovered:
                logger.warning(
                    "Recovered typo'd product_code %r → %r via exact name match (%r)",
                    emitted, recovered, name,
                )
                # Log the recovery so admins can spot recurring typo patterns
                # (Gemini consistently mis-types one specific code → warrants
                # a hint in the prompt or a catalog representation tweak).
                try:
                    db.add(
                        TypoRecoveryEvent(
                            document_id=document_id,
                            emitted_code=emitted,
                            recovered_code=recovered,
                            product_name=name,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to record typo_recovery_event: %s", exc)
                return recovered
        logger.warning(
            "Gemini emitted unknown product_code %r for %r — catalog gap, leaving unresolved.",
            emitted, name,
        )
        # Log to catalog_gap_events so admins can review recurring gaps
        # and add the missing SKU. Failure to write (e.g. session in odd
        # state) must not block extraction itself.
        try:
            db.add(
                CatalogGapEvent(
                    document_id=document_id,
                    emitted_code=emitted,
                    product_name=name,
                    product_name_raw=item.product_name_raw,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to record catalog_gap_event: %s", exc)
        return None

    # No code emitted by Gemini → try fuzzy match by name.
    resolved = find_code_by_name(db, name)
    if resolved is None and _is_primary_product_category(item.category):
        # Gemini correctly abstained on a primary-category item (e.g. a
        # competitor liquor brand) — record a gap with no emitted_code so
        # admins can decide whether to add the SKU.
        try:
            db.add(
                CatalogGapEvent(
                    document_id=document_id,
                    emitted_code=None,
                    product_name=name,
                    product_name_raw=item.product_name_raw,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to record catalog_gap_event (no-code path): %s", exc)
    return resolved


# Categories where a missing product_code likely means "real SKU we don't
# have in catalog yet" rather than "packaging / delivery fee / supplies".
_PRIMARY_PRODUCT_CATEGORIES = frozenset(
    {"เครื่องดื่ม", "สินค้าพรีเมียมสิงห์"}
)


def _is_primary_product_category(category: str | None) -> bool:
    return bool(category) and category in _PRIMARY_PRODUCT_CATEGORIES


from ..services.storage import save_bytes, validate_and_hash
from ..services.validation import validate_extraction

logger = logging.getLogger(__name__)

router = APIRouter()

# Dedicated thread pool for in-process extraction. Sized by
# ``EXTRACTION_CONCURRENCY`` so a single bulk-upload request (which arrives as
# one POST + N files) still runs N extractions concurrently — FastAPI's built-in
# BackgroundTasks runs scheduled callbacks serially in one thread, which would
# otherwise serialize the whole batch. arq mode (see worker.py) bypasses this
# pool and uses its own queue.
#
# Lazy-init so the pool survives multiple FastAPI lifespans in the same process
# (e.g. TestClient creating/disposing the app once per test).
_extraction_pool: concurrent.futures.ThreadPoolExecutor | None = None


def _get_extraction_pool() -> concurrent.futures.ThreadPoolExecutor:
    global _extraction_pool
    if _extraction_pool is None or _extraction_pool._shutdown:
        _extraction_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=settings.extraction_concurrency,
            thread_name_prefix="extract",
        )
    return _extraction_pool


def shutdown_extraction_pool() -> None:
    """Drain in-flight extractions on app shutdown. Re-created on next submit."""
    global _extraction_pool
    if _extraction_pool is not None:
        _extraction_pool.shutdown(wait=True, cancel_futures=False)
        _extraction_pool = None


def _run_processing(doc_id: str, file_path: str) -> None:
    """Core processing logic, shared between BackgroundTasks and arq worker."""
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            logger.error("Document %s not found for processing", doc_id)
            return

        result = extract_receipt(file_path)

        warnings = validate_extraction(result)

        # Snapshot the raw Gemini extraction BEFORE any alias mutation so
        # ``doc.raw_extraction`` always reflects what the model actually said.
        raw_extraction_json = result.model_dump_json()

        # Apply learned aliases before persisting: if a human has previously
        # corrected this merchant's name or category, use that.
        try:
            applied = apply_alias_to_extraction(db, result)
            if applied:
                logger.info(
                    "Applied learned alias for %s: %s (hits=%s)",
                    doc_id,
                    applied.canonical_name,
                    applied.hit_count,
                )
        except Exception as alias_exc:  # noqa: BLE001
            logger.warning("Alias lookup failed for %s: %s", doc_id, alias_exc)

        # Same treatment for each line item.
        try:
            item_matches = apply_product_aliases(db, result.items)
            if item_matches:
                logger.info(
                    "Applied learned product aliases on %d/%d items of %s",
                    item_matches,
                    len(result.items),
                    doc_id,
                )
        except Exception as p_exc:  # noqa: BLE001
            logger.warning("Product alias lookup failed for %s: %s", doc_id, p_exc)

        doc.merchant_name = result.merchant_name
        doc.document_number = result.document_number
        doc.document_date = result.document_date
        doc.category = result.category
        doc.confidence = result.confidence
        doc.notes = result.notes
        doc.raw_extraction = raw_extraction_json
        doc.needs_review = (
            result.confidence < settings.review_confidence_threshold
            or len(result.needs_review_fields) > 0
        )
        # Gemini sometimes accepts a non-receipt (screenshot, document photo)
        # — those return very low confidence with no items. Mark them so the
        # dashboard surfaces them in a separate bucket and they're not
        # attempted to attach to a Visit.
        is_not_receipt = result.confidence < 0.3 and not result.items
        doc.status = "not_receipt" if is_not_receipt else "extracted"
        doc.processed_at = datetime.now(UTC)
        if not is_not_receipt:
            assign_normalized_merchant(doc, db)

        if warnings:
            existing = doc.notes or ""
            separator = "\n" if existing else ""
            doc.notes = existing + separator + "\n".join(f"⚠️ {w}" for w in warnings)

        has_catalog_gap = False
        for item_data in result.items:
            # Raw snapshot of what Gemini read — fall back to normalized when
            # the model didn't emit raw (older extraction paths or legacy
            # re-extracts). Alias learning uses this as a stable source.
            raw_name = item_data.product_name_raw or item_data.product_name_normalized
            # SKU resolution priority:
            # 1. Gemini-emitted product_code (from prompt catalog) when valid.
            # 2. Fuzzy fallback against products.canonical_name / display_name.
            code = _resolve_product_code(db, item_data, document_id=doc_id)
            # A primary-category item with no resolved code is a real catalog
            # gap (KULOV case) — the admin should review the doc to decide
            # whether to add the SKU.
            if code is None and _is_primary_product_category(item_data.category):
                has_catalog_gap = True
            item = DocumentItem(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                product_name_raw=raw_name,
                product_name_normalized=item_data.product_name_normalized,
                product_code=code,
                quantity=item_data.quantity,
                unit=item_data.unit,
                category=item_data.category,
                confidence=result.confidence,
            )
            db.add(item)

        # Surface docs with at least one catalog gap so the admin sees them
        # — without this, Gemini's uniformly-high confidence (≥0.95) would
        # let real "missing SKU" cases slip past the review queue.
        if has_catalog_gap:
            doc.needs_review = True

        db.flush()
        db.refresh(doc)

        if doc.auto_attach_visit and not is_not_receipt:
            try:
                ensure_visit_for_doc(db, doc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to auto-attach visit for %s: %s", doc_id, exc)

        period_warning = check_period_mismatch(doc)
        if period_warning:
            existing = doc.notes or ""
            sep = "\n" if existing else ""
            doc.notes = existing + sep + period_warning
            doc.needs_review = True

        store_warning = check_store_mismatch(doc)
        if store_warning:
            existing = doc.notes or ""
            sep = "\n" if existing else ""
            doc.notes = existing + sep + store_warning
            doc.needs_review = True

        db.commit()
        logger.info("Document %s processed successfully", doc_id)
        event_bus.publish(doc_id, {"status": doc.status, "needs_review": doc.needs_review})
        record_event(
            db,
            doc_id,
            "extracted",
            actor="system",
            payload={
                "confidence": doc.confidence,
                "merchant": doc.merchant_name,
                "items": len(doc.items or []),
            },
        )
    except Exception as exc:
        logger.error("Failed to process document %s: %s", doc_id, exc)
        db.rollback()
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.status = "error"
            doc.error_message = str(exc)
            db.commit()
            event_bus.publish(doc_id, {"status": "error", "error_message": str(exc)})
            record_event(
                db,
                doc_id,
                "extraction_failed",
                actor="system",
                payload={"error": str(exc)[:500]},
            )
    finally:
        db.close()


def _enqueue_processing(
    doc_id: str,
    file_path: str,
    background_tasks: BackgroundTasks,
) -> None:
    """Enqueue processing to arq if configured, otherwise to the local thread pool.

    ``background_tasks`` is kept in the signature for symmetry with FastAPI's
    DI but is unused in the local-pool path — submitting to a pool gives true
    concurrency across files in a single bulk-upload POST, which FastAPI's
    BackgroundTasks (serial, single-thread) does not.
    """
    if settings.use_arq:
        from ..worker import enqueue_process_document

        try:
            enqueue_process_document(doc_id, file_path)
            return
        except Exception as exc:
            logger.warning(
                "Failed to enqueue arq job, falling back to local pool: %s", exc
            )
    _get_extraction_pool().submit(_run_processing, doc_id, file_path)


@router.post("/upload", response_model=DocumentResponse)
def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    validated = validate_and_hash(file, max_bytes=settings.max_file_size_bytes)

    # Only block uploads if a live (non-trashed) doc already has the hash —
    # users can re-upload a file they previously trashed.
    existing = (
        db.query(Document)
        .filter(
            Document.file_hash == validated.file_hash,
            Document.deleted_at.is_(None),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            409,
            detail={
                "message": f"เอกสารนี้เคยอัปโหลดแล้ว (ชื่อไฟล์เดิม: {existing.filename})",
                "existing_document_id": existing.id,
                "existing_filename": existing.filename,
            },
        )

    doc_id = str(uuid.uuid4())
    original_ext = os.path.splitext(file.filename or "")[1].lower()
    ext = validated.extension or original_ext
    filename = f"{doc_id}{ext}"
    file_path = os.path.join(settings.upload_dir, filename)
    save_bytes(file_path, validated.data)

    # If we converted (e.g. HEIC → JPG), also update the user-facing filename
    # so downloads and review UI show a sensible extension.
    display_name = file.filename or filename
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
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    record_event(
        db,
        doc_id,
        "uploaded",
        actor="user",
        payload={"filename": display_name, "size_bytes": validated.size, "file_type": validated.file_type},
    )

    logger.info(
        "Document %s uploaded: %s (%d bytes, %s)",
        doc_id,
        file.filename,
        validated.size,
        validated.file_type,
    )

    _enqueue_processing(doc_id, file_path, background_tasks)

    return doc


def _apply_filters(query, status, search, date_from, date_to, category=None, *, include_deleted: bool = False):
    """Apply common filters to a Document query.

    By default excludes soft-deleted documents — the recycle-bin endpoints opt
    back in with ``include_deleted=True``.
    """
    if not include_deleted:
        query = query.filter(Document.deleted_at.is_(None))
    if status:
        query = query.filter(Document.status == status)
    if category:
        query = query.filter(Document.category == category)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            Document.merchant_name.ilike(pattern)
            | Document.filename.ilike(pattern)
            | Document.document_number.ilike(pattern)
            | Document.ocr_text.ilike(pattern)
        )
    if date_from:
        query = query.filter(Document.document_date >= date_from)
    if date_to:
        query = query.filter(Document.document_date <= date_to)
    return query


_SORTABLE_COLUMNS = {
    "uploaded_at": Document.uploaded_at,
    "document_date": Document.document_date,
    "merchant_name": Document.merchant_name,
    "confidence": Document.confidence,
    "status": Document.status,
    "category": Document.category,
}


@router.get("", response_model=list[DocumentListItem])
def list_documents(
    skip: int = 0,
    limit: int = 50,
    status: str | None = None,
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    category: str | None = None,
    sort_by: str = "uploaded_at",
    sort_dir: str = "desc",
    db: Session = Depends(get_db),
):
    query = _apply_filters(db.query(Document), status, search, date_from, date_to, category)

    item_count_sub = (
        select(func.count(DocumentItem.id))
        .where(DocumentItem.document_id == Document.id)
        .correlate(Document)
        .scalar_subquery()
        .label("item_count")
    )

    sort_col = _SORTABLE_COLUMNS.get(sort_by, Document.uploaded_at)
    order = sort_col.desc() if sort_dir.lower() == "desc" else sort_col.asc()

    rows = (
        query
        .add_columns(item_count_sub)
        .order_by(order, Document.uploaded_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return [
        DocumentListItem(
            id=d.id,
            filename=d.filename,
            file_type=d.file_type,
            status=d.status,
            uploaded_at=d.uploaded_at,
            merchant_name=d.merchant_name,
            merchant_normalized=d.merchant_normalized,
            document_date=d.document_date,
            category=d.category,
            confidence=d.confidence,
            needs_review=d.needs_review,
            item_count=item_count,
            visit_id=d.visit_id,
        )
        for d, item_count in rows
    ]


@router.get("/count")
def count_documents(
    status: str | None = None,
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    category: str | None = None,
    db: Session = Depends(get_db),
):
    query = _apply_filters(db.query(Document), status, search, date_from, date_to, category)
    return {"count": query.count()}


@router.get("/trash", response_model=list[DocumentListItem])
def list_trash(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    item_count_sub = (
        select(func.count(DocumentItem.id))
        .where(DocumentItem.document_id == Document.id)
        .correlate(Document)
        .scalar_subquery()
        .label("item_count")
    )
    rows = (
        db.query(Document)
        .filter(Document.deleted_at.isnot(None))
        .add_columns(item_count_sub)
        .order_by(Document.deleted_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [
        DocumentListItem(
            id=d.id,
            filename=d.filename,
            file_type=d.file_type,
            status=d.status,
            uploaded_at=d.uploaded_at,
            merchant_name=d.merchant_name,
            merchant_normalized=d.merchant_normalized,
            document_date=d.document_date,
            category=d.category,
            confidence=d.confidence,
            needs_review=d.needs_review,
            item_count=item_count,
            visit_id=d.visit_id,
        )
        for d, item_count in rows
    ]


@router.get("/trash/count")
def count_trash(db: Session = Depends(get_db)):
    return {
        "count": db.query(func.count(Document.id))
        .filter(Document.deleted_at.isnot(None))
        .scalar()
        or 0
    }


@router.get("/{doc_id}", response_model=DocumentResponse)
def get_document(doc_id: str, db: Session = Depends(get_db)):
    doc = (
        db.query(Document)
        .filter(Document.id == doc_id, Document.deleted_at.is_(None))
        .first()
    )
    if not doc:
        raise HTTPException(404, "ไม่พบเอกสาร")
    return doc


@router.put("/{doc_id}", response_model=DocumentResponse)
def update_document(
    doc_id: str,
    update: DocumentUpdate,
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "ไม่พบเอกสาร")

    incoming = update.model_dump(exclude_unset=True)

    # Capture before-state so the audit entry records what actually changed.
    diff: dict[str, dict[str, object]] = {}
    for field, new_value in incoming.items():
        old_value = getattr(doc, field, None)
        if old_value != new_value:
            diff[field] = {
                "from": str(old_value) if old_value is not None else None,
                "to": str(new_value) if new_value is not None else None,
            }

    for field, value in incoming.items():
        setattr(doc, field, value)

    # When the merchant or date changes, the doc may now belong to a different
    # Visit (different store, different month). Re-normalize and reattach so
    # the dashboard / monthly aggregate stay in sync.
    needs_reattach = (
        "merchant_name" in incoming
        or "merchant_normalized" in incoming
        or "document_date" in incoming
    )
    if needs_reattach:
        old_visit_id = doc.visit_id
        if "merchant_name" in incoming and "merchant_normalized" not in incoming:
            # User edited the printed name only — re-derive canonical form.
            assign_normalized_merchant(doc, db)
        reattach_visit_for_doc(db, doc)
        if old_visit_id and old_visit_id != doc.visit_id:
            db.flush()
            cleanup_empty_visits(db, [old_visit_id])

    db.commit()
    db.refresh(doc)
    logger.info("Document %s updated", doc_id)

    if diff:
        record_event(db, doc_id, "edited", actor="user", payload={"changed": diff})

    # Merchant-alias learning was removed when Store master became the
    # source of truth for merchant identity. Existing aliases are still
    # *applied* during extraction (see ``_run_processing``) so historical
    # learning is not lost, but no new merchant aliases are added here.

    return doc


@router.post("/{doc_id}/items", response_model=DocumentResponse)
def create_item(
    doc_id: str,
    payload: DocumentItemCreate,
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "ไม่พบเอกสาร")
    # Trust explicit product_code from the UI (user picked from autocomplete);
    # fall back to catalog lookup when the caller just sent a name.
    resolved_code = payload.product_code or find_code_by_name(db, payload.product_name_normalized)
    item = DocumentItem(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        # For manually-added items we don't have a Gemini raw signal — use
        # whatever the user typed so alias learning still has a source.
        product_name_raw=payload.product_name_raw or payload.product_name_normalized,
        product_name_normalized=payload.product_name_normalized,
        product_code=resolved_code,
        quantity=payload.quantity,
        unit=payload.unit,
        category=payload.category,
        needs_review=True,
    )
    db.add(item)
    db.commit()
    db.refresh(doc)
    logger.info("Item %s added to document %s", item.id, doc_id)
    record_event(
        db,
        doc_id,
        "item_added",
        actor="user",
        payload={"item_id": item.id, "name": item.product_name_normalized},
    )
    return doc


@router.put("/{doc_id}/items/{item_id}", response_model=DocumentResponse)
def update_item(
    doc_id: str,
    item_id: str,
    update: DocumentItemUpdate,
    db: Session = Depends(get_db),
):
    item = (
        db.query(DocumentItem)
        .filter(DocumentItem.id == item_id, DocumentItem.document_id == doc_id)
        .first()
    )
    if not item:
        raise HTTPException(404, "ไม่พบรายการสินค้า")
    incoming = update.model_dump(exclude_unset=True)

    old_name = item.product_name_normalized
    old_category = item.category
    # Alias source = raw (what Gemini originally OCR'd). Stable across edits
    # so the mapping stored is ``(original_ocr_text → user_canonical)``
    # instead of drifting with each correction.
    raw_name = item.product_name_raw or old_name
    new_name = incoming.get("product_name_normalized", old_name)
    new_category = incoming.get("category", old_category)

    for field, value in incoming.items():
        setattr(item, field, value)

    # Re-resolve product_code whenever the name changed, unless the caller
    # explicitly passed one (UI picking from the autocomplete).
    if "product_name_normalized" in incoming and "product_code" not in incoming:
        item.product_code = find_code_by_name(db, new_name)

    # Snap the unit to the SKU's selling unit when a catalog match resolves,
    # unless the user is explicitly editing the unit in this same request.
    # Keeps manual corrections consistent with the extraction-time override.
    if item.product_code and "unit" not in incoming:
        catalog_unit = selling_unit_by_code(item.product_code)
        if catalog_unit:
            item.unit = catalog_unit

    db.commit()
    doc = db.query(Document).filter(Document.id == doc_id).first()
    db.refresh(doc)
    record_event(
        db,
        doc_id,
        "item_updated",
        actor="user",
        payload={"item_id": item_id, "fields": list(incoming.keys())},
    )

    # Learn product alias only when the name actually changed (or a new
    # category was set for the same name). Quantity/price/unit edits must not
    # produce aliases — they are per-receipt facts. Also honour catalog /
    # semantic-jump guards inside ``upsert_product_alias``.
    alias_status: dict | None = None
    try:
        if raw_name and new_name:
            raw_key = product_normalize_key(raw_name)
            new_key = product_normalize_key(new_name)
            name_changed = raw_key and raw_key != new_key
            category_changed = bool(new_category) and (new_category or "") != (old_category or "")
            # Ambiguity guard: if other items in this same document share the
            # same raw text, the user's correction is per-document
            # disambiguation (e.g. "เลมอนโซดา" and "เลมอนโซดา (เรด)" both
            # extracted as "เลมอนโซดา"). Generalising would overwrite the
            # alias for the OTHER variant on every future receipt.
            sibling_raw_count = (
                db.query(DocumentItem)
                .filter(
                    DocumentItem.document_id == doc_id,
                    DocumentItem.id != item_id,
                    DocumentItem.product_name_raw == raw_name,
                )
                .count()
            ) if raw_key and (name_changed or category_changed) else 0

            if sibling_raw_count > 0:
                alias_status = {
                    "learned": False,
                    "skipped_reason": "ambiguous_source",
                    "skipped_detail": (
                        f"raw text {raw_name!r} appears in {sibling_raw_count} other item(s) "
                        f"of this document — correction is per-doc, not generalised"
                    ),
                }
                record_event(
                    db, doc_id, "product_alias_skipped", actor="system",
                    payload={
                        "source": raw_name, "canonical": new_name,
                        "reason": "ambiguous_source",
                        "detail": f"{sibling_raw_count} sibling items share same raw",
                    },
                )
            elif raw_key and (name_changed or category_changed):
                res = upsert_product_alias(
                    db,
                    source_text=raw_name,
                    canonical_name=new_name,
                    category=new_category,
                )
                if res.ok and res.alias is not None:
                    alias_status = {
                        "learned": True,
                        "hit_count": int(res.alias.hit_count or 0),
                    }
                    record_event(
                        db,
                        doc_id,
                        "product_alias_learned",
                        actor="user",
                        payload={
                            "source": raw_name,
                            "canonical": new_name,
                            "category": new_category,
                            "hit_count": int(res.alias.hit_count or 0),
                        },
                    )
                elif res.skipped_reason is not None:
                    alias_status = {
                        "learned": False,
                        "skipped_reason": res.skipped_reason.value,
                        "skipped_detail": res.skipped_detail,
                    }
                    record_event(
                        db,
                        doc_id,
                        "product_alias_skipped",
                        actor="system",
                        payload={
                            "source": raw_name,
                            "canonical": new_name,
                            "reason": res.skipped_reason.value,
                            "detail": res.skipped_detail,
                        },
                    )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to learn product alias for item %s: %s", item_id, exc)

    if alias_status is not None:
        logger.info("Alias status for item %s: %s", item_id, alias_status)

    return doc


@router.delete("/{doc_id}/items/{item_id}", response_model=DocumentResponse)
def delete_item(
    doc_id: str,
    item_id: str,
    db: Session = Depends(get_db),
):
    item = (
        db.query(DocumentItem)
        .filter(DocumentItem.id == item_id, DocumentItem.document_id == doc_id)
        .first()
    )
    if not item:
        raise HTTPException(404, "ไม่พบรายการสินค้า")
    deleted_name = item.product_name_normalized
    db.delete(item)
    db.commit()
    doc = db.query(Document).filter(Document.id == doc_id).first()
    db.refresh(doc)
    logger.info("Item %s deleted from document %s", item_id, doc_id)
    record_event(
        db,
        doc_id,
        "item_deleted",
        actor="user",
        payload={"item_id": item_id, "name": deleted_name},
    )
    return doc


@router.post("/{doc_id}/reextract", response_model=DocumentResponse)
def reextract_document(
    doc_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Re-run OCR + AI extraction on an existing document."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "ไม่พบเอกสาร")
    if not os.path.exists(doc.file_path):
        raise HTTPException(404, "ไม่พบไฟล์เอกสาร")

    # Clear old items
    db.query(DocumentItem).filter(DocumentItem.document_id == doc_id).delete()
    doc.status = "processing"
    doc.error_message = None
    doc.ocr_text = None
    db.commit()
    db.refresh(doc)

    logger.info("Document %s queued for re-extraction", doc_id)
    record_event(db, doc_id, "reextracted", actor="user")
    _enqueue_processing(doc_id, doc.file_path, background_tasks)
    return doc


@router.post("/bulk/approve", response_model=BulkActionResult)
def bulk_approve(payload: BulkIds, db: Session = Depends(get_db)):
    docs = (
        db.query(Document)
        .filter(Document.id.in_(payload.ids), Document.deleted_at.is_(None))
        .all()
    )
    now = datetime.now(UTC)
    succeeded = 0
    for doc in docs:
        doc.status = "reviewed"
        doc.needs_review = False
        doc.reviewed_at = now
        succeeded += 1
    db.commit()
    failed_ids = [i for i in payload.ids if i not in {d.id for d in docs}]
    logger.info("Bulk approved %d documents (%d missing)", succeeded, len(failed_ids))
    return BulkActionResult(succeeded=succeeded, failed=len(failed_ids), failed_ids=failed_ids)


@router.post("/bulk/delete", response_model=BulkActionResult)
def bulk_delete(payload: BulkIds, db: Session = Depends(get_db)):
    """Soft-delete: moves to trash. Use ``/bulk/purge`` to permanently remove."""
    docs = (
        db.query(Document)
        .filter(Document.id.in_(payload.ids), Document.deleted_at.is_(None))
        .all()
    )
    now = datetime.now(UTC)
    touched_visits = {d.visit_id for d in docs}
    for doc in docs:
        doc.deleted_at = now
    db.flush()
    closed = cleanup_empty_visits(db, touched_visits)
    db.commit()
    failed_ids = [i for i in payload.ids if i not in {d.id for d in docs}]
    logger.info(
        "Bulk soft-deleted %d documents (%d missing, %d empty visits closed)",
        len(docs), len(failed_ids), closed,
    )
    return BulkActionResult(succeeded=len(docs), failed=len(failed_ids), failed_ids=failed_ids)


@router.post("/bulk/restore", response_model=BulkActionResult)
def bulk_restore(payload: BulkIds, db: Session = Depends(get_db)):
    docs = (
        db.query(Document)
        .filter(Document.id.in_(payload.ids), Document.deleted_at.isnot(None))
        .all()
    )
    for doc in docs:
        doc.deleted_at = None
    db.commit()
    failed_ids = [i for i in payload.ids if i not in {d.id for d in docs}]
    logger.info("Bulk restored %d documents", len(docs))
    return BulkActionResult(succeeded=len(docs), failed=len(failed_ids), failed_ids=failed_ids)


@router.post("/bulk/purge", response_model=BulkActionResult)
def bulk_purge(payload: BulkIds, db: Session = Depends(get_db)):
    """Permanently delete: only operates on already-trashed documents."""
    docs = (
        db.query(Document)
        .filter(Document.id.in_(payload.ids), Document.deleted_at.isnot(None))
        .all()
    )
    touched_visits = {d.visit_id for d in docs}
    for doc in docs:
        try:
            if doc.file_path and os.path.exists(doc.file_path):
                os.remove(doc.file_path)
        except OSError as exc:
            logger.warning("Failed to remove file for %s: %s", doc.id, exc)
        db.delete(doc)
    db.flush()
    closed = cleanup_empty_visits(db, touched_visits)
    db.commit()
    failed_ids = [i for i in payload.ids if i not in {d.id for d in docs}]
    logger.info(
        "Bulk purged %d documents (%d empty visits closed)", len(docs), closed
    )
    return BulkActionResult(succeeded=len(docs), failed=len(failed_ids), failed_ids=failed_ids)


@router.post("/{doc_id}/approve", response_model=DocumentResponse)
def approve_document(doc_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "ไม่พบเอกสาร")
    doc.status = "reviewed"
    doc.needs_review = False
    doc.reviewed_at = datetime.now(UTC)
    db.commit()
    db.refresh(doc)
    logger.info("Document %s approved", doc_id)
    record_event(db, doc_id, "approved", actor="user")
    return doc


@router.delete("/{doc_id}")
def delete_document(doc_id: str, db: Session = Depends(get_db)):
    """Soft-delete: moves the document to the recycle bin.

    Use ``POST /documents/{id}/purge`` (or ``/bulk/purge``) to permanently
    remove a trashed document and its file on disk.
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "ไม่พบเอกสาร")
    old_visit_id = doc.visit_id
    if doc.deleted_at is not None:
        # Second delete on an already-trashed doc = purge (convenience for UIs
        # that don't distinguish).
        try:
            if doc.file_path and os.path.exists(doc.file_path):
                os.remove(doc.file_path)
        except OSError as exc:
            logger.warning("Failed to remove file for %s: %s", doc_id, exc)
        db.delete(doc)
        db.flush()
        cleanup_empty_visits(db, [old_visit_id])
        db.commit()
        logger.info("Document %s permanently deleted", doc_id)
        return {"message": "ลบเอกสารถาวรเรียบร้อย"}
    doc.deleted_at = datetime.now(UTC)
    db.flush()
    cleanup_empty_visits(db, [old_visit_id])
    db.commit()
    logger.info("Document %s moved to trash", doc_id)
    record_event(db, doc_id, "trashed", actor="user")
    return {"message": "ย้ายไปถังขยะเรียบร้อย"}


@router.post("/{doc_id}/restore", response_model=DocumentResponse)
def restore_document(doc_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "ไม่พบเอกสาร")
    if doc.deleted_at is None:
        raise HTTPException(400, "เอกสารนี้ไม่ได้อยู่ในถังขยะ")
    doc.deleted_at = None
    db.commit()
    db.refresh(doc)
    logger.info("Document %s restored", doc_id)
    record_event(db, doc_id, "restored", actor="user")
    return doc


@router.post("/{doc_id}/purge")
def purge_document(doc_id: str, db: Session = Depends(get_db)):
    """Permanently delete a trashed document."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "ไม่พบเอกสาร")
    if doc.deleted_at is None:
        raise HTTPException(400, "ต้องย้ายไปถังขยะก่อน")
    old_visit_id = doc.visit_id
    try:
        if doc.file_path and os.path.exists(doc.file_path):
            os.remove(doc.file_path)
    except OSError as exc:
        logger.warning("Failed to remove file for %s: %s", doc_id, exc)
    db.delete(doc)
    db.flush()
    cleanup_empty_visits(db, [old_visit_id])
    db.commit()
    logger.info("Document %s purged", doc_id)
    return {"message": "ลบเอกสารถาวรเรียบร้อย"}


@router.get("/{doc_id}/history")
def get_document_history(
    doc_id: str,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """Return the audit trail for a document, newest first."""
    # Verify the doc exists (including trashed) so the UI can show history
    # in the recycle bin too.
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "ไม่พบเอกสาร")
    events = (
        db.query(DocumentEvent)
        .filter(DocumentEvent.document_id == doc_id)
        .order_by(DocumentEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "actor": e.actor,
            "payload": json.loads(e.payload) if e.payload else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]


@router.get("/{doc_id}/image")
def get_document_image(doc_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "ไม่พบเอกสาร")
    if not os.path.exists(doc.file_path):
        raise HTTPException(404, "ไม่พบไฟล์")
    return FileResponse(doc.file_path)


@router.get("/{doc_id}/events")
async def stream_document_events(
    doc_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Server-Sent Events stream for a document's processing status.

    Emits the initial status immediately, then pushes updates as ``_run_processing``
    publishes them. The client closes the connection when it sees a terminal
    status (``extracted``, ``reviewed``, ``error``).
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "ไม่พบเอกสาร")

    initial_payload = {
        "status": doc.status,
        "needs_review": doc.needs_review,
        "error_message": doc.error_message,
    }

    async def event_generator():
        yield {"event": "status", "data": json.dumps(initial_payload, ensure_ascii=False)}

        # If already terminal, close the stream.
        if doc.status in ("reviewed", "extracted", "error"):
            return

        subscription = event_bus.subscribe(doc_id)
        try:
            # Heartbeat task so proxies don't time out
            keepalive_task = asyncio.create_task(_sse_keepalive())
            anext_task = asyncio.create_task(subscription.__anext__())

            try:
                while True:
                    if await request.is_disconnected():
                        break

                    done, _pending = await asyncio.wait(
                        {anext_task, keepalive_task},
                        timeout=30,
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    if anext_task in done:
                        try:
                            payload = anext_task.result()
                        except StopAsyncIteration:
                            break
                        yield {
                            "event": "status",
                            "data": json.dumps(payload, ensure_ascii=False),
                        }
                        if payload.get("status") in ("extracted", "reviewed", "error"):
                            break
                        anext_task = asyncio.create_task(subscription.__anext__())
                    else:
                        # Timeout or keepalive — emit comment to keep connection alive.
                        yield {"event": "ping", "data": ""}
                        if keepalive_task.done():
                            keepalive_task = asyncio.create_task(_sse_keepalive())
            finally:
                anext_task.cancel()
                keepalive_task.cancel()
        finally:
            await subscription.aclose()

    return EventSourceResponse(event_generator())


async def _sse_keepalive() -> None:
    await asyncio.sleep(25)
