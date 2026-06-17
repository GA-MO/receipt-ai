"""Seed ``products`` table from a singhaonline.com API dump.

Usage:
    cd backend && .venv/bin/python -m app.scripts.seed_products

Idempotent: upserts by ``code`` so running twice updates existing rows rather
than duplicating. Pass ``--wipe`` to delete existing rows first.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Product

logger = logging.getLogger(__name__)

_CATALOG_PATH = Path(__file__).parent / "singha_catalog.json"
# Extra SKUs (beer, spirits) that Singha Online does not list but receipts
# routinely contain. Structured identically to the public dump.
_INTERNAL_CATALOG_PATH = Path(__file__).parent / "internal_catalog.json"


def _derive_category(path_th: list[str] | None) -> str | None:
    """Top-level category from ``pathCategoryNameTH``.

    Shape is ``["สินค้า/เครื่องดื่ม/น้ำดื่มสิงห์"]`` — split on "/" and take
    element at index 1 to get "เครื่องดื่ม" (maps to our taxonomy).
    """
    if not path_th:
        return None
    parts = path_th[0].split("/")
    if len(parts) >= 2:
        return parts[1].strip()
    return None


def _derive_sub_category(path_th: list[str] | None) -> str | None:
    if not path_th:
        return None
    parts = path_th[0].split("/")
    if len(parts) >= 3:
        return parts[2].strip()
    return None


def _load_catalog_file(path: Path) -> list[dict]:
    if not path.exists():
        logger.warning("Catalog seed file %s not found — skipping", path)
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("result", {}).get("products", []) or []


def seed(db: Session, *, wipe: bool = False, path: Path | None = None) -> dict[str, int]:
    """Upsert products from the bundled Singha Online + internal catalog.

    Merges two files at read time:
      1. ``singha_catalog.json`` — scraped from singhaonline.com (~207 SKUs)
      2. ``internal_catalog.json`` — beer & spirits not on the public site

    Safe to call at startup — skips rows whose ``canonical_name`` collides
    within the same run and updates existing rows keyed by ``code``.
    """
    products = _load_catalog_file(path or _CATALOG_PATH)
    products.extend(_load_catalog_file(_INTERNAL_CATALOG_PATH))
    if not products:
        return {"inserted": 0, "updated": 0, "skipped_dup": 0}

    if wipe:
        n = db.query(Product).delete()
        db.commit()
        logger.info("Wiped %d existing rows", n)

    now = datetime.now(UTC)
    inserted = updated = skipped = 0
    seen_names: set[str] = set()

    for p in products:
        code = p.get("productCode")
        name_th = (p.get("nameTH") or "").strip()
        if not code or not name_th:
            continue
        if name_th in seen_names:
            skipped += 1
            continue
        seen_names.add(name_th)

        existing = db.query(Product).filter(Product.code == code).first()
        row = existing or Product(code=code)
        row.canonical_name = name_th
        row.name_en = (p.get("nameEN") or "").strip() or None
        row.brand_th = (p.get("brandNameTH") or "").strip() or None
        row.brand_en = (p.get("brandNameEN") or "").strip() or None
        row.category = _derive_category(p.get("pathCategoryNameTH"))
        row.sub_category = _derive_sub_category(p.get("pathCategoryNameTH"))
        row.size = (p.get("sizeTH") or "").strip() or None
        row.unit = (p.get("unitNameTH") or "").strip() or None
        aliases = p.get("tags") or []
        row.aliases = json.dumps(aliases, ensure_ascii=False) if aliases else None
        try:
            row.price = float(p.get("price")) if p.get("price") is not None else None
        except (TypeError, ValueError):
            row.price = None
        row.product_type = p.get("productType")
        row.source = "internal" if str(code).startswith("INT-") else "singhaonline"
        # Everything on singhaonline.com is Boonrawd-owned. Internal rows
        # may override with the actual producer (ThaiBev, Diageo, …) for
        # competitor tracking.
        row.manufacturer = p.get("manufacturer") or (
            "Boonrawd" if row.source == "singhaonline" else "Boonrawd"
        )
        row.active = p.get("activate") == "Y"
        row.updated_at = now
        if existing:
            updated += 1
        else:
            row.created_at = now
            db.add(row)
            inserted += 1

    db.commit()

    # Compute display_name across all active rows so groupings reflect the
    # full catalog, not just this batch.
    _recompute_display_names(db)

    return {"inserted": inserted, "updated": updated, "skipped_dup": skipped}


def _recompute_display_names(db: Session) -> None:
    """Rebuild ``products.display_name`` across the whole table.

    Called after any seed/import. Cheap for the current ~200-row catalog;
    if it grows large move to batched updates.
    """
    from ..services.catalog import build_display_names, invalidate_cache

    rows = db.query(Product).all()
    pairs = [(p.id, p.canonical_name) for p in rows if p.canonical_name]
    mapping = build_display_names(pairs)
    for p in rows:
        desired = mapping.get(p.id)
        if desired and desired != p.display_name:
            p.display_name = desired
    db.commit()
    invalidate_cache()
    logger.info("Recomputed display_name for %d products", len(pairs))


def seed_if_empty(db: Session) -> int:
    """Auto-seed on startup if the table is empty. Returns rows added.

    The bundled ``singha_catalog.json`` has already been pruned of pack
    variants, curated to beverages only (หมวดเครื่องดื่ม), and further trimmed
    to SKUs a โชห่วย actually stocks (merch and premium imports like FIJI water
    removed, RTD tea/coffee dropped), so a fresh seed merged with
    ``internal_catalog.json`` yields the ~47-SKU shop-realistic catalog
    (beer, water, soda, spirits) without post-processing.
    """
    count = db.query(Product).count()
    if count > 0:
        logger.debug("products table already has %d rows — skipping auto-seed", count)
        return 0
    logger.info("products table is empty — seeding from bundled catalog")
    result = seed(db)
    logger.info(
        "Auto-seed done — inserted=%d, skipped_dup=%d",
        result["inserted"],
        result["skipped_dup"],
    )
    return result["inserted"]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--wipe", action="store_true", help="Delete all existing products first")
    parser.add_argument(
        "--file",
        default=str(_CATALOG_PATH),
        help=f"Path to singhaonline.com API dump (default: {_CATALOG_PATH})",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = seed(db, wipe=args.wipe, path=Path(args.file))
        logger.info(
            "Done — inserted=%d, updated=%d, skipped_dup=%d, total=%d",
            result["inserted"],
            result["updated"],
            result["skipped_dup"],
            result["inserted"] + result["updated"],
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
