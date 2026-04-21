"""Autocomplete suggestions for merchant and product name fields.

Merges two sources, weighting aliases higher because they represent explicit
user-confirmed canonical names:

* ``*_aliases.canonical_name`` — explicit user-set canonicals (×5 weight)
* historical values from ``documents.merchant_name`` / ``document_items.product_name_normalized``
  (×1 per occurrence)

Returns at most ``limit`` suggestions, ordered by combined frequency and
optionally filtered by ``q`` (case-insensitive substring match).
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    Document,
    DocumentItem,
    MerchantAlias,
    Product,
    ProductAlias,
)

router = APIRouter()


_ALIAS_WEIGHT = 5
# Catalog SKUs are authoritative — outrank even user-confirmed aliases.
_CATALOG_WEIGHT = 10


def _match(value: str | None, q: str) -> bool:
    if not q:
        return True
    return bool(value) and q.lower() in value.lower()


@router.get("")
def autocomplete(
    kind: str = Query(..., pattern="^(merchant|product)$"),
    q: str = "",
    limit: int = Query(20, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    counter: Counter[str] = Counter()

    if kind == "merchant":
        for row in (
            db.query(MerchantAlias.canonical_name, MerchantAlias.hit_count)
            .all()
        ):
            name = (row[0] or "").strip()
            if name and _match(name, q):
                counter[name] += max(int(row[1] or 0), 1) * _ALIAS_WEIGHT

        rows = (
            db.query(Document.merchant_name, func.count(Document.id))
            .filter(Document.merchant_name.isnot(None))
            .filter(Document.deleted_at.is_(None))
            .group_by(Document.merchant_name)
            .all()
        )
        for name, count in rows:
            name = (name or "").strip()
            if name and _match(name, q):
                counter[name] += int(count or 0)

    else:  # product
        # 1. Canonical catalog (singhaonline.com seed) — authoritative, highest weight.
        # Match against display/canonical (Thai), name_en (English), and the
        # ``aliases`` JSON blob (short codes, OCR-friendly variants) so the
        # user can pipe in ``"Silver"``, ``"SK"``, ``"SINGHA L"``, etc. and
        # still surface the right catalog entry.
        catalog_rows = (
            db.query(
                Product.display_name,
                Product.canonical_name,
                Product.name_en,
                Product.aliases,
            )
            .filter(Product.active.is_(True))
            .all()
        )
        for display, canon, name_en, aliases in catalog_rows:
            name = (display or canon or "").strip()
            if not name:
                continue
            haystacks = (name, (canon or ""), (name_en or ""), (aliases or ""))
            if not q or any(_match(h, q) for h in haystacks):
                counter[name] += _CATALOG_WEIGHT

        # 2. User-confirmed aliases.
        for row in (
            db.query(ProductAlias.canonical_name, ProductAlias.hit_count)
            .all()
        ):
            name = (row[0] or "").strip()
            if name and _match(name, q):
                counter[name] += max(int(row[1] or 0), 1) * _ALIAS_WEIGHT

        # 3. Historical product names from prior documents.
        rows = (
            db.query(DocumentItem.product_name_normalized, func.count(DocumentItem.id))
            .filter(DocumentItem.product_name_normalized.isnot(None))
            .group_by(DocumentItem.product_name_normalized)
            .all()
        )
        for name, count in rows:
            name = (name or "").strip()
            if name and _match(name, q):
                counter[name] += int(count or 0)

    return [
        {"value": name, "score": score}
        for name, score in counter.most_common(limit)
    ]
