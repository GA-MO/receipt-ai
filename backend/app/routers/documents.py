import asyncio
import json
import logging
import os
import threading
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
from ..models import Document, DocumentItem
from ..schemas import (
    DocumentItemUpdate,
    DocumentListItem,
    DocumentResponse,
    DocumentUpdate,
)
from ..services.extraction import extract_receipt
from ..services.extraction_agentic import extract_agentic
from ..services.extraction_combined import (
    compute_history_fraud_checks,
    extract_with_fraud,
    merge_fraud_results,
)
from ..services.fraud import run_fraud_detection
from ..services.merchants import assign_normalized_merchant


def _resolve_extraction_mode() -> str:
    """Resolve the active extraction mode, honouring the legacy boolean flag."""
    mode = (settings.extraction_mode or "legacy").lower()
    if mode not in {"legacy", "combined", "agentic"}:
        logger.warning("Unknown extraction_mode %r — falling back to legacy", mode)
        mode = "legacy"
    if settings.use_combined_extraction and mode == "legacy":
        mode = "combined"
    return mode
from ..services.storage import save_bytes, validate_and_hash
from ..services.validation import validate_extraction

logger = logging.getLogger(__name__)

router = APIRouter()

# Limit concurrent OCR+extraction to 1 to prevent memory exhaustion when using
# FastAPI BackgroundTasks. The arq worker (see worker.py) handles its own
# concurrency via the queue.
_processing_lock = threading.Semaphore(1)


def _process_document(doc_id: str, file_path: str) -> None:
    """Background task: extract receipt data with Gemini Vision → update the document.

    Used as the in-process fallback when ``USE_ARQ`` is disabled. The arq worker
    calls :func:`process_document_sync` directly (same body), sharing logic via
    ``_run_processing``.
    """
    _processing_lock.acquire()
    try:
        _run_processing(doc_id, file_path)
    finally:
        _processing_lock.release()


def _run_processing(doc_id: str, file_path: str) -> None:
    """Core processing logic, shared between BackgroundTasks and arq worker."""
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            logger.error("Document %s not found for processing", doc_id)
            return

        mode = _resolve_extraction_mode()
        gemini_fraud_block: dict | None = None
        agentic_fraud_payload: dict | None = None

        if mode == "combined":
            combined = extract_with_fraud(file_path)
            result = combined.extraction
            gemini_fraud_block = combined.fraud_payload
        elif mode == "agentic":
            agentic = extract_agentic(file_path, db)
            result = agentic.extraction
            agentic_fraud_payload = agentic.fraud_payload
            logger.info(
                "Agentic used %d iterations, tools=%s",
                agentic.iterations,
                agentic.tool_calls,
            )
        else:
            result = extract_receipt(file_path)

        warnings = validate_extraction(result)

        doc.merchant_name = result.merchant_name
        doc.document_number = result.document_number
        doc.document_date = result.document_date
        doc.subtotal = result.subtotal
        doc.discount = result.discount
        doc.vat = result.vat
        doc.grand_total = result.grand_total
        doc.category = result.category
        doc.confidence = result.confidence
        doc.notes = result.notes
        doc.raw_extraction = result.model_dump_json()
        doc.needs_review = (
            result.confidence < settings.review_confidence_threshold
            or len(result.needs_review_fields) > 0
        )
        doc.status = "extracted"
        doc.processed_at = datetime.now(UTC)
        assign_normalized_merchant(doc, db)

        if warnings:
            existing = doc.notes or ""
            separator = "\n" if existing else ""
            doc.notes = existing + separator + "\n".join(f"⚠️ {w}" for w in warnings)

        for item_data in result.items:
            item = DocumentItem(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                product_name_normalized=item_data.product_name_normalized,
                quantity=item_data.quantity,
                unit=item_data.unit,
                unit_price=item_data.unit_price,
                line_total=item_data.line_total,
                category=item_data.category,
                confidence=result.confidence,
            )
            db.add(item)

        db.flush()
        db.refresh(doc)
        try:
            if mode == "combined":
                # Gemini already did self-contained fraud; Python adds
                # history-based flags (duplicate, unusual amount).
                history_flags = compute_history_fraud_checks(doc, db)
                doc.fraud_flags = merge_fraud_results(gemini_fraud_block, history_flags)
            elif mode == "agentic":
                # Gemini already consulted history inline via tool call, so its
                # fraud_analysis output is final. Still merge with zero extra
                # flags to get consistent serialization.
                doc.fraud_flags = merge_fraud_results(agentic_fraud_payload, [])
            else:
                doc.fraud_flags = run_fraud_detection(doc, db)
            if doc.fraud_flags:
                logger.info("Document %s flagged for fraud: %s", doc_id, doc.fraud_flags[:200])
        except Exception as fraud_exc:
            logger.warning("Fraud detection failed for %s: %s", doc_id, fraud_exc)

        db.commit()
        logger.info("Document %s processed successfully", doc_id)
        event_bus.publish(doc_id, {"status": doc.status, "needs_review": doc.needs_review})
    except Exception as exc:
        logger.error("Failed to process document %s: %s", doc_id, exc)
        db.rollback()
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.status = "error"
            doc.error_message = str(exc)
            db.commit()
            event_bus.publish(doc_id, {"status": "error", "error_message": str(exc)})
    finally:
        db.close()


def _enqueue_processing(
    doc_id: str,
    file_path: str,
    background_tasks: BackgroundTasks,
) -> None:
    """Enqueue processing to arq if configured, otherwise schedule as BackgroundTask."""
    if settings.use_arq:
        from ..worker import enqueue_process_document

        try:
            enqueue_process_document(doc_id, file_path)
            return
        except Exception as exc:
            logger.warning(
                "Failed to enqueue arq job, falling back to BackgroundTasks: %s",
                exc,
            )
    background_tasks.add_task(_process_document, doc_id, file_path)


@router.post("/upload", response_model=DocumentResponse)
def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    validated = validate_and_hash(file, max_bytes=settings.max_file_size_bytes)

    existing = (
        db.query(Document)
        .filter(Document.file_hash == validated.file_hash)
        .first()
    )
    if existing:
        raise HTTPException(
            409,
            f"เอกสารนี้เคยอัปโหลดแล้ว (ชื่อไฟล์เดิม: {existing.filename})",
        )

    doc_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename or "")[1].lower()
    filename = f"{doc_id}{ext}"
    file_path = os.path.join(settings.upload_dir, filename)
    save_bytes(file_path, validated.data)

    doc = Document(
        id=doc_id,
        filename=file.filename or filename,
        file_path=file_path,
        file_type=validated.file_type,
        file_hash=validated.file_hash,
        status="processing",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    logger.info(
        "Document %s uploaded: %s (%d bytes, %s)",
        doc_id,
        file.filename,
        validated.size,
        validated.file_type,
    )

    _enqueue_processing(doc_id, file_path, background_tasks)

    return doc


def _apply_filters(query, status, search, date_from, date_to, category=None):
    """Apply common filters to a Document query."""
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


@router.get("", response_model=list[DocumentListItem])
def list_documents(
    skip: int = 0,
    limit: int = 50,
    status: str | None = None,
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    category: str | None = None,
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

    rows = (
        query
        .add_columns(item_count_sub)
        .order_by(Document.uploaded_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return [
        DocumentListItem(
            id=d.id,
            filename=d.filename,
            status=d.status,
            uploaded_at=d.uploaded_at,
            merchant_name=d.merchant_name,
            merchant_normalized=d.merchant_normalized,
            grand_total=float(d.grand_total) if d.grand_total is not None else None,
            category=d.category,
            confidence=d.confidence,
            needs_review=d.needs_review,
            item_count=item_count,
            fraud_flags=d.fraud_flags,
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


@router.get("/{doc_id}", response_model=DocumentResponse)
def get_document(doc_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
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
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(doc, field, value)
    db.commit()
    db.refresh(doc)
    logger.info("Document %s updated", doc_id)
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
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    doc = db.query(Document).filter(Document.id == doc_id).first()
    db.refresh(doc)
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
    db.delete(item)
    db.commit()
    doc = db.query(Document).filter(Document.id == doc_id).first()
    db.refresh(doc)
    logger.info("Item %s deleted from document %s", item_id, doc_id)
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
    _enqueue_processing(doc_id, doc.file_path, background_tasks)
    return doc


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
    return doc


@router.delete("/{doc_id}")
def delete_document(doc_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "ไม่พบเอกสาร")
    if os.path.exists(doc.file_path):
        os.remove(doc.file_path)
    db.delete(doc)
    db.commit()
    logger.info("Document %s deleted", doc_id)
    return {"message": "ลบเอกสารเรียบร้อย"}


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
