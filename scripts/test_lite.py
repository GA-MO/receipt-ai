"""A/B: current model vs gemini-3.1-flash-lite on the WHOLE demo set.

Uses the current extraction pipeline (services.extraction.extract_receipt).
Reports per-image item-set agreement + latency, then an aggregate summary.

Usage: cd backend && .venv/bin/python ../scripts/test_lite.py
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.services import extraction  # noqa: E402
from app.services import llm_client  # noqa: E402

DATA = ROOT / "dataTest" / "demo"
EXTS = {".jpeg", ".jpg", ".png", ".webp", ".pdf"}

BASE = ("baseline", "google/gemini-3-flash-preview")
LITE = ("lite", "google/gemini-3.1-flash-lite")


def item_key(it):
    code = getattr(it, "product_code", None)
    name = getattr(it, "product_name_normalized", None) or getattr(it, "product_name_raw", None) or ""
    qty = getattr(it, "quantity", None)
    unit = getattr(it, "unit", None) or ""
    return (code or name, qty, unit)


def run(model: str, img: Path):
    settings.openrouter_model = model
    llm_client.reset_openai_client()
    t0 = time.time()
    r = extraction.extract_receipt(str(img))
    dt = time.time() - t0
    keys = sorted(item_key(it) for it in r.items)
    merch = r.merchant_normalized or r.merchant_name
    return {"dt": dt, "merch": merch, "items": keys, "n": len(r.items)}


def main() -> None:
    images = sorted(p for p in DATA.iterdir() if p.suffix.lower() in EXTS and not p.name.startswith("."))
    print(f"demo images: {len(images)}\n")
    print(f"{'image':<40} {'base s':>7} {'lite s':>7} {'base#':>6} {'lite#':>6}  match")
    print("-" * 80)

    base_times, lite_times = [], []
    n_match = n_total = 0
    merch_match = 0

    for img in images:
        try:
            b = run(*((BASE[1],) + (img,)))
            l = run(*((LITE[1],) + (img,)))
        except Exception as exc:  # noqa: BLE001
            print(f"{img.name:<40} ERROR: {exc}")
            continue
        n_total += 1
        same_items = b["items"] == l["items"]
        same_merch = b["merch"] == l["merch"]
        if same_items:
            n_match += 1
        if same_merch:
            merch_match += 1
        base_times.append(b["dt"])
        lite_times.append(l["dt"])
        flag = "OK" if (same_items and same_merch) else ("items!" if not same_items else "merch!")
        print(f"{img.name:<40} {b['dt']:>7.1f} {l['dt']:>7.1f} {b['n']:>6} {l['n']:>6}  {flag}")
        if not same_items:
            print(f"    base: {b['items']}")
            print(f"    lite: {l['items']}")
        if not same_merch:
            print(f"    merchant base={b['merch']!r} lite={l['merch']!r}")

    print("-" * 80)
    if n_total:
        print(f"images compared        : {n_total}")
        print(f"item-set identical     : {n_match}/{n_total}")
        print(f"merchant identical     : {merch_match}/{n_total}")
        print(f"avg latency  baseline  : {statistics.mean(base_times):.2f}s")
        print(f"avg latency  lite      : {statistics.mean(lite_times):.2f}s")
        print(f"speedup                : {statistics.mean(base_times)/statistics.mean(lite_times):.2f}x faster")


if __name__ == "__main__":
    main()
