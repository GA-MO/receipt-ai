"""Deactivate pack-multiplier variants from the product catalog.

singhaonline.com lists the same SKU multiple times at different pack
quantities (e.g. "... จำนวน 1 แพ็ก", "... จำนวน 6 แพ็ก", "... จำนวน 10 แพ็ก").
For receipt matching and autocomplete we only want ONE canonical entry per
product — the smallest pack (N=1) or the unitless base name.

Rows are soft-deactivated (``active=False``) rather than deleted so the
original singhaonline seed can still be re-applied later.

Usage:
    cd backend && .venv/bin/python -m app.scripts.prune_pack_variants        # preview
    cd backend && .venv/bin/python -m app.scripts.prune_pack_variants --apply
"""

from __future__ import annotations

import argparse
import logging
import re

from ..database import SessionLocal
from ..models import Product

logger = logging.getLogger(__name__)


# Patterns that indicate a "bundle multiplier": capturing group = count.
# A match with count > 1 means this row is a pack variant of a smaller SKU.
# Each pattern is written to avoid matching volume specifiers (e.g. "6x1.5L")
# by requiring a Thai unit word (ถาด / ลัง / แพ็ก / ชิ้น).
_PACK_PATTERNS = (
    # Explicit "จำนวน N <unit>" (Singha's preferred phrasing) — both
    # "แพ็ก" and "แพ็ค" spellings occur in the wild.
    re.compile(r"จำนวน\s+(\d+)\s*(?:แพ็[กค]|ลัง|ถาด|ชิ้น)"),
    # "x N แพ็ก/แพ็ค" inside a size spec, e.g. "(1.5 ล. x 8 ขวด x 6 แพ็ค)"
    re.compile(r"x\s*(\d+)\s*แพ็[กค]"),
    # Bare "N ถาด/ลัง/ชิ้น (…)" before a parenthesised size
    re.compile(r"(?:^|\s)(\d+)\s+(?:ถาด|ลัง|ชิ้น)\s*\("),
    # Bare "N ถาด/ลัง/ชิ้น" at end of string
    re.compile(r"(?:^|\s)(\d+)\s+(?:ถาด|ลัง|ชิ้น)\s*$"),
    # "…สูตร… N ลัง" tail (catches "สูตรหวานน้อย 2 ลัง" variants)
    re.compile(r"สูตร[^()]+?\s+(\d+)\s+(?:ถาด|ลัง)"),
)


def pack_quantity(name: str) -> int:
    """Return the bundle multiplier embedded in ``name``, or 0 if none.

    Picks the FIRST matching pattern — the order above puts unambiguous
    "จำนวน N แพ็ก/ลัง" first so we catch those before the looser "N ถาด"
    match that can occasionally appear in base names.
    """
    for p in _PACK_PATTERNS:
        m = p.search(name)
        if m:
            try:
                return int(m.group(1))
            except (TypeError, ValueError):
                continue
    return 0


def is_multi_pack(name: str) -> bool:
    return pack_quantity(name) > 1


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually deactivate (default: dry-run)")
    parser.add_argument("--delete", action="store_true", help="Hard delete instead of deactivate (use with --apply)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        active_rows = db.query(Product).filter(Product.active.is_(True)).all()
        to_prune = [r for r in active_rows if is_multi_pack(r.canonical_name)]

        logger.info("Scanned %d active products; %d are pack-variants", len(active_rows), len(to_prune))
        for r in to_prune[:20]:
            logger.info("  [%s qty=%d] %s", r.code, pack_quantity(r.canonical_name), r.canonical_name)
        if len(to_prune) > 20:
            logger.info("  ... and %d more", len(to_prune) - 20)

        if not args.apply:
            logger.info("Dry run — pass --apply to deactivate. --apply --delete to hard delete.")
            return

        if args.delete:
            for r in to_prune:
                db.delete(r)
            db.commit()
            logger.info("Hard-deleted %d pack-variant rows", len(to_prune))
        else:
            for r in to_prune:
                r.active = False
            db.commit()
            logger.info("Deactivated %d pack-variant rows", len(to_prune))

        # Invalidate the catalog cache so next lookup rebuilds without them.
        from ..services.catalog import invalidate_cache
        invalidate_cache()
    finally:
        db.close()


if __name__ == "__main__":
    main()
