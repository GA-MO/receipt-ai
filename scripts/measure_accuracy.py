"""Measure (product, quantity) extraction accuracy on the demo receipts.

Runs the *production* extraction pipeline (extract_receipt -> live DB catalog,
same prompt the app uses) on each demo image, aligns the result against
human-labelled ground truth, and reports field-level accuracy.

This is the number behind the "96%" slide claim — measured, not asserted.

Usage:
    cd backend && .venv/bin/python ../scripts/measure_accuracy.py
    cd backend && .venv/bin/python ../scripts/measure_accuracy.py --only 31_ai_reads_shorthand

Headline metric = "line correct" = AI got BOTH the product identity AND the
quantity right on that line. A missing or hallucinated line counts against us.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services.extraction import extract_receipt  # noqa: E402

DEMO_DIR = ROOT / "dataTest" / "demo"
GT_PATH = ROOT / "dataTest" / "ground_truth_demo.json"

# Product identity is matched leniently — wording differs ("เบียร์ลีโอขวดใหญ่"
# vs "ลีโอ ขวดใหญ่") but Leo-vs-Singha must still fail. token_set_ratio on the
# de-noised name does this well; 70 is the accept threshold.
PRODUCT_MATCH_THRESHOLD = 70
_NOISE = ["เบียร์", "ขวด", "ใหญ่", "(", ")", "ml", "มล", "ลัง", "แพ็ค", "ถาด", "ขวดใหญ่"]


def _denoise(s: str) -> str:
    s = (s or "").lower().strip()
    for n in _NOISE:
        s = s.replace(n.lower(), " ")
    return " ".join(s.split())


def product_match(pred: str, gt: str) -> bool:
    a, b = _denoise(pred), _denoise(gt)
    # token_set_ratio handles word-order/wording diffs; the space-stripped ratio
    # rescues identical names that only differ by a space ("อาซาฮี กระป๋อง" vs
    # "อาซาฮีกระป๋อง") which token matching otherwise splits apart.
    score = max(
        fuzz.token_set_ratio(a, b),
        fuzz.ratio(a.replace(" ", ""), b.replace(" ", "")),
    )
    return score >= PRODUCT_MATCH_THRESHOLD


def score_image(name: str, gt: dict) -> dict:
    path = DEMO_DIR / name
    result = extract_receipt(str(path))
    pred_lines = [
        {"product": it.product_name_normalized or it.product_name_raw, "quantity": it.quantity}
        for it in result.items
    ]
    gt_lines = gt["lines"]

    # Greedy positional alignment: receipts list items top-to-bottom in order,
    # so line i of the prediction maps to line i of ground truth.
    n = max(len(gt_lines), len(pred_lines))
    per_line = []
    for i in range(n):
        g = gt_lines[i] if i < len(gt_lines) else None
        p = pred_lines[i] if i < len(pred_lines) else None
        if g is None:
            per_line.append({"status": "extra_pred", "pred": p})
            continue
        if p is None:
            per_line.append({"status": "missed", "gt": g})
            continue
        prod_ok = product_match(p["product"], g["product"])
        qty_ok = float(p["quantity"]) == float(g["quantity"])
        per_line.append({
            "status": "ok" if (prod_ok and qty_ok) else "wrong",
            "product_ok": prod_ok,
            "quantity_ok": qty_ok,
            "gt": g,
            "pred": {"product": p["product"], "quantity": p["quantity"]},
        })

    gt_n = len(gt_lines)
    prod_correct = sum(1 for r in per_line if r.get("product_ok"))
    qty_correct = sum(1 for r in per_line if r.get("quantity_ok"))
    line_correct = sum(1 for r in per_line if r["status"] == "ok")
    merchant_ok = fuzz.partial_ratio(
        (result.merchant_normalized or result.merchant_name or "").lower(),
        gt["merchant"].lower(),
    ) >= 70

    return {
        "name": name,
        "kind": gt["kind"],
        "gt_lines": gt_n,
        "pred_lines": len(pred_lines),
        "product_correct": prod_correct,
        "quantity_correct": qty_correct,
        "line_correct": line_correct,
        "merchant_ok": merchant_ok,
        "per_line": per_line,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="run a single image (filename stem)")
    ap.add_argument("--json", action="store_true", help="dump full per-line JSON")
    args = ap.parse_args()

    gt_all = json.loads(GT_PATH.read_text())["images"]
    items = gt_all.items()
    if args.only:
        items = [(k, v) for k, v in items if k.startswith(args.only)]

    results = []
    for name, gt in items:
        print(f"… extracting {name}", file=sys.stderr)
        results.append(score_image(name, gt))

    def agg(rs):
        gt_n = sum(r["gt_lines"] for r in rs)
        return {
            "receipts": len(rs),
            "gt_lines": gt_n,
            "product_acc": sum(r["product_correct"] for r in rs) / gt_n if gt_n else 0,
            "quantity_acc": sum(r["quantity_correct"] for r in rs) / gt_n if gt_n else 0,
            "line_acc": sum(r["line_correct"] for r in rs) / gt_n if gt_n else 0,
            "merchant_acc": sum(1 for r in rs if r["merchant_ok"]) / len(rs) if rs else 0,
        }

    printed = [r for r in results if r["kind"] == "printed"]
    handw = [r for r in results if r["kind"] == "handwritten"]

    print("\n" + "=" * 72)
    print(f"{'image':<40}{'kind':<13}{'lines':>6}{'prod':>6}{'qty':>6}{'both':>6}")
    print("-" * 72)
    for r in results:
        print(f"{r['name']:<40}{r['kind']:<13}{r['gt_lines']:>6}"
              f"{r['product_correct']:>6}{r['quantity_correct']:>6}{r['line_correct']:>6}")
    print("=" * 72)

    for label, rs in [("ALL", results), ("PRINTED", printed), ("HANDWRITTEN", handw)]:
        a = agg(rs)
        print(f"\n[{label}]  {a['receipts']} receipts, {a['gt_lines']} line-items")
        print(f"  product identity : {a['product_acc']*100:5.1f}%")
        print(f"  quantity         : {a['quantity_acc']*100:5.1f}%")
        print(f"  line (prod+qty)  : {a['line_acc']*100:5.1f}%   <-- headline")
        print(f"  merchant         : {a['merchant_acc']*100:5.1f}%")

    if args.json:
        print("\n" + json.dumps(results, ensure_ascii=False, indent=2))

    out = ROOT / "dataTest" / "accuracy_report.json"
    out.write_text(json.dumps({"summary": {
        "all": agg(results), "printed": agg(printed), "handwritten": agg(handw),
    }, "results": results}, ensure_ascii=False, indent=2))
    print(f"\nwrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
