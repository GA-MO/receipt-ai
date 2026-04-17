"""A/B compare legacy vs combined vs agentic extraction modes.

Runs all three modes against the demo documents and reports timing + quality.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.services.extraction import extract_receipt  # noqa: E402
from app.services.extraction_agentic import extract_agentic  # noqa: E402
from app.services.extraction_combined import extract_with_fraud  # noqa: E402


DEMO_DIR = Path(__file__).resolve().parent.parent / "dataTest" / "demo"


@dataclass
class Sample:
    filename: str
    mode: str
    duration: float
    merchant: str | None
    merchant_normalized: str | None
    category: str | None
    grand_total: float | None
    subtotal: float | None
    item_count: int
    item_names: list[str]
    item_categories: list[str]
    confidence: float
    fraud_score: float
    fraud_level: str
    fraud_flags: int
    fraud_summary: str
    extra: str = ""
    error: str | None = None


def _to_sample(mode, filename, duration, extraction, fraud, extra="", error=None):
    fraud = fraud or {}
    ai = fraud.get("ai_analysis") or {}
    flags = fraud.get("flags") or []
    return Sample(
        filename=filename,
        mode=mode,
        duration=duration,
        merchant=extraction.merchant_name if extraction else None,
        merchant_normalized=extraction.merchant_normalized if extraction else None,
        category=extraction.category if extraction else None,
        grand_total=extraction.grand_total if extraction else None,
        subtotal=extraction.subtotal if extraction else None,
        item_count=len(extraction.items) if extraction else 0,
        item_names=[i.product_name_normalized or "?" for i in (extraction.items if extraction else [])],
        item_categories=[i.category or "?" for i in (extraction.items if extraction else [])],
        confidence=extraction.confidence if extraction else 0.0,
        fraud_score=float(ai.get("risk_score") or 0.0),
        fraud_level=(ai.get("risk_level") or "n/a").lower(),
        fraud_flags=len(flags),
        fraud_summary=(ai.get("summary") or "").strip()[:90],
        extra=extra,
        error=error,
    )


def _run_legacy(path):
    t0 = time.time()
    try:
        ex = extract_receipt(str(path))
        return _to_sample("legacy", path.name, time.time() - t0, ex, None, extra="(extract only)")
    except Exception as e:
        return _to_sample("legacy", path.name, time.time() - t0, None, None, error=str(e)[:80])


def _run_combined(path):
    t0 = time.time()
    try:
        r = extract_with_fraud(str(path))
        return _to_sample("combined", path.name, time.time() - t0, r.extraction, r.fraud_payload)
    except Exception as e:
        return _to_sample("combined", path.name, time.time() - t0, None, None, error=str(e)[:80])


def _run_agentic(path, db):
    t0 = time.time()
    try:
        r = extract_agentic(str(path), db)
        extra = f"iters={r.iterations} tools={len(r.tool_calls)}"
        return _to_sample("agentic", path.name, time.time() - t0, r.extraction, r.fraud_payload, extra=extra)
    except Exception as e:
        return _to_sample("agentic", path.name, time.time() - t0, None, None, error=str(e)[:80])


def main() -> int:
    files = sorted(
        f for f in DEMO_DIR.iterdir()
        if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
    )
    print(f"Comparing {len(files)} demo files across 3 modes.\n")

    db = SessionLocal()
    results: dict[str, list[Sample]] = {"legacy": [], "combined": [], "agentic": []}

    try:
        for i, f in enumerate(files, 1):
            print(f"[{i:>2}/{len(files)}] {f.name}")
            r = _run_legacy(f); print(f"         legacy    {r.duration:>5.1f}s  {r.merchant_normalized or '?'}"); results["legacy"].append(r)
            r = _run_combined(f); print(f"         combined  {r.duration:>5.1f}s  risk={r.fraud_score:.2f}"); results["combined"].append(r)
            r = _run_agentic(f, db); print(f"         agentic   {r.duration:>5.1f}s  risk={r.fraud_score:.2f}  {r.extra}"); results["agentic"].append(r)
    finally:
        db.close()

    # Timing summary
    print()
    print("=" * 120)
    print("TIMING (legacy=extract-only; add ~4-5s for the 2nd fraud call in production)")
    print("=" * 120)
    print(f"{'File':<32} {'Legacy':>8} {'Combined':>9} {'Agentic':>9}")
    print("-" * 120)
    sums = {"legacy": 0.0, "combined": 0.0, "agentic": 0.0}
    for i, f in enumerate(files):
        row = f"{f.name:<32}"
        for m in ("legacy", "combined", "agentic"):
            s = results[m][i]
            row += f" {s.duration:>7.1f}s"
            sums[m] += s.duration
        print(row)
    print("-" * 120)
    n = len(files)
    print(f"{'TOTAL':<32} {sums['legacy']:>7.1f}s {sums['combined']:>8.1f}s {sums['agentic']:>8.1f}s")
    print(f"{'AVG':<32} {sums['legacy']/n:>7.1f}s {sums['combined']/n:>8.1f}s {sums['agentic']/n:>8.1f}s")
    legacy_adjusted = sums["legacy"] + 4.5 * n  # adjust legacy for missing fraud call
    print()
    print("Adjusted legacy (add 4.5s/doc for fraud call): "
          f"{legacy_adjusted:.1f}s total → combined speedup {legacy_adjusted/sums['combined']:.2f}x, "
          f"agentic speedup {legacy_adjusted/sums['agentic']:.2f}x")

    # Fraud comparison
    print()
    print("=" * 120)
    print("FRAUD DETECTION")
    print("=" * 120)
    print(f"{'File':<32} {'Combined':>30} {'Agentic':>40}")
    print("-" * 120)
    for i, f in enumerate(files):
        c = results["combined"][i]
        a = results["agentic"][i]
        c_str = f"{c.fraud_score:.2f} {c.fraud_level}({c.fraud_flags})"
        a_str = f"{a.fraud_score:.2f} {a.fraud_level}({a.fraud_flags})"
        print(f"{f.name:<32} {c_str:>30} {a_str:>40}")

    # Quality: agreement on merchant / totals
    print()
    print("=" * 120)
    print("QUALITY: 3-way agreement on key fields")
    print("=" * 120)
    identical_count = 0
    for i, f in enumerate(files):
        l = results["legacy"][i]; c = results["combined"][i]; a = results["agentic"][i]
        if l.error or c.error or a.error:
            print(f"  ERR {f.name}: {l.error or ''} / {c.error or ''} / {a.error or ''}")
            continue

        diffs: list[str] = []
        for field in ("merchant_normalized", "category", "grand_total", "item_count"):
            uniq = {getattr(l, field), getattr(c, field), getattr(a, field)}
            if len(uniq) > 1:
                diffs.append(
                    f"{field}: L={getattr(l, field)!r} C={getattr(c, field)!r} A={getattr(a, field)!r}"
                )
        if not diffs:
            identical_count += 1
            print(f"  ✓ {f.name}")
        else:
            print(f"  ⚠ {f.name}")
            for d in diffs:
                print(f"     {d}")
    print()
    print(f"→ {identical_count}/{n} docs identical across all 3 modes")

    # Agentic tool stats
    print()
    print("=" * 120)
    print("AGENTIC MODE — tool call statistics")
    print("=" * 120)
    for i, f in enumerate(files):
        a = results["agentic"][i]
        print(f"  {f.name:<32} {a.extra}")

    # Verdict
    print()
    print("=" * 120)
    print("VERDICT")
    print("=" * 120)
    print(f"  Legacy avg     : {sums['legacy']/n:.1f}s/doc (+4.5s fraud = ~{sums['legacy']/n + 4.5:.1f}s in prod)")
    print(f"  Combined avg   : {sums['combined']/n:.1f}s/doc  [ 1 Gemini call + Python post-check ]")
    print(f"  Agentic avg    : {sums['agentic']/n:.1f}s/doc  [ 3-5 turn tool loop + history-aware ]")
    print(f"  3-way agreement: {identical_count}/{n} docs identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
