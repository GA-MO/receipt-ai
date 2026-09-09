"""Sweep candidate models over the demo set: accuracy / latency / cost.

Runs the production extraction pipeline once per (model, image), scores it with
measure_accuracy.py, and prices the run from OpenRouter's live rate card.
Replaces the old benchmark_models.py, which still imported the removed
extraction_combined module.

Usage:
    cd backend && .venv/bin/python ../scripts/sweep_models.py
    cd backend && .venv/bin/python ../scripts/sweep_models.py --models google/gemini-3.1-flash-lite,x/y
"""
from __future__ import annotations

import argparse, json, statistics, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.config import settings  # noqa: E402
from app.services import llm_client  # noqa: E402
from measure_accuracy import score_image, GT_PATH  # noqa: E402

CANDIDATES = [
    "google/gemini-3.1-flash-lite",   # current
    "google/gemini-3-flash-preview",  # old default
    "google/gemini-3.5-flash-lite",
    "google/gemini-3.5-flash",
    "google/gemini-3.6-flash",
    "google/gemini-3.7-flash",
    "google/gemini-3.8-flash",
]

_lock = threading.Lock()
_usage: dict[str, list] = {}


def pricing():
    with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=60) as r:
        d = json.load(r)["data"]
    return {m["id"]: (float(m["pricing"]["prompt"]), float(m["pricing"]["completion"]))
            for m in d}


def install_recorder():
    client = llm_client._get_openai_client()
    orig = client.chat.completions.create

    def wrapped(**kw):
        t0 = time.time()
        r = orig(**kw)
        dt = time.time() - t0
        u = r.usage
        with _lock:
            _usage.setdefault(kw["model"], []).append(
                (dt, u.prompt_tokens if u else 0, u.completion_tokens if u else 0)
            )
        return r

    client.chat.completions.create = wrapped


def agg(rs, scope="read"):
    n = sum(r[scope]["gt_lines"] for r in rs)
    f = lambda k: sum(r[scope][k] for r in rs) / n  # noqa: E731
    return {
        "gt_lines": n,
        "product_acc": f("product_correct"),
        "quantity_acc": f("quantity_correct"),
        "line_acc": f("line_correct"),
        "missed": sum(r[scope]["missed"] for r in rs),
        "invented": sum(r[scope]["invented"] for r in rs),
        "merchant_acc": sum(1 for r in rs if r["merchant_ok"]) / len(rs),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(CANDIDATES))
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]

    price = pricing()
    install_recorder()
    gt_all = json.loads(GT_PATH.read_text())["images"]
    names = list(gt_all)
    out = {}

    for model in models:
        settings.openrouter_model = model
        _usage.pop(model, None)
        print(f"\n### {model}", file=sys.stderr)
        t0 = time.time()
        results = []
        errs = []
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = {ex.submit(score_image, n, gt_all[n]): n for n in names}
            for f, n in futs.items():
                try:
                    results.append(f.result())
                except Exception as e:  # noqa: BLE001
                    errs.append((n, repr(e)[:200]))
        wall = time.time() - t0
        if not results:
            out[model] = {"error": errs[:3]}
            print(f"  FAILED: {errs[:2]}", file=sys.stderr)
            continue
        u = _usage.get(model, [])
        lat = [x[0] for x in u]
        pin = sum(x[1] for x in u)
        pout = sum(x[2] for x in u)
        pi, po = price.get(model, (0, 0))
        cost = pin * pi + pout * po
        a = agg(results)
        a["catalog"] = agg(results, "catalog")
        a.update({
            "receipts": len(results), "errors": errs,
            "p50_latency_s": round(statistics.median(lat), 2) if lat else None,
            "mean_latency_s": round(statistics.fmean(lat), 2) if lat else None,
            "calls": len(u),
            "cost_usd_total": round(cost, 5),
            "cost_per_receipt_usd": round(cost / max(len(results), 1), 6),
            "wall_s": round(wall, 1),
        })
        out[model] = a
        print(f"  line={a['line_acc']*100:.1f}% qty={a['quantity_acc']*100:.1f}% "
              f"p50={a['p50_latency_s']}s cost/receipt=${a['cost_per_receipt_usd']:.5f}", file=sys.stderr)

    dest = ROOT / "dataTest" / "sweep_results.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nwrote {dest}")

    hdr = (f"{'model':<32}{'line%':>7}{'qty%':>7}{'miss':>6}{'inv':>5}"
           f"{'cat.line%':>11}{'merch%':>8}{'p50 s':>8}{'$/receipt':>11}")
    print("\n" + hdr); print("-" * len(hdr))
    for m, a in out.items():
        if "error" in a or "line_acc" not in a:
            print(f"{m:<34}  ERROR"); continue
        print(f"{m:<32}{a['line_acc']*100:>7.1f}{a['quantity_acc']*100:>7.1f}"
              f"{a['missed']:>6}{a['invented']:>5}{a['catalog']['line_acc']*100:>11.1f}"
              f"{a['merchant_acc']*100:>8.1f}"
              f"{a['p50_latency_s']:>8.2f}{a['cost_per_receipt_usd']:>11.5f}")


if __name__ == "__main__":
    main()
