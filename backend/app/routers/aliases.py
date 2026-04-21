"""Learned alias admin endpoints.

Aliases are created implicitly when users edit documents (see
``documents.update_document``) or items (see ``documents.update_item``).
These endpoints let the UI show what the system has learned and let an
operator remove incorrect entries. Two resources:

* ``/`` — merchant aliases (document-level corrections)
* ``/products`` — product aliases (item-level corrections)

``/stats`` returns a combined view so the badge in the header can show a
single learned count.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import MerchantAlias, ProductAlias

router = APIRouter()


class AliasOut(BaseModel):
    id: str
    source_text: str
    canonical_name: str
    category: str | None = None
    hit_count: int

    model_config = {"from_attributes": True}


class AliasKindStats(BaseModel):
    total_aliases: int
    total_hits: int


class AliasStats(BaseModel):
    total_aliases: int
    total_hits: int
    merchants: AliasKindStats
    products: AliasKindStats


# ----- Merchant aliases -----


@router.get("", response_model=list[AliasOut])
def list_aliases(
    limit: int = 100,
    db: Session = Depends(get_db),
):
    rows = (
        db.query(MerchantAlias)
        .order_by(MerchantAlias.hit_count.desc(), MerchantAlias.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [
        AliasOut(
            id=r.id,
            source_text=r.source_text,
            canonical_name=r.canonical_name,
            category=r.category,
            hit_count=int(r.hit_count or 0),
        )
        for r in rows
    ]


@router.get("/stats", response_model=AliasStats)
def alias_stats(db: Session = Depends(get_db)):
    merchants = db.query(MerchantAlias).all()
    products = db.query(ProductAlias).all()
    m_hits = sum(int(r.hit_count or 0) for r in merchants)
    p_hits = sum(int(r.hit_count or 0) for r in products)
    return AliasStats(
        total_aliases=len(merchants) + len(products),
        total_hits=m_hits + p_hits,
        merchants=AliasKindStats(total_aliases=len(merchants), total_hits=m_hits),
        products=AliasKindStats(total_aliases=len(products), total_hits=p_hits),
    )


@router.delete("/{alias_id}")
def delete_alias(alias_id: str, db: Session = Depends(get_db)):
    alias = db.query(MerchantAlias).filter(MerchantAlias.id == alias_id).first()
    if not alias:
        raise HTTPException(404, "ไม่พบรายการที่เรียนรู้")
    db.delete(alias)
    db.commit()
    return {"status": "ok"}


# ----- Product aliases -----


@router.get("/products", response_model=list[AliasOut])
def list_product_aliases(
    limit: int = 100,
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ProductAlias)
        .order_by(ProductAlias.hit_count.desc(), ProductAlias.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [
        AliasOut(
            id=r.id,
            source_text=r.source_text,
            canonical_name=r.canonical_name,
            category=r.category,
            hit_count=int(r.hit_count or 0),
        )
        for r in rows
    ]


@router.delete("/products/{alias_id}")
def delete_product_alias(alias_id: str, db: Session = Depends(get_db)):
    alias = db.query(ProductAlias).filter(ProductAlias.id == alias_id).first()
    if not alias:
        raise HTTPException(404, "ไม่พบรายการที่เรียนรู้")
    db.delete(alias)
    db.commit()
    return {"status": "ok"}
