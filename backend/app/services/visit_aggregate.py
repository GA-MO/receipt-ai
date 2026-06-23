"""Compute the visit aggregate — `(product, qty)` rolled up across docs."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from sqlalchemy.orm import Session

from ..models import Document, DocumentItem, Product
from ..schemas import VisitAggregateRow
from .catalog import _norm


def _group_key(item: DocumentItem) -> tuple[str, str, str]:
    """Return ``(kind, key, unit)`` — catalog SKU wins, else normalized name.

    Unit is part of the key so quantities are NEVER summed across different
    units (e.g. ``2 ลัง`` + ``3 ขวด`` must stay two rows, not become ``5``).
    Catalog items are forced to one selling unit upstream, so they don't split;
    only genuinely mixed-unit off-catalog lines fan out into separate rows.
    """
    unit = _norm(item.unit or "")
    if item.product_code:
        return ("sku", item.product_code, unit)
    name = item.product_name_normalized or item.product_name_raw or "?"
    return ("name", _norm(name), unit)


def _live_docs(visit_id: str, db: Session, *, date_from=None, date_to=None) -> list[Document]:
    q = db.query(Document).filter(
        Document.visit_id == visit_id,
        Document.deleted_at.is_(None),
    )
    if date_from:
        q = q.filter(Document.document_date >= date_from)
    if date_to:
        q = q.filter(Document.document_date <= date_to)
    return q.order_by(Document.document_date.desc(), Document.uploaded_at.desc()).all()


def aggregate_visit(
    db: Session,
    visit_id: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[VisitAggregateRow]:
    """Group all DocumentItems belonging to the Visit's live docs.

    Grouping precedence:
    1. ``product_code`` (catalog match)
    2. Normalized ``product_name_normalized`` (case+whitespace folded)

    The unit reported is the most common unit among contributors; if multiple
    distinct units appear, ``units_seen`` contains all of them so the caller
    can surface a warning.
    """
    docs = _live_docs(visit_id, db, date_from=date_from, date_to=date_to)
    if not docs:
        return []

    # Pre-load product metadata for any SKUs we'll show, so we can attach
    # manufacturer + display_name without N+1 queries.
    item_lists: list[Iterable[DocumentItem]] = [list(d.items or []) for d in docs]
    all_codes = {it.product_code for items in item_lists for it in items if it.product_code}
    products_by_code: dict[str, Product] = {}
    if all_codes:
        for p in db.query(Product).filter(Product.code.in_(all_codes)).all():
            products_by_code[p.code] = p

    groups: dict[tuple[str, str], dict] = defaultdict(
        lambda: {
            "product_code": None,
            "display_name": "",
            "manufacturer": None,
            "is_catalog_match": False,
            "total_quantity": 0.0,
            "units": Counter(),
            "names": Counter(),
            "source_doc_ids": [],
        }
    )

    for doc, items in zip(docs, item_lists):
        for it in items:
            key = _group_key(it)
            bucket = groups[key]
            qty = float(it.quantity or 0)
            bucket["total_quantity"] += qty
            if it.unit:
                bucket["units"][it.unit] += 1
            display_candidate = it.product_name_normalized or it.product_name_raw or "?"
            bucket["names"][display_candidate] += 1
            if doc.id not in bucket["source_doc_ids"]:
                bucket["source_doc_ids"].append(doc.id)

            if key[0] == "sku":
                bucket["product_code"] = it.product_code
                product = products_by_code.get(it.product_code)
                if product:
                    bucket["display_name"] = product.display_name or product.canonical_name or display_candidate
                    bucket["manufacturer"] = product.manufacturer
                    bucket["is_catalog_match"] = True

    rows: list[VisitAggregateRow] = []
    for bucket in groups.values():
        if not bucket["is_catalog_match"]:
            # For unknown items, take the most common surface form as display.
            bucket["display_name"] = bucket["names"].most_common(1)[0][0]
        unit_list = [u for u, _ in bucket["units"].most_common()]
        rows.append(
            VisitAggregateRow(
                product_code=bucket["product_code"],
                display_name=bucket["display_name"],
                manufacturer=bucket["manufacturer"],
                is_catalog_match=bucket["is_catalog_match"],
                total_quantity=round(bucket["total_quantity"], 3),
                unit=unit_list[0] if unit_list else None,
                source_doc_ids=bucket["source_doc_ids"],
                source_count=len(bucket["source_doc_ids"]),
                units_seen=unit_list,
            )
        )

    rows.sort(key=lambda r: r.total_quantity, reverse=True)
    return rows
