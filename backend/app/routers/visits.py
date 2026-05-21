"""Visit endpoints — group documents collected during one store visit.

A Visit is a light grouping; the store identity = ``Document.merchant_normalized``.
The aggregate (product × qty rolled up across all docs in the visit) is computed
on demand via :mod:`app.services.visit_aggregate`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
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
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ..config import settings
from ..database import get_db
from ..events import event_bus
from ..models import Document, DocumentItem, Store, Visit
from ..schemas import (
    DocumentListItem,
    VisitCreate,
    VisitDetail,
    VisitListItem,
    VisitUpdate,
)
from ..services.audit import record as record_event
from ..services.storage import save_bytes, validate_and_hash
from ..services.visit_aggregate import aggregate_visit
from ..services.visits import recompute_store_label, visit_doc_date_range
from .documents import _enqueue_processing

logger = logging.getLogger(__name__)

router = APIRouter()


def _doc_count_subquery():
    return (
        select(func.count(Document.id))
        .where(Document.visit_id == Visit.id, Document.deleted_at.is_(None))
        .correlate(Visit)
        .scalar_subquery()
        .label("document_count")
    )


def _earliest_date_sub():
    return (
        select(func.min(Document.document_date))
        .where(Document.visit_id == Visit.id, Document.deleted_at.is_(None))
        .correlate(Visit)
        .scalar_subquery()
        .label("earliest_doc_date")
    )


def _latest_date_sub():
    return (
        select(func.max(Document.document_date))
        .where(Document.visit_id == Visit.id, Document.deleted_at.is_(None))
        .correlate(Visit)
        .scalar_subquery()
        .label("latest_doc_date")
    )


def _reviewed_count_sub():
    return (
        select(func.count(Document.id))
        .where(
            Document.visit_id == Visit.id,
            Document.deleted_at.is_(None),
            Document.status == "reviewed",
        )
        .correlate(Visit)
        .scalar_subquery()
        .label("reviewed_count")
    )


def _to_list_item(
    visit: Visit,
    doc_count: int,
    earliest: str | None,
    latest: str | None,
    reviewed_count: int = 0,
) -> VisitListItem:
    return VisitListItem(
        id=visit.id,
        store_id=visit.store_id,
        store_key=visit.store_key,
        store_label=visit.store_label,
        rep_name=visit.rep_name,
        notes=visit.notes,
        created_at=visit.created_at,
        updated_at=visit.updated_at,
        document_count=doc_count,
        reviewed_count=reviewed_count,
        earliest_doc_date=earliest,
        latest_doc_date=latest,
    )


def _doc_to_list_item(doc: Document, item_count: int) -> DocumentListItem:
    return DocumentListItem(
        id=doc.id,
        filename=doc.filename,
        file_type=doc.file_type,
        status=doc.status,
        uploaded_at=doc.uploaded_at,
        merchant_name=doc.merchant_name,
        merchant_normalized=doc.merchant_normalized,
        grand_total=float(doc.grand_total) if doc.grand_total is not None else None,
        category=doc.category,
        confidence=doc.confidence,
        needs_review=doc.needs_review,
        item_count=item_count,
        fraud_flags=doc.fraud_flags,
        visit_id=doc.visit_id,
    )


@router.post("", response_model=VisitListItem)
def create_visit(body: VisitCreate, db: Session = Depends(get_db)):
    store_id = body.store_id
    store_label = body.store_label
    store_key = None
    if store_id:
        store = db.query(Store).filter(Store.id == store_id).first()
        if not store:
            raise HTTPException(404, f"Store {store_id} not found")
        store_label = store_label or store.name
        store_key = store.normalized_name or store.name
    visit = Visit(
        id=str(uuid.uuid4()),
        store_id=store_id,
        store_key=store_key,
        store_label=store_label,
        rep_name=body.rep_name,
        notes=body.notes,
    )
    db.add(visit)
    db.commit()
    db.refresh(visit)
    return _to_list_item(visit, 0, None, None, 0)


@router.get("", response_model=list[VisitListItem])
def list_visits(
    skip: int = 0,
    limit: int = 50,
    store_id: str | None = None,
    store_key: str | None = None,
    rep_name: str | None = None,
    db: Session = Depends(get_db),
):
    doc_count = _doc_count_subquery()
    reviewed = _reviewed_count_sub()
    earliest = _earliest_date_sub()
    latest = _latest_date_sub()

    q = (
        db.query(Visit, doc_count, reviewed, earliest, latest)
        .filter(Visit.deleted_at.is_(None))
    )
    if store_id:
        q = q.filter(Visit.store_id == store_id)
    if store_key:
        q = q.filter(Visit.store_key == store_key)
    if rep_name:
        q = q.filter(Visit.rep_name == rep_name)

    rows = (
        q.order_by(Visit.updated_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [_to_list_item(v, c or 0, e, l, r or 0) for v, c, r, e, l in rows]


@router.get("/{visit_id}", response_model=VisitDetail)
def get_visit(
    visit_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
):
    visit = (
        db.query(Visit)
        .filter(Visit.id == visit_id, Visit.deleted_at.is_(None))
        .first()
    )
    if not visit:
        raise HTTPException(404, "Visit not found")

    item_count_sub = (
        select(func.count(DocumentItem.id))
        .where(DocumentItem.document_id == Document.id)
        .correlate(Document)
        .scalar_subquery()
        .label("item_count")
    )
    doc_rows = (
        db.query(Document, item_count_sub)
        .filter(Document.visit_id == visit_id, Document.deleted_at.is_(None))
        .order_by(Document.document_date.desc().nullslast(), Document.uploaded_at.desc())
        .all()
    )
    reviewed_count = sum(1 for d, _ in doc_rows if d.status == "reviewed")

    return VisitDetail(
        id=visit.id,
        store_id=visit.store_id,
        store_key=visit.store_key,
        store_label=visit.store_label,
        rep_name=visit.rep_name,
        notes=visit.notes,
        created_at=visit.created_at,
        updated_at=visit.updated_at,
        documents=[_doc_to_list_item(d, c or 0) for d, c in doc_rows],
        aggregate=aggregate_visit(db, visit_id, date_from=date_from, date_to=date_to),
        reviewed_count=reviewed_count,
    )


@router.patch("/{visit_id}", response_model=VisitListItem)
def update_visit(visit_id: str, body: VisitUpdate, db: Session = Depends(get_db)):
    visit = (
        db.query(Visit)
        .filter(Visit.id == visit_id, Visit.deleted_at.is_(None))
        .first()
    )
    if not visit:
        raise HTTPException(404, "Visit not found")

    if body.store_id is not None:
        store = db.query(Store).filter(Store.id == body.store_id).first()
        if not store:
            raise HTTPException(404, f"Store {body.store_id} not found")
        visit.store_id = store.id
        visit.store_key = store.normalized_name or store.name
        if visit.store_label is None or visit.store_label == "":
            visit.store_label = store.name
    if body.store_label is not None:
        visit.store_label = body.store_label
    if body.store_key is not None:
        visit.store_key = body.store_key
    if body.rep_name is not None:
        visit.rep_name = body.rep_name
    if body.notes is not None:
        visit.notes = body.notes
    db.commit()
    db.refresh(visit)
    doc_count = (
        db.query(func.count(Document.id))
        .filter(Document.visit_id == visit_id, Document.deleted_at.is_(None))
        .scalar()
        or 0
    )
    reviewed = (
        db.query(func.count(Document.id))
        .filter(
            Document.visit_id == visit_id,
            Document.deleted_at.is_(None),
            Document.status == "reviewed",
        )
        .scalar()
        or 0
    )
    earliest, latest = visit_doc_date_range(db, visit_id)
    return _to_list_item(visit, doc_count, earliest, latest, reviewed)


@router.delete("/{visit_id}")
def delete_visit(visit_id: str, db: Session = Depends(get_db)):
    """Soft-delete a Visit. Its documents stay (their visit_id is left dangling
    so they appear in the "All documents" view as orphans). Use
    ``PATCH /api/documents/{id}`` to move docs to another Visit if needed."""
    visit = (
        db.query(Visit)
        .filter(Visit.id == visit_id, Visit.deleted_at.is_(None))
        .first()
    )
    if not visit:
        raise HTTPException(404, "Visit not found")
    visit.deleted_at = datetime.now(UTC)
    db.commit()
    return {"id": visit_id, "deleted_at": visit.deleted_at.isoformat()}


@router.post("/{visit_id}/documents")
def upload_documents_to_visit(
    visit_id: str,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Bulk upload multiple receipt images to a Visit, queue extraction."""
    visit = (
        db.query(Visit)
        .filter(Visit.id == visit_id, Visit.deleted_at.is_(None))
        .first()
    )
    if not visit:
        raise HTTPException(404, "Visit not found")

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
            visit_id=visit_id,
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
                "visit_id": visit_id,
            },
        )
        _enqueue_processing(doc_id, file_path, background_tasks)
        created_ids.append(doc_id)

    visit.updated_at = datetime.now(UTC)
    db.commit()

    return {
        "visit_id": visit_id,
        "document_ids": created_ids,
        "duplicates": duplicates,
        "failures": failures,
    }


@router.post("/{visit_id}/recompute-label")
def recompute_label(visit_id: str, db: Session = Depends(get_db)):
    """After all docs in a visit settle, pick a sensible store_label/store_key."""
    visit = (
        db.query(Visit)
        .filter(Visit.id == visit_id, Visit.deleted_at.is_(None))
        .first()
    )
    if not visit:
        raise HTTPException(404, "Visit not found")
    recompute_store_label(db, visit)
    db.commit()
    db.refresh(visit)
    return {
        "id": visit.id,
        "store_key": visit.store_key,
        "store_label": visit.store_label,
    }


@router.get("/{visit_id}/stream")
async def stream_visit(visit_id: str, request: Request, db: Session = Depends(get_db)):
    """SSE — emits one event per doc in the Visit when its status changes.

    Subscribes to every doc's stream on connect and re-checks for new docs every
    couple of seconds (cheap query). Each event is ``{doc_id, status, ...}``.
    """
    visit = (
        db.query(Visit)
        .filter(Visit.id == visit_id, Visit.deleted_at.is_(None))
        .first()
    )
    if not visit:
        raise HTTPException(404, "Visit not found")

    async def _drain(doc_id: str, queue: asyncio.Queue):
        async for payload in event_bus.subscribe(doc_id):
            await queue.put({"doc_id": doc_id, **payload})

    async def event_gen():
        from ..database import SessionLocal as _Session

        queue: asyncio.Queue = asyncio.Queue(maxsize=128)
        tasks: dict[str, asyncio.Task] = {}

        def _doc_ids() -> set[str]:
            session = _Session()
            try:
                return {
                    row[0]
                    for row in session.query(Document.id)
                    .filter(Document.visit_id == visit_id, Document.deleted_at.is_(None))
                    .all()
                }
            finally:
                session.close()

        def _subscribe_missing():
            for doc_id in _doc_ids() - set(tasks):
                tasks[doc_id] = asyncio.create_task(_drain(doc_id, queue))

        try:
            _subscribe_missing()
            while not await request.is_disconnected():
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=2.0)
                    yield {"event": "doc-update", "data": json.dumps(msg)}
                except asyncio.TimeoutError:
                    _subscribe_missing()
        finally:
            for t in tasks.values():
                t.cancel()

    return EventSourceResponse(event_gen())
