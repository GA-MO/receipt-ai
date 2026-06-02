"""Backfill document_items.unit from the catalog's canonical SELLING unit.

For every item that matched a catalog SKU (has a product_code), overwrite the
per-document unit the model guessed with the SKU's selling unit (ลัง/ถาด/แพ็ค/…)
so a visit aggregate never mixes a single ขวด with a ลัง. Quantities are left
untouched — only the unit label is corrected. Off-catalog items are skipped.

    cd backend && .venv/bin/python ../scripts/backfill_units.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.models import DocumentItem  # noqa: E402
from app.services import catalog  # noqa: E402


def main() -> None:
    dry = "--dry-run" in sys.argv
    db = SessionLocal()
    catalog.prompt_catalog_entries()  # warm caches
    changed = 0
    skipped_no_unit = 0
    items = db.query(DocumentItem).filter(DocumentItem.product_code.isnot(None)).all()
    for it in items:
        target = catalog.selling_unit_by_code(it.product_code)
        if not target:
            skipped_no_unit += 1
            continue
        if (it.unit or "") != target:
            print(f"  {it.product_name_normalized!r:28} {it.unit!r:10} -> {target!r}")
            it.unit = target
            changed += 1
    if dry:
        print(f"\n[dry-run] would change {changed} item(s); "
              f"{skipped_no_unit} coded item(s) have no derivable selling unit")
        db.rollback()
    else:
        db.commit()
        print(f"\nupdated {changed} item(s); "
              f"{skipped_no_unit} coded item(s) had no derivable selling unit")
    db.close()


if __name__ == "__main__":
    main()
