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


def align(gt_lines: list[dict], pred_lines: list[dict]) -> list[dict]:
    """Match predictions to ground-truth lines by product identity, not position.

    Positional alignment breaks as soon as one line is missed or invented —
    every line after it shifts and is scored wrong. So each GT line claims its
    best unclaimed prediction (same product; nearest position wins ties), and
    whatever is left over is a miss or an invented line.
    """
    taken: set[int] = set()
    per_line: list[dict] = []
    for gi, g in enumerate(gt_lines):
        best = None
        for pi, p in enumerate(pred_lines):
            if pi in taken or not product_match(p["product"], g["product"]):
                continue
            if best is None or abs(pi - gi) < abs(best - gi):
                best = pi
        if best is None:
            per_line.append({"status": "missed", "gt": g})
            continue
        taken.add(best)
        p = pred_lines[best]
        qty_ok = float(p["quantity"]) == float(g["quantity"])
        per_line.append({
            "status": "ok" if qty_ok else "wrong",
            "product_ok": True,
            "quantity_ok": qty_ok,
            "gt": g,
            "pred": p,
        })
    for pi, p in enumerate(pred_lines):
        if pi not in taken:
            per_line.append({"status": "invented", "pred": p})
    return per_line


def _tally(per_line: list[dict], gt_n: int) -> dict:
    return {
        "gt_lines": gt_n,
        "product_correct": sum(1 for r in per_line if r.get("product_ok")),
        "quantity_correct": sum(1 for r in per_line if r.get("quantity_ok")),
        "line_correct": sum(1 for r in per_line if r["status"] == "ok"),
        "missed": sum(1 for r in per_line if r["status"] == "missed"),
        "invented": sum(1 for r in per_line if r["status"] == "invented"),
    }


def score_image(name: str, gt: dict) -> dict:
    path = DEMO_DIR / name
    result = extract_receipt(str(path))
    pred_lines = [
        {
            "product": it.product_name_normalized or it.product_name_raw,
            "quantity": it.quantity,
            "in_catalog": bool(it.product_code),
        }
        for it in result.items
    ]
    gt_lines = gt["lines"]

    # "read"  = every line on the paper, off-catalog products included. This is
    #           the honest measure of how well the model reads a bill, and the
    #           one to compare models on.
    # "catalog" = only lines whose product exists in `products`. This is what
    #           actually reaches the visit rollup, so it is the number the
    #           business sees. An off-catalog line is a catalog gap, not a
    #           misread, and must not be charged to either score twice.
    per_line = align(gt_lines, pred_lines)
    cat_gt = [g for g in gt_lines if g.get("in_catalog", True)]
    cat_pred = [p for p in pred_lines if p["in_catalog"]]
    cat_per_line = align(cat_gt, cat_pred)

    merchant_ok = fuzz.partial_ratio(
        (result.merchant_normalized or result.merchant_name or "").lower(),
        gt["merchant"].lower(),
    ) >= 70

    return {
        "name": name,
        "kind": gt["kind"],
        "pred_lines": len(pred_lines),
        "merchant_ok": merchant_ok,
        "read": _tally(per_line, len(gt_lines)),
        "catalog": _tally(cat_per_line, len(cat_gt)),
        "per_line": per_line,
        **_tally(per_line, len(gt_lines)),  # flat keys, kept for old readers
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

    def agg(rs, scope="read"):
        gt_n = sum(r[scope]["gt_lines"] for r in rs)
        f = lambda k: sum(r[scope][k] for r in rs) / gt_n if gt_n else 0  # noqa: E731
        return {
            "receipts": len(rs),
            "gt_lines": gt_n,
            "product_acc": f("product_correct"),
            "quantity_acc": f("quantity_correct"),
            "line_acc": f("line_correct"),
            "missed": sum(r[scope]["missed"] for r in rs),
            "invented": sum(r[scope]["invented"] for r in rs),
            "merchant_acc": sum(1 for r in rs if r["merchant_ok"]) / len(rs) if rs else 0,
        }

    print("\n" + "=" * 78)
    print(f"{'image':<34}{'kind':<13}{'lines':>6}{'prod':>6}{'qty':>6}{'both':>6}"
          f"{'miss':>6}{'inv':>5}")
    print("-" * 78)
    for r in results:
        t = r["read"]
        print(f"{r['name']:<34}{r['kind']:<13}{t['gt_lines']:>6}"
              f"{t['product_correct']:>6}{t['quantity_correct']:>6}{t['line_correct']:>6}"
              f"{t['missed']:>6}{t['invented']:>5}")
    print("=" * 78)

    scopes = [
        ("READ — every line on the bill", "read"),
        ("CATALOG — lines that reach the rollup", "catalog"),
    ]
    for label, scope in scopes:
        a = agg(results, scope)
        print(f"\n[{label}]  {a['receipts']} receipts, {a['gt_lines']} line-items")
        print(f"  product identity : {a['product_acc']*100:5.1f}%")
        print(f"  quantity         : {a['quantity_acc']*100:5.1f}%")
        print(f"  line (prod+qty)  : {a['line_acc']*100:5.1f}%   <-- headline")
        print(f"  missed / invented: {a['missed']} / {a['invented']}")
    print(f"\n  merchant         : {agg(results)['merchant_acc']*100:5.1f}%")

    if args.json:
        print("\n" + json.dumps(results, ensure_ascii=False, indent=2))

    out = ROOT / "dataTest" / "accuracy_report.json"
    out.write_text(json.dumps({"summary": {
        "read": agg(results, "read"), "catalog": agg(results, "catalog"),
    }, "results": results}, ensure_ascii=False, indent=2))
    print(f"\nwrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
