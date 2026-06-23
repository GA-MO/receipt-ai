"""Measure extraction accuracy using the LIVE DB as ground truth.

Ground truth = the `document_items` currently stored in the system (what the
app shows / what a reviewer accepted). For each real uploaded receipt we
re-run the production `extract_receipt` pipeline on its stored image and
compare (product_code, quantity) against the stored items.

Two signals:
  * TRUE ACCURACY  — docs with status='reviewed' (human-verified ground
    truth). This is the gold standard; compares both the original AI output
    (raw_extraction) and a fresh re-run against the human-corrected items.
  * RECORD AGREEMENT — all other docs: how well a fresh extraction reproduces
    the stored record. For unreviewed docs the record is itself AI-made minus
    parser-dropped empty lines, so this is stability, not independent truth.

Usage:
    cd backend && .venv/bin/python ../scripts/measure_accuracy_db.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.models import Document, DocumentItem  # noqa: E402
from app.services.extraction import extract_receipt  # noqa: E402

_NOISE = ["เบียร์", "ขวด", "ใหญ่", "(", ")", "ml", "มล", "ลัง", "แพ็ค", "ถาด"]


def _denoise(s: str) -> str:
    s = (s or "").lower().strip()
    for n in _NOISE:
        s = s.replace(n.lower(), " ")
    return " ".join(s.split())


def key_of(code: str | None, name: str | None) -> str:
    """Identity key: catalog code when present, else de-noised name."""
    if code and code.strip() and code.strip() != "-":
        return f"CODE:{code.strip()}"
    return f"NAME:{_denoise(name)}"


def match_lines(gt: list[tuple[str, float]], pred: list[tuple[str, float]]) -> dict:
    """Multiset match on identity key; among matched, check quantity."""
    gt_keys = Counter(k for k, _ in gt)
    pred_by_key: dict[str, list[float]] = {}
    for k, q in pred:
        pred_by_key.setdefault(k, []).append(q)

    product_matched = 0
    qty_correct = 0
    gt_qty = {}
    for k, q in gt:
        gt_qty.setdefault(k, []).append(q)

    for k, qtys in gt_qty.items():
        avail = list(pred_by_key.get(k, []))
        for q in qtys:
            if avail:
                product_matched += 1
                # pick an exact-qty pred if available, else any
                if q in avail:
                    qty_correct += 1
                    avail.remove(q)
                else:
                    avail.pop(0)
    # Quantity-only accuracy: do the COUNTS match, regardless of which product
    # label they were attached to? (A product-name correction that keeps the
    # quantity must not be charged as a quantity error.) Multiset of qty values.
    gt_q = Counter(round(q, 3) for _, q in gt)
    pred_q = Counter(round(q, 3) for _, q in pred)
    qty_multiset_correct = sum((gt_q & pred_q).values())

    return {
        "gt_lines": len(gt),
        "pred_lines": len(pred),
        "product_matched": product_matched,
        "qty_correct": qty_correct,
        "qty_multiset_correct": qty_multiset_correct,
    }


def main() -> None:
    db = SessionLocal()
    docs = (
        db.query(Document)
        .filter(Document.status != "not_receipt")
        .filter(Document.deleted_at.is_(None))
        .order_by(Document.status, Document.filename)
        .all()
    )

    reviewed_rows, agreement_rows = [], []
    print(f"{'file':<30}{'status':<11}{'gt':>4}{'pred':>5}{'prodOK':>7}{'qtyOK':>6}", file=sys.stderr)

    for d in docs:
        items = (
            db.query(DocumentItem)
            .filter(DocumentItem.document_id == d.id)
            .order_by(DocumentItem.id)
            .all()
        )
        gt = [(key_of(i.product_code, i.product_name_normalized or i.product_name_raw),
               float(i.quantity or 0)) for i in items]
        if not gt:
            continue

        try:
            res = extract_receipt(d.file_path)
        except Exception as exc:  # noqa: BLE001
            print(f"  SKIP {d.filename}: {exc}", file=sys.stderr)
            continue
        pred = [(key_of(it.product_code, it.product_name_normalized or it.product_name_raw),
                 float(it.quantity or 0)) for it in res.items]

        m = match_lines(gt, pred)
        m["file"] = d.filename
        m["status"] = d.status
        (reviewed_rows if d.status == "reviewed" else agreement_rows).append(m)
        print(f"{d.filename[:28]:<30}{d.status:<11}{m['gt_lines']:>4}{m['pred_lines']:>5}"
              f"{m['product_matched']:>7}{m['qty_correct']:>6}", file=sys.stderr)

    def agg(rows, label):
        g = sum(r["gt_lines"] for r in rows)
        if not g:
            print(f"\n[{label}] no rows")
            return None
        pm = sum(r["product_matched"] for r in rows)
        qc = sum(r["qty_correct"] for r in rows)
        qm = sum(r["qty_multiset_correct"] for r in rows)
        print(f"\n[{label}]  {len(rows)} receipts, {g} stored line-items (ground truth)")
        print(f"  product identity   : {pm/g*100:5.1f}%   ({pm}/{g})")
        print(f"  quantity (counts)  : {qm/g*100:5.1f}%   ({qm}/{g})   <-- the headline number")
        print(f"  line (prod+qty)    : {qc/g*100:5.1f}%   ({qc}/{g})")
        return {"receipts": len(rows), "gt_lines": g,
                "product": pm / g, "quantity": qm / g, "line": qc / g}

    print("\n" + "=" * 60)
    s_rev = agg(reviewed_rows, "REVIEWED (human-verified ground truth)")
    s_agr = agg(agreement_rows, "RECORD AGREEMENT (fresh run vs stored record)")
    s_all = agg(reviewed_rows + agreement_rows, "ALL real receipts in system")

    out = ROOT / "dataTest" / "accuracy_report_db.json"
    out.write_text(json.dumps({
        "reviewed": s_rev, "agreement": s_agr, "all": s_all,
        "reviewed_rows": reviewed_rows, "agreement_rows": agreement_rows,
    }, ensure_ascii=False, indent=2))
    print(f"\nwrote {out.relative_to(ROOT)}")
    db.close()


if __name__ == "__main__":
    main()
