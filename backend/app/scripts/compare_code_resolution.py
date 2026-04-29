"""Compare Gemini-emitted product_code vs fuzzy fallback per line item.

For each test receipt, run extraction *once* and capture two signals per item:

  1. ``gemini_code``  — what Gemini emitted in ``product_code`` (new path,
     enabled by adding ``code`` to the prompt catalog + schema rule).
  2. ``fuzzy_code``   — what :func:`catalog.find_code_by_name` resolves the
     same ``product_name_normalized`` to (current production path).

Then tabulate:

  * ``gemini_only``  — fuzzy returned None, Gemini emitted a valid code.
  * ``fuzzy_only``   — Gemini omitted, fuzzy resolved.
  * ``agree``        — both emitted the same code.
  * ``disagree``     — both emitted, but different codes (manual review).
  * ``both_none``    — neither resolved (genuine non-catalog item).

Usage::

    .venv/bin/python -m app.scripts.compare_code_resolution \\
        --dir ../dataTest/groupA --limit 5

Run only against your own test data — each receipt is one Gemini call.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path

from ..database import SessionLocal
from ..models import Product
from ..services.catalog import find_code_by_name
from ..services.extraction import extract_receipt

logger = logging.getLogger(__name__)


def _label_for_code(db, code: str | None) -> str:
    if not code:
        return "—"
    p = db.query(Product).filter(Product.code == code).first()
    if not p:
        return f"{code} (UNKNOWN)"
    return f"{code} ({p.display_name or p.canonical_name})"


def process_receipt(file_path: Path) -> dict:
    """Run extraction once, return per-item comparison rows."""
    db = SessionLocal()
    try:
        t0 = time.perf_counter()
        result = extract_receipt(str(file_path))
        elapsed = time.perf_counter() - t0

        items: list[dict] = []
        for item in result.items:
            normalized = item.product_name_normalized or ""
            gemini_code = (item.product_code or "").strip() or None
            fuzzy_code = find_code_by_name(db, normalized)

            # Validate Gemini's code against active products.
            gemini_valid = False
            if gemini_code:
                gemini_valid = (
                    db.query(Product.code)
                    .filter(Product.code == gemini_code, Product.active.is_(True))
                    .first()
                    is not None
                )

            verdict: str
            if gemini_code and not gemini_valid:
                verdict = "gemini_invalid"
            elif gemini_code and not fuzzy_code:
                verdict = "gemini_only"
            elif fuzzy_code and not gemini_code:
                verdict = "fuzzy_only"
            elif gemini_code and fuzzy_code and gemini_code == fuzzy_code:
                verdict = "agree"
            elif gemini_code and fuzzy_code and gemini_code != fuzzy_code:
                verdict = "disagree"
            else:
                verdict = "both_none"

            if not gemini_code:
                gemini_label = "—"
            elif gemini_valid:
                gemini_label = _label_for_code(db, gemini_code)
            else:
                gemini_label = f"{gemini_code} (UNKNOWN)"

            items.append(
                {
                    "name": normalized,
                    "raw": item.product_name_raw,
                    "gemini_code": gemini_code,
                    "fuzzy_code": fuzzy_code,
                    "verdict": verdict,
                    "gemini_label": gemini_label,
                    "fuzzy_label": _label_for_code(db, fuzzy_code),
                }
            )

        return {
            "file": file_path.name,
            "elapsed_s": round(elapsed, 2),
            "merchant": result.merchant_name,
            "confidence": result.confidence,
            "items": items,
        }
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, required=True, help="Directory of receipt files.")
    parser.add_argument("--limit", type=int, default=5, help="Max receipts to process.")
    parser.add_argument("--out", type=Path, default=None, help="Write raw JSON results here.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.dir.is_dir():
        sys.exit(f"Not a directory: {args.dir}")

    files = sorted(
        f
        for f in args.dir.iterdir()
        if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
    )[: args.limit]
    if not files:
        sys.exit(f"No receipt files in {args.dir}")

    print(f"Processing {len(files)} receipt(s) from {args.dir}\n")

    all_results: list[dict] = []
    verdicts: Counter[str] = Counter()
    total_items = 0

    for f in files:
        try:
            row = process_receipt(f)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {f.name}: {exc}")
            continue
        all_results.append(row)

        item_verdicts = Counter(it["verdict"] for it in row["items"])
        verdicts.update(item_verdicts)
        total_items += len(row["items"])

        print(f"  ✓ {f.name} — {row['elapsed_s']}s, {len(row['items'])} items, conf={row['confidence']:.2f}")
        for it in row["items"]:
            marker = {
                "agree": "=",
                "gemini_only": "G",
                "fuzzy_only": "F",
                "disagree": "✗",
                "gemini_invalid": "!",
                "both_none": "·",
            }.get(it["verdict"], "?")
            print(
                f"      [{marker}] {it['name'][:40]:<40} "
                f"G={it['gemini_label'][:32]:<32} | F={it['fuzzy_label'][:32]}"
            )

    print()
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Receipts processed: {len(all_results)}")
    print(f"Total line items:   {total_items}")
    print()
    print("Per-item verdicts:")
    for verdict, count in verdicts.most_common():
        pct = (count / total_items * 100) if total_items else 0
        print(f"  {verdict:<16} {count:>4}  ({pct:5.1f}%)")

    catalog_items = total_items - verdicts.get("both_none", 0)
    if catalog_items:
        gemini_resolved = (
            verdicts.get("agree", 0)
            + verdicts.get("gemini_only", 0)
            + verdicts.get("disagree", 0)
        )
        fuzzy_resolved = (
            verdicts.get("agree", 0)
            + verdicts.get("fuzzy_only", 0)
            + verdicts.get("disagree", 0)
        )
        print()
        print("Resolution rate (excluding both_none):")
        print(f"  Gemini-emit: {gemini_resolved}/{catalog_items} ({gemini_resolved/catalog_items*100:.1f}%)")
        print(f"  Fuzzy:       {fuzzy_resolved}/{catalog_items} ({fuzzy_resolved/catalog_items*100:.1f}%)")

    if args.out:
        args.out.write_text(json.dumps(all_results, ensure_ascii=False, indent=2))
        print(f"\nRaw results written to {args.out}")


if __name__ == "__main__":
    main()
