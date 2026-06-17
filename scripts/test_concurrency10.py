"""Simulate the real upload pipeline: fan 10 receipts through a thread pool
sized by settings.extraction_concurrency (same as routers/documents.py) and
measure WALL-CLOCK time — i.e. what a 10-image bulk upload actually costs.

Usage: cd backend && .venv/bin/python ../scripts/test_concurrency10.py
"""
from __future__ import annotations

import concurrent.futures as cf
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.services import extraction  # noqa: E402

DATA = ROOT / "dataTest" / "demo"
EXTS = {".jpeg", ".jpg", ".png", ".webp", ".pdf"}


def one(img: Path):
    t0 = time.time()
    try:
        r = extraction.extract_receipt(str(img))
        return img.name, time.time() - t0, len(r.items), r.merchant_normalized or r.merchant_name, None
    except Exception as exc:  # noqa: BLE001
        return img.name, time.time() - t0, 0, None, str(exc)


def main() -> None:
    images = sorted(p for p in DATA.iterdir() if p.suffix.lower() in EXTS and not p.name.startswith("."))
    conc = settings.extraction_concurrency
    print(f"model       : {settings.openrouter_model}")
    print(f"concurrency : {conc}  (extraction_concurrency)")
    print(f"images      : {len(images)}\n")

    wall0 = time.time()
    results = []
    with cf.ThreadPoolExecutor(max_workers=conc, thread_name_prefix="extract") as pool:
        for r in pool.map(one, images):
            results.append(r)
    wall = time.time() - wall0

    print(f"{'image':<40} {'sec':>6}  {'items':>5}  merchant")
    print("-" * 80)
    per = []
    errs = 0
    for name, dt, n, merch, err in results:
        per.append(dt)
        if err:
            errs += 1
            print(f"{name:<40} {dt:>6.1f}  ERROR: {err}")
        else:
            print(f"{name:<40} {dt:>6.1f}  {n:>5}  {merch}")

    print("-" * 80)
    print(f"WALL CLOCK (10 in parallel) : {wall:.1f}s")
    print(f"sum if serial               : {sum(per):.1f}s")
    print(f"avg per receipt             : {sum(per)/len(per):.1f}s")
    print(f"errors                      : {errs}/{len(images)}")


if __name__ == "__main__":
    main()
