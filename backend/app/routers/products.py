"""Product catalog admin endpoints.

Read-only for now (list/search). Write endpoints can be added when an admin
UI lands; the seed script handles the initial import from singhaonline.com.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.catalog import search_names

logger = logging.getLogger(__name__)

router = APIRouter()


class ProductOut(BaseModel):
    id: str
    code: str | None = None
    canonical_name: str
    display_name: str | None = None
    name_en: str | None = None
    brand_th: str | None = None
    category: str | None = None
    sub_category: str | None = None
    size: str | None = None
    unit: str | None = None
    aliases: list[str] = []
    price: float | None = None
    manufacturer: str | None = None
    active: bool = True

    model_config = {"from_attributes": True}


@router.get("", response_model=list[ProductOut])
def list_products(
    q: str = "",
    category: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    rows = search_names(db, q, limit=limit, category=category)
    out: list[ProductOut] = []
    for p in rows:
        try:
            aliases = json.loads(p.aliases) if p.aliases else []
        except (TypeError, ValueError):
            aliases = []
        out.append(
            ProductOut(
                id=p.id,
                code=p.code,
                canonical_name=p.canonical_name,
                display_name=p.display_name,
                name_en=p.name_en,
                brand_th=p.brand_th,
                category=p.category,
                sub_category=p.sub_category,
                size=p.size,
                unit=p.unit,
                aliases=aliases,
                price=float(p.price) if p.price is not None else None,
                manufacturer=p.manufacturer,
                active=bool(p.active),
            )
        )
    return out


class ProductStats(BaseModel):
    total: int
    active: int
    by_category: dict[str, int]


@router.get("/stats", response_model=ProductStats)
def product_stats(db: Session = Depends(get_db)):
    from ..models import Product  # local import to avoid cycle

    rows = db.query(Product).all()
    active = sum(1 for r in rows if r.active)
    by_cat: dict[str, int] = {}
    for r in rows:
        if not r.active:
            continue
        cat = r.category or "สินค้าอื่นๆ"
        by_cat[cat] = by_cat.get(cat, 0) + 1
    return ProductStats(total=len(rows), active=active, by_category=by_cat)
