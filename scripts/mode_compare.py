"""
Compare extraction modes (combined vs legacy) on a small sample,
calling services directly (no HTTP / no DB write).

Usage: cd backend && .venv/bin/python ../scripts/mode_compare.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services.extraction import extract_receipt  # noqa: E402
from app.services.extraction_combined import extract_with_fraud  # noqa: E402

SAMPLE = [
    "01.jpeg",  # รวยสุรา clean
    "08.jpeg",  # กวงเสิน clean mid
    "06.jpeg",  # โจวบุ่งใช้ handwritten
]

DATA = ROOT / "dataTest" / "demo"


def time_call(fn, *args):
    t0 = time.time()
    try:
        out = fn(*args)
        return time.time() - t0, out, None
    except Exception as e:
        return time.time() - t0, None, str(e)


def main() -> int:
    paths = [DATA / n for n in SAMPLE if (DATA / n).exists()]
    if not paths:
        print("No sample files found")
        return 1

    print(f"\n{'=' * 70}\n  EXTRACTION MODE COMPARISON  ({len(paths)} files)\n{'=' * 70}\n")

    rows = []
    for p in paths:
        print(f"--- {p.name} ---")

        # Combined
        t_c, out_c, err_c = time_call(extract_with_fraud, str(p))
        if err_c:
            print(f"  combined: ERROR {err_c[:120]}")
            c_total = c_items = c_conf = None
        else:
            ext = out_c.extraction
            c_total = ext.grand_total
            c_items = len(ext.items)
            c_conf = ext.confidence
            fp = out_c.fraud_payload or {}
            print(
                f"  combined ⏱ {t_c:5.2f}s  total={c_total}  items={c_items}  conf={c_conf}"
                f"  fraud_flags={len(fp.get('flags', []))}"
            )

        # Legacy (no fraud merged in this entry; just extraction)
        t_l, out_l, err_l = time_call(extract_receipt, str(p))
        if err_l:
            print(f"  legacy  : ERROR {err_l[:120]}")
            l_total = l_items = l_conf = None
        else:
            l_total = out_l.grand_total
            l_items = len(out_l.items)
            l_conf = out_l.confidence
            print(f"  legacy   ⏱ {t_l:5.2f}s  total={l_total}  items={l_items}  conf={l_conf}")

        rows.append({
            "file": p.name,
            "combined": {
                "seconds": round(t_c, 2),
                "grand_total": c_total,
                "items": c_items,
                "confidence": c_conf,
                "error": err_c,
            },
            "legacy": {
                "seconds": round(t_l, 2),
                "grand_total": l_total,
                "items": l_items,
                "confidence": l_conf,
                "error": err_l,
            },
        })

    print(f"\n{'=' * 70}\n  SUMMARY\n{'=' * 70}")
    c_t = [r["combined"]["seconds"] for r in rows if not r["combined"]["error"]]
    l_t = [r["legacy"]["seconds"] for r in rows if not r["legacy"]["error"]]
    if c_t:
        print(f"  combined  mean={statistics.mean(c_t):.2f}s  total={sum(c_t):.2f}s  n={len(c_t)}")
    if l_t:
        print(f"  legacy    mean={statistics.mean(l_t):.2f}s  total={sum(l_t):.2f}s  n={len(l_t)}")
    if c_t and l_t:
        delta = (statistics.mean(l_t) - statistics.mean(c_t)) / statistics.mean(l_t) * 100
        print(f"  combined is ~{delta:.1f}% faster on average")

    out = ROOT / "dataTest" / "mode_compare.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"\n  Saved to: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
