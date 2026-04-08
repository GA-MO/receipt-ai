import hashlib
import logging
import os
import shutil
import threading
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, get_db
from ..models import Document, DocumentItem
from ..schemas import (
    DocumentItemUpdate,
    DocumentListItem,
    DocumentResponse,
    DocumentUpdate,
)
from ..services.extraction import extract_receipt
from ..services.fraud import run_fraud_detection
from ..services.validation import validate_extraction

logger = logging.getLogger(__name__)

router = APIRouter()

_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}

# Limit concurrent OCR+extraction to 1 to prevent memory exhaustion
_processing_lock = threading.Semaphore(1)


def _process_document(doc_id: str, file_path: str) -> None:
    """Background task: OCR → extract receipt data → update the document."""
    _processing_lock.acquire()
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            logger.error("Document %s not found for processing", doc_id)
            return

        # Step 1: Extract text context
        # - PDF: always try PyMuPDF text extraction (fast, no OCR needed)
        # - Images: only run PaddleOCR if OCR_ENABLED=true
        ocr_text: str | None = None
        if file_path.lower().endswith(".pdf"):
            try:
                from ..services.ocr import _extract_pdf_text

                pdf_text = _extract_pdf_text(file_path)
                if pdf_text:
                    ocr_text = pdf_text
                    doc.ocr_text = pdf_text
                    logger.info("PDF text extracted for %s: %d chars", doc_id, len(pdf_text))
            except Exception as exc:
                logger.warning("PDF text extraction failed for %s: %s", doc_id, exc)

        if settings.ocr_enabled and not ocr_text:
            try:
                from ..services.ocr import run_ocr

                ocr_result = run_ocr(file_path)
                ocr_text = ocr_result["full_text"]
                doc.ocr_text = ocr_text
                logger.info(
                    "OCR for %s: %d chars, avg confidence %.2f",
                    doc_id,
                    len(ocr_text),
                    ocr_result["avg_confidence"],
                )
            except Exception as ocr_exc:
                logger.warning("OCR failed for %s, continuing without: %s", doc_id, ocr_exc)

        # Step 2: Extract with Gemini (pass OCR text as context)
        result = extract_receipt(file_path, ocr_text=ocr_text)
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
            result.confidence < 0.9 or len(result.needs_review_fields) > 0
        )
        doc.status = "extracted"
        doc.processed_at = datetime.now(UTC)

        if warnings:
            existing = doc.notes or ""
            separator = "\n" if existing else ""
            doc.notes = existing + separator + "\n".join(f"⚠️ {w}" for w in warnings)

        for item_data in result.items:
            item = DocumentItem(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                product_name_raw=item_data.product_name_raw,
                product_name_normalized=item_data.product_name_normalized,
                quantity=item_data.quantity,
                unit=item_data.unit,
                unit_price=item_data.unit_price,
                line_total=item_data.line_total,
                confidence=result.confidence,
            )
            db.add(item)

        # Step 3: Fraud detection (flush first so doc.items is visible)
        db.flush()
        db.refresh(doc)
        try:
            doc.fraud_flags = run_fraud_detection(doc, db)
            if doc.fraud_flags:
                logger.info("Document %s flagged for fraud: %s", doc_id, doc.fraud_flags[:200])
        except Exception as fraud_exc:
            logger.warning("Fraud detection failed for %s: %s", doc_id, fraud_exc)

        db.commit()
        logger.info("Document %s processed successfully", doc_id)
    except Exception as exc:
        logger.error("Failed to process document %s: %s", doc_id, exc)
        db.rollback()
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.status = "error"
            doc.error_message = str(exc)
            db.commit()
    finally:
        db.close()
        _processing_lock.release()


def _compute_file_hash(file_path: str) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


@router.post("/upload", response_model=DocumentResponse)
def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    # Validate extension
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(400, f"ไฟล์ไม่รองรับ: {ext}")

    # Validate file size
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > settings.max_file_size_bytes:
        raise HTTPException(
            413,
            f"ไฟล์ใหญ่เกิน {settings.max_file_size_mb} MB "
            f"(ขนาดไฟล์: {size / 1024 / 1024:.1f} MB)",
        )

    # Save file
    doc_id = str(uuid.uuid4())
    filename = f"{doc_id}{ext}"
    file_path = os.path.join(settings.upload_dir, filename)

    os.makedirs(settings.upload_dir, exist_ok=True)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Check for duplicates
    file_hash = _compute_file_hash(file_path)
    existing = (
        db.query(Document)
        .filter(Document.file_hash == file_hash)
        .first()
    )
    if existing:
        os.remove(file_path)
        raise HTTPException(
            409,
            f"เอกสารนี้เคยอัปโหลดแล้ว (ชื่อไฟล์เดิม: {existing.filename})",
        )

    # Create document record
    doc = Document(
        id=doc_id,
        filename=file.filename or filename,
        file_path=file_path,
        file_type="pdf" if ext == ".pdf" else "image",
        file_hash=file_hash,
        status="processing",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    logger.info("Document %s uploaded: %s (%d bytes)", doc_id, file.filename, size)

    # Process in background
    background_tasks.add_task(_process_document, doc_id, file_path)

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
    background_tasks.add_task(_process_document, doc_id, doc.file_path)
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
