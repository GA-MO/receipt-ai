"""Stores master-data router.

The stores table is admin-managed and serves as the picker when creating a
Visit. ``GET /api/stores?q=...`` powers the visit-form autocomplete.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Store, Visit
from ..schemas import StoreCreate, StoreListItem, StoreUpdate

logger = logging.getLogger(__name__)

router = APIRouter()


def _serialize(store: Store, visit_count: int) -> StoreListItem:
    return StoreListItem(
        id=store.id,
        code=store.code,
        name=store.name,
        normalized_name=store.normalized_name,
        address=store.address,
        notes=store.notes,
        active=bool(store.active),
        created_at=store.created_at,
        updated_at=store.updated_at,
        visit_count=visit_count,
    )


def _visit_count_sub():
    return (
        select(func.count(Visit.id))
        .where(Visit.store_id == Store.id, Visit.deleted_at.is_(None))
        .correlate(Store)
        .scalar_subquery()
        .label("visit_count")
    )


@router.get("", response_model=list[StoreListItem])
def list_stores(
    q: str | None = None,
    include_inactive: bool = False,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    sub = _visit_count_sub()
    query = db.query(Store, sub)
    if not include_inactive:
        query = query.filter(Store.active.is_(True))
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            Store.name.ilike(pattern)
            | Store.normalized_name.ilike(pattern)
            | Store.code.ilike(pattern)
        )
    rows = query.order_by(Store.name).limit(limit).all()
    return [_serialize(s, c or 0) for s, c in rows]


@router.post("", response_model=StoreListItem)
def create_store(body: StoreCreate, db: Session = Depends(get_db)):
    if not body.name.strip():
        raise HTTPException(400, "name is required")
    if body.code:
        clash = db.query(Store).filter(Store.code == body.code).first()
        if clash:
            raise HTTPException(409, f"code {body.code} already exists")
    store = Store(
        id=str(uuid.uuid4()),
        name=body.name.strip(),
        code=(body.code or None),
        normalized_name=(body.normalized_name or body.name).strip(),
        address=body.address,
        notes=body.notes,
        active=True,
    )
    db.add(store)
    db.commit()
    db.refresh(store)
    return _serialize(store, 0)


@router.get("/{store_id}", response_model=StoreListItem)
def get_store(store_id: str, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(404, "Store not found")
    count = (
        db.query(func.count(Visit.id))
        .filter(Visit.store_id == store_id, Visit.deleted_at.is_(None))
        .scalar()
        or 0
    )
    return _serialize(store, count)


@router.patch("/{store_id}", response_model=StoreListItem)
def update_store(store_id: str, body: StoreUpdate, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(404, "Store not found")
    if body.code and body.code != store.code:
        clash = (
            db.query(Store)
            .filter(Store.code == body.code, Store.id != store_id)
            .first()
        )
        if clash:
            raise HTTPException(409, f"code {body.code} already exists")
    for field in ("name", "code", "normalized_name", "address", "notes", "active"):
        value = getattr(body, field)
        if value is not None:
            setattr(store, field, value)
    store.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(store)
    count = (
        db.query(func.count(Visit.id))
        .filter(Visit.store_id == store_id, Visit.deleted_at.is_(None))
        .scalar()
        or 0
    )
    return _serialize(store, count)


@router.delete("/{store_id}")
def delete_store(store_id: str, db: Session = Depends(get_db)):
    """Hard delete only when no visits link to it; otherwise mark inactive."""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(404, "Store not found")
    has_visits = (
        db.query(func.count(Visit.id))
        .filter(Visit.store_id == store_id)
        .scalar()
        or 0
    )
    if has_visits:
        store.active = False
        store.updated_at = datetime.now(UTC)
        db.commit()
        return {"id": store_id, "status": "deactivated", "visit_count": has_visits}
    db.delete(store)
    db.commit()
    return {"id": store_id, "status": "deleted"}
