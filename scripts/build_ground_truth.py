"""Rebuild the accuracy ground truth from human-approved documents in the DB.

A document with ``status='reviewed'`` has been through the per-doc review
screen — a human confirmed every (product, quantity) line — so its items *are*
the ground truth. This dumps them into the schema `measure_accuracy.py` reads
and copies the source images into `dataTest/demo/` so the harness is
self-contained.

Usage:
    cd backend && .venv/bin/python ../scripts/build_ground_truth.py
    cd backend && .venv/bin/python ../scripts/build_ground_truth.py --dry-run
    cd backend && .venv/bin/python ../scripts/build_ground_truth.py --fill-off-catalog
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "backend" / "data" / "receipts.db"
UPLOADS = ROOT / "backend" / "uploads"
DEMO_DIR = ROOT / "dataTest" / "demo"
OUT = ROOT / "dataTest" / "ground_truth_demo.json"

# Every receipt in the current set is a handwritten cash-sale bill. Override
# per-image here if printed slips are added later.
KIND_OVERRIDES: dict[str, str] = {}
DEFAULT_KIND = "handwritten"

# Lines written on the bill but absent from the DB: the reviewer deleted every
# off-catalog line while approving (all surviving rows carry a product_code).
# Ground truth is the *paper*, not what we chose to keep — an off-catalog line
# is a catalog gap, not an extraction error — so `--fill-off-catalog` re-reads
# each image with the production extractor and restores the code-less lines it
# finds. Cheap and reproducible; a human still spot-checks the diff it prints.
# It only fills gaps: a reviewer who keeps off-catalog lines (the policy from
# 2026-09-09 on) leaves nothing to restore, and the pass adds nothing.
#
# Bias note: these restored lines come from the same model family we benchmark,
# so they only ever *add* lines a model can find. They inflate no score on their
# own — a model that misses them is still penalised — but do not read them as
# an independent transcription of the paper.


def off_catalog_lines(image: Path, existing: list[dict]) -> list[tuple[int, dict]]:
    """Re-read the bill with the production extractor; return its code-less lines.

    Lines already saved on the document are skipped, so the pass is idempotent
    and safe to re-run after a reviewer starts keeping off-catalog lines.
    Imported lazily so the plain DB dump needs no API key.
    """
    sys.path.insert(0, str(ROOT / "backend"))
    sys.path.insert(0, str(ROOT / "scripts"))
    from app.services.extraction import extract_receipt
    from measure_accuracy import product_match

    result = extract_receipt(str(image))
    out = []
    for idx, it in enumerate(result.items):
        if it.product_code:
            continue
        name = it.product_name_normalized or it.product_name_raw
        if any(
            product_match(name, e["product"]) and float(it.quantity) == float(e["quantity"])
            for e in existing
        ):
            continue
        out.append((idx, {
            "product": name,
            "quantity": it.quantity,
            "unit": it.unit,
            "code": None,
            "in_catalog": False,
            "source": "extractor",
        }))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fill-off-catalog", action="store_true",
                    help="re-read each image with the production extractor and "
                         "restore off-catalog lines the reviewer deleted")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    docs = con.execute(
        """
        SELECT id, filename, file_path, merchant_normalized, merchant_name,
               document_date, document_number
          FROM documents
         WHERE status = 'reviewed' AND deleted_at IS NULL
         ORDER BY filename
        """
    ).fetchall()

    images: dict[str, dict] = {}
    skipped: list[str] = []
    for d in docs:
        name = d["filename"]
        if name in images:
            skipped.append(f"{name}: duplicate filename, kept doc {images[name]['doc_id'][:8]}")
            continue

        rows = con.execute(
            """
            SELECT product_name_normalized, product_name_raw, product_code,
                   quantity, unit
              FROM document_items
             WHERE document_id = ?
             ORDER BY rowid
            """,
            (d["id"],),
        ).fetchall()
        if not rows:
            skipped.append(f"{name}: no items")
            continue

        src = UPLOADS / Path(d["file_path"]).name
        dest = DEMO_DIR / name
        if not src.exists() and not dest.exists():
            skipped.append(f"{name}: image missing ({src.name})")
            continue
        if src.exists() and not args.dry_run:
            # Only copy when absent/changed — keeps the git diff quiet.
            if not dest.exists() or dest.stat().st_size != src.stat().st_size:
                shutil.copy2(src, dest)

        lines = [
            {
                "product": r["product_name_normalized"] or r["product_name_raw"],
                "quantity": r["quantity"],
                "unit": r["unit"],
                "code": r["product_code"],
                "in_catalog": bool(r["product_code"]),
            }
            for r in rows
        ]
        if args.fill_off_catalog:
            for at, extra in off_catalog_lines(dest if dest.exists() else src, lines):
                lines.insert(at, extra)
                print(f"  + {name} @{at}: {extra['product']} x{extra['quantity']:g}")

        images[name] = {
            "doc_id": d["id"],
            "kind": KIND_OVERRIDES.get(name, DEFAULT_KIND),
            "merchant": d["merchant_normalized"] or d["merchant_name"] or "",
            "document_number": d["document_number"],
            "document_date": d["document_date"],
            "lines": lines,
        }

    payload = {
        "source": "human-approved documents (status=reviewed) in backend/data/receipts.db",
        "images": images,
    }
    n_lines = sum(len(v["lines"]) for v in images.values())
    n_cat = sum(1 for v in images.values() for l in v["lines"] if l["in_catalog"])
    print(f"{len(images)} receipts, {n_lines} line-items ({n_cat} in catalog, "
          f"{n_lines - n_cat} off-catalog)")
    for s in skipped:
        print(f"  skip {s}", file=sys.stderr)
    if args.dry_run:
        print("(dry run — nothing written)")
        return
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
