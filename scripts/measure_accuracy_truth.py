"""TRUE production accuracy: original AI output vs human-reviewed ground truth.

For every human-reviewed document we compare the ORIGINAL extraction the AI
produced at upload time (`documents.raw_extraction`) against the items the
reviewer ended up with (`document_items`). This is the real, honest accuracy
of the production run — the exact output a human looked at and corrected.

No re-extraction, no API calls, no hand-labelling: ground truth is whatever is
in the system right now.

Usage:
    cd backend && .venv/bin/python ../scripts/measure_accuracy_truth.py
    cd backend && .venv/bin/python ../scripts/measure_accuracy_truth.py --diff
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.models import Document, DocumentItem  # noqa: E402

_NOISE = ["เบียร์", "ขวด", "ใหญ่", "(", ")", "ml", "มล", "ลัง", "แพ็ค", "ถาด"]


def _denoise(s: str) -> str:
    s = (s or "").lower().strip()
    for n in _NOISE:
        s = s.replace(n.lower(), " ")
    return " ".join(s.split())


def key_of(code, name) -> str:
    code = (code or "").strip()
    if code and code != "-":
        return f"CODE:{code}"
    return f"NAME:{_denoise(name)}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", action="store_true", help="print every AI miss")
    args = ap.parse_args()

    db = SessionLocal()
    docs = (
        db.query(Document)
        .filter(Document.status == "reviewed", Document.deleted_at.is_(None))
        .order_by(Document.filename)
        .all()
    )

    tot_truth = tot_prod = tot_qty = tot_line = tot_false = 0
    rows = []
    misses = []

    for d in docs:
        truth_items = (
            db.query(DocumentItem)
            .filter(DocumentItem.document_id == d.id)
            .order_by(DocumentItem.id)
            .all()
        )
        truth = [(key_of(i.product_code, i.product_name_normalized or i.product_name_raw),
                  float(i.quantity or 0),
                  i.product_name_normalized or i.product_name_raw) for i in truth_items]
        try:
            raw = json.loads(d.raw_extraction or "{}")
        except json.JSONDecodeError:
            raw = {}
        pred = [(key_of(it.get("product_code"), it.get("product_name_raw")),
                 float(it.get("quantity") or 0),
                 it.get("product_name_raw")) for it in raw.get("items", [])]

        # multiset alignment on identity key
        pred_keys = Counter(k for k, _, _ in pred)
        product_ok = qty_ok_line = 0
        truth_qty = Counter(round(q, 3) for _, q, _ in truth)
        pred_qty = Counter(round(q, 3) for _, q, _ in pred)
        qty_counts_ok = sum((truth_qty & pred_qty).values())

        used = Counter()
        for k, q, nm in truth:
            # is there an unused pred line with same key?
            matches = [(pk, pq) for pk, pq, _ in pred if pk == k]
            avail = [pq for pk, pq in matches if used[(k, pq)] < pred_keys[k]]
            if matches:
                product_ok += 1
                if q in [m[1] for m in matches]:
                    qty_ok_line += 1
                    used[(k, q)] += 1

        false_lines = max(0, len(pred) - product_ok)
        rows.append({
            "file": d.filename, "truth": len(truth), "pred": len(pred),
            "product_ok": product_ok, "qty_counts_ok": qty_counts_ok,
            "line_ok": qty_ok_line, "false_lines": false_lines,
        })
        tot_truth += len(truth); tot_prod += product_ok
        tot_qty += qty_counts_ok; tot_line += qty_ok_line; tot_false += false_lines

        if args.diff:
            truth_set = Counter(k for k, _, _ in truth)
            pred_set = Counter(k for k, _, _ in pred)
            missing = truth_set - pred_set
            extra = pred_set - truth_set
            if missing or extra:
                tmap = {k: nm for k, _, nm in truth}
                pmap = {k: nm for k, _, nm in pred}
                for k in missing:
                    misses.append(f"{d.filename}: AI missed/misread → truth has {tmap.get(k,k)!r} [{k}]")
                for k in extra:
                    misses.append(f"{d.filename}: AI produced {pmap.get(k,k)!r} [{k}] not in truth")

    print(f"\n{'file':<30}{'truth':>6}{'AIpred':>7}{'prodOK':>7}{'qtyOK':>6}{'bothOK':>7}{'false':>6}")
    print("-" * 69)
    for r in rows:
        flag = "" if r["line_ok"] == r["truth"] and r["false_lines"] == 0 else "  <"
        print(f"{r['file'][:28]:<30}{r['truth']:>6}{r['pred']:>7}{r['product_ok']:>7}"
              f"{r['qty_counts_ok']:>6}{r['line_ok']:>7}{r['false_lines']:>6}{flag}")
    print("=" * 69)
    g = tot_truth or 1
    print(f"\nTRUE PRODUCTION ACCURACY  ({len(rows)} human-reviewed receipts, {tot_truth} ground-truth lines)")
    print(f"  product identity   : {tot_prod/g*100:5.1f}%   ({tot_prod}/{tot_truth})")
    print(f"  quantity (counts)  : {tot_qty/g*100:5.1f}%   ({tot_qty}/{tot_truth})   <-- the '96%' number")
    print(f"  line (prod+qty)    : {tot_line/g*100:5.1f}%   ({tot_line}/{tot_truth})")
    print(f"  false/extra lines  : {tot_false} total (AI lines the reviewer removed)")

    if args.diff:
        print("\n--- every AI miss ---")
        for m in misses:
            print(" ", m)

    out = ROOT / "dataTest" / "accuracy_truth.json"
    out.write_text(json.dumps({"summary": {
        "receipts": len(rows), "truth_lines": tot_truth,
        "product": tot_prod / g, "quantity": tot_qty / g, "line": tot_line / g,
        "false_lines": tot_false,
    }, "rows": rows}, ensure_ascii=False, indent=2))
    print(f"\nwrote {out.relative_to(ROOT)}")
    db.close()


if __name__ == "__main__":
    main()
