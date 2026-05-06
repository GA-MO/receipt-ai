"""
A/B test: current model (gemini-2.5-flash) vs gemini-3.1 on the demo set.

Calls extract_with_fraud directly with monkey-patched settings.openrouter_model
so we don't have to restart the backend.

Usage: cd backend && .venv/bin/python ../scripts/test_gemini_31.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.services import llm_client as _llm  # noqa: E402
from app.services.extraction_combined import extract_with_fraud  # noqa: E402

DATA = ROOT / "dataTest" / "demo"
OUT = ROOT / "dataTest" / "gemini_31_compare.json"

# Models on OpenRouter — names match backend/.env.example
MODELS = [
    ("baseline_2.5_flash", "google/gemini-2.5-flash"),
    ("gemini_3_flash", "google/gemini-3-flash-preview"),
    ("gemini_3.1_flash_lite", "google/gemini-3.1-flash-lite-preview"),
]

SAMPLE = sorted(p.name for p in DATA.glob("*") if p.is_file() and not p.name.startswith("."))


def reset_clients():
    """Force the OpenRouter client to be re-created so the new model is picked up."""
    _llm._openai_client = None  # noqa: SLF001


def run_one(file_path: Path) -> dict:
    t0 = time.time()
    try:
        out = extract_with_fraud(str(file_path))
        elapsed = time.time() - t0
        ext = out.extraction
        fp = out.fraud_payload or {}
        return {
            "ok": True,
            "seconds": round(elapsed, 2),
            "merchant": ext.merchant_normalized or ext.merchant_name,
            "doc_date": ext.document_date,
            "subtotal": ext.subtotal,
            "vat": ext.vat,
            "grand_total": ext.grand_total,
            "items": len(ext.items),
            "confidence": ext.confidence,
            "fraud_flags": len(fp.get("flags", [])),
            "fraud_risk": (fp.get("ai_analysis") or {}).get("risk_score"),
        }
    except Exception as e:
        return {"ok": False, "seconds": round(time.time() - t0, 2), "error": str(e)[:200]}


def main() -> int:
    if not SAMPLE:
        print("No demo files")
        return 1

    print(f"\n{'=' * 78}")
    print(f"  GEMINI 3.1 A/B TEST  ({len(SAMPLE)} files × {len(MODELS)} models)")
    print(f"{'=' * 78}\n")

    all_results: dict[str, dict] = {}
    for label, model_id in MODELS:
        print(f"\n--- Model: {label}  ({model_id}) ---")
        settings.openrouter_model = model_id
        reset_clients()

        per_file: dict[str, dict] = {}
        for fname in SAMPLE:
            r = run_one(DATA / fname)
            per_file[fname] = r
            if r["ok"]:
                print(
                    f"  {fname:36s}  ⏱ {r['seconds']:5.2f}s  "
                    f"total={r['grand_total']:>10}  conf={r['confidence']}  "
                    f"items={r['items']}  fraud={r['fraud_flags']}  "
                    f"merchant={r['merchant']}"
                )
            else:
                print(f"  {fname:36s}  ⏱ {r['seconds']:5.2f}s  ERROR: {r['error'][:100]}")
        all_results[label] = per_file

        ok = [r for r in per_file.values() if r["ok"]]
        if ok:
            ts = [r["seconds"] for r in ok]
            cs = [r["confidence"] for r in ok if r.get("confidence") is not None]
            ts.sort()
            print(
                f"  → success {len(ok)}/{len(SAMPLE)}  "
                f"latency mean={statistics.mean(ts):.2f}s  "
                f"p50={ts[len(ts)//2]:.2f}s  p95={ts[max(0,int(len(ts)*0.95)-1)]:.2f}s  "
                f"min={min(ts):.2f}s max={max(ts):.2f}s"
            )
            if cs:
                print(f"     confidence mean={statistics.mean(cs):.2f}  min={min(cs):.2f}")

    # Side-by-side diff per file
    print(f"\n{'=' * 78}\n  SIDE-BY-SIDE\n{'=' * 78}")
    base_label, new_label = MODELS[0][0], MODELS[1][0]
    print(f"\n  {'file':36s}  {base_label:>20s} | {new_label:>20s}  {'Δ total':>10s}  {'Δ time':>8s}")
    for fname in SAMPLE:
        b = all_results[base_label].get(fname, {})
        n = all_results[new_label].get(fname, {})
        if not (b.get("ok") and n.get("ok")):
            print(f"  {fname:36s}  base_ok={b.get('ok')}  new_ok={n.get('ok')}")
            continue
        b_total = b.get("grand_total")
        n_total = n.get("grand_total")
        delta = (n_total - b_total) if (b_total is not None and n_total is not None) else None
        delta_t = n["seconds"] - b["seconds"]
        print(
            f"  {fname:36s}  "
            f"{str(b_total):>15} ({b['seconds']:.1f}s) | "
            f"{str(n_total):>15} ({n['seconds']:.1f}s)  "
            f"{str(delta):>10s}  {delta_t:+8.2f}s"
        )

    OUT.write_text(json.dumps(all_results, ensure_ascii=False, indent=2))
    print(f"\n  Saved: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
