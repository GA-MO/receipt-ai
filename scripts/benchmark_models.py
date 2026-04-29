"""Compare LLM models on a single receipt — latency, cost, accuracy.

Usage:
    cd backend && .venv/bin/python ../scripts/benchmark_models.py \\
        --doc-id 4e55c50e-dcbb-45bb-9c75-74c2d6719f15

Bypasses the FastAPI app — calls OpenRouter directly per model so we capture
exact token usage and per-call $ cost from /api/v1/generation. Re-uses the
production prompts (SYSTEM_INSTRUCTION + EXTRACTION_PROMPT + fraud schema)
so apples-to-apples comparison.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from openai import OpenAI

# Make app/ importable when run from repo root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Document  # noqa: E402
from app.services.extraction import EXTRACTION_PROMPT, parse_extraction_payload  # noqa: E402
from app.services.extraction_combined import _build_system_instruction  # noqa: E402


DEFAULT_MODELS = [
    "google/gemini-2.5-flash-lite",
    "openai/gpt-4.1-mini",
    "google/gemini-2.5-flash",
    "anthropic/claude-haiku-4.5",
    "openai/gpt-5-mini",
    "google/gemini-2.5-pro",
    "qwen/qwen3-vl-235b-a22b-instruct",
]


@dataclass
class RunResult:
    model: str
    ok: bool
    latency_s: float = 0.0
    cost_usd: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    extraction: dict = field(default_factory=dict)
    fraud: dict | None = None
    accuracy: dict = field(default_factory=dict)
    error: str | None = None
    raw: str = ""


def _load_image_data_url(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }.get(suffix, "image/jpeg")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}", mime


def _user_content(image_data_url: str, mime: str) -> list[dict]:
    parts: list[dict] = [{"type": "text", "text": EXTRACTION_PROMPT}]
    if mime == "application/pdf":
        parts.append(
            {
                "type": "file",
                "file": {"filename": "doc.pdf", "file_data": image_data_url},
            }
        )
    else:
        parts.append({"type": "image_url", "image_url": {"url": image_data_url}})
    return parts


def _fetch_generation_cost(api_key: str, generation_id: str) -> float | None:
    """Pull exact $ cost from OpenRouter /api/v1/generation."""
    # OpenRouter sometimes lags 1-2s before the generation record is available.
    url = f"{settings.openrouter_base_url.rstrip('/')}/generation"
    headers = {"Authorization": f"Bearer {api_key}"}
    for attempt in range(5):
        try:
            r = httpx.get(url, params={"id": generation_id}, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json().get("data") or {}
                cost = data.get("total_cost")
                if cost is not None:
                    return float(cost)
            time.sleep(1.0 + attempt * 0.5)
        except Exception:
            time.sleep(1.0)
    return None


def run_one(model: str, image_data_url: str, mime: str) -> RunResult:
    api_key = settings.openrouter_api_key
    if not api_key:
        return RunResult(model=model, ok=False, error="OPENROUTER_API_KEY not set")

    client = OpenAI(
        base_url=settings.openrouter_base_url,
        api_key=api_key,
        timeout=180.0,
    )

    messages = [
        {"role": "system", "content": _build_system_instruction()},
        {"role": "user", "content": _user_content(image_data_url, mime)},
    ]

    t0 = time.perf_counter()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        return RunResult(
            model=model,
            ok=False,
            latency_s=time.perf_counter() - t0,
            error=str(exc)[:300],
        )
    latency = time.perf_counter() - t0

    raw = (resp.choices[0].message.content or "").strip()
    usage = resp.usage
    gen_id = resp.id

    cost = _fetch_generation_cost(api_key, gen_id) if gen_id else None

    extraction_payload: dict = {}
    fraud_payload: dict | None = None
    parse_error: str | None = None
    try:
        data = json.loads(raw)
        if isinstance(data, list) and data:
            data = data[0]
        if isinstance(data, dict):
            extraction_payload = data
            fraud_payload = data.get("fraud_analysis")
    except json.JSONDecodeError as exc:
        parse_error = f"invalid JSON: {exc}"

    return RunResult(
        model=model,
        ok=parse_error is None,
        latency_s=latency,
        cost_usd=cost,
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        extraction=extraction_payload,
        fraud=fraud_payload,
        error=parse_error,
        raw=raw,
    )


# ---------------------------------------------------------------------------
# Accuracy scoring
# ---------------------------------------------------------------------------


def _norm(s) -> str:
    return (str(s or "")).strip().lower()


def _approx_eq(a, b, tol: float = 1.0) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def score(extraction: dict, ground_truth: dict) -> dict:
    """Field-level accuracy + items overlap."""
    out: dict = {}
    out["merchant_match"] = _norm(extraction.get("merchant_name")) == _norm(
        ground_truth.get("merchant_name")
    )
    out["normalized_match"] = _norm(extraction.get("merchant_normalized")) == _norm(
        ground_truth.get("merchant_normalized")
    )
    out["date_match"] = _norm(extraction.get("document_date")) == _norm(
        ground_truth.get("document_date")
    )
    out["total_match"] = _approx_eq(
        extraction.get("grand_total"), ground_truth.get("grand_total")
    )
    out["category_match"] = _norm(extraction.get("category")) == _norm(
        ground_truth.get("category")
    )

    gt_items = ground_truth.get("items", [])
    pred_items = extraction.get("items", []) or []
    out["items_count_match"] = len(pred_items) == len(gt_items)

    gt_names = {_norm(i.get("product_name_normalized")) for i in gt_items}
    pred_names = {_norm(i.get("product_name_normalized")) for i in pred_items}
    if gt_names:
        out["items_name_overlap"] = round(
            len(gt_names & pred_names) / len(gt_names), 2
        )
    else:
        out["items_name_overlap"] = 0.0

    gt_totals = sorted(
        round(float(i.get("line_total") or 0), 2) for i in gt_items
    )
    pred_totals = sorted(
        round(float(i.get("line_total") or 0), 2) for i in pred_items
    )
    out["items_total_match"] = gt_totals == pred_totals

    # Composite score: weighted sum (0..1)
    weights = {
        "merchant_match": 1.5,
        "date_match": 1.0,
        "total_match": 2.0,
        "category_match": 0.5,
        "items_count_match": 1.0,
        "items_name_overlap": 1.5,  # already 0..1
        "items_total_match": 1.5,
    }
    total_w = sum(weights.values())
    score_sum = 0.0
    for k, w in weights.items():
        v = out.get(k, False)
        if isinstance(v, bool):
            v = 1.0 if v else 0.0
        score_sum += w * float(v)
    out["composite"] = round(score_sum / total_w, 3)
    return out


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_table(results: list[RunResult], ground_truth: dict) -> None:
    print()
    print("=" * 110)
    print(f"{'model':<46} {'ok':<3} {'lat(s)':>8} {'cost$':>10} {'in tok':>8} {'out tok':>8} {'score':>7}")
    print("-" * 110)
    for r in sorted(results, key=lambda x: -(x.accuracy.get("composite") or 0)):
        cost = f"{r.cost_usd:.5f}" if r.cost_usd is not None else "  n/a"
        score_s = f"{r.accuracy.get('composite', 0):.3f}" if r.ok else "  n/a"
        print(
            f"{r.model:<46} {('OK' if r.ok else 'ERR'):<3} "
            f"{r.latency_s:>8.2f} {cost:>10} "
            f"{(r.prompt_tokens or 0):>8} {(r.completion_tokens or 0):>8} "
            f"{score_s:>7}"
        )
    print("=" * 110)
    print()
    print("Per-model details (vs ground truth):")
    for r in results:
        print(f"\n--- {r.model} ---")
        if not r.ok:
            print(f"  error: {r.error}")
            continue
        ext = r.extraction
        a = r.accuracy
        print(f"  merchant   : {ext.get('merchant_name')!r:60} match={a['merchant_match']}")
        print(f"  normalized : {ext.get('merchant_normalized')!r:60} match={a['normalized_match']}")
        print(f"  date       : {ext.get('document_date')!r:60} match={a['date_match']}")
        print(f"  total      : {ext.get('grand_total')!r:60} match={a['total_match']}")
        print(f"  category   : {ext.get('category')!r:60} match={a['category_match']}")
        items = ext.get("items") or []
        print(f"  items      : {len(items)}/{len(ground_truth.get('items', []))} count_match={a['items_count_match']}, name_overlap={a['items_name_overlap']}, totals_match={a['items_total_match']}")
        for it in items:
            print(
                f"    - {it.get('product_name_normalized'):<35} "
                f"x{it.get('quantity')} @ {it.get('unit_price')} = {it.get('line_total')}"
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc-id", required=True, help="Document ID to benchmark")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument(
        "--truth-file",
        default=None,
        help="Path to a JSON file with ground-truth values. Falls back to current DB state.",
    )
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "dataTest" / "benchmark_results"),
        help="Where to dump the JSON results",
    )
    args = parser.parse_args()

    # Resolve doc → file path + ground truth (current DB state).
    db = SessionLocal()
    try:
        doc = db.query(Document).filter_by(id=args.doc_id).first()
        if not doc:
            sys.exit(f"Document {args.doc_id} not found")
        # Resolve file path (DB stores it relative to backend cwd).
        file_path = Path(doc.file_path)
        if not file_path.is_absolute():
            file_path = ROOT / "backend" / doc.file_path
        if not file_path.exists():
            sys.exit(f"File not found: {file_path}")

        if args.truth_file:
            ground_truth = json.loads(Path(args.truth_file).read_text())
            print(f"Ground truth: loaded from {args.truth_file}")
        else:
            ground_truth = {
                "merchant_name": doc.merchant_name,
                "merchant_normalized": doc.merchant_normalized,
                "document_date": doc.document_date,
                "grand_total": float(doc.grand_total) if doc.grand_total else None,
                "category": doc.category,
                "items": [
                    {
                        "product_name_normalized": it.product_name_normalized,
                        "quantity": float(it.quantity) if it.quantity else None,
                        "unit_price": float(it.unit_price) if it.unit_price else None,
                        "line_total": float(it.line_total) if it.line_total else None,
                    }
                    for it in doc.items
                ],
            }
            print("Ground truth: current DB state")
    finally:
        db.close()

    print(f"Doc       : {args.doc_id}")
    print(f"File      : {file_path}")
    print(f"Ground truth (current DB state):")
    print(f"  merchant : {ground_truth['merchant_name']}")
    print(f"  date     : {ground_truth['document_date']}")
    print(f"  total    : {ground_truth['grand_total']}")
    print(f"  items    : {len(ground_truth['items'])}")

    image_data_url, mime = _load_image_data_url(file_path)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    print(f"\nBenchmarking {len(models)} models...\n")

    results: list[RunResult] = []
    for m in models:
        print(f"  → {m} ...", end=" ", flush=True)
        r = run_one(m, image_data_url, mime)
        if r.ok:
            r.accuracy = score(r.extraction, ground_truth)
            print(f"OK ({r.latency_s:.1f}s, score={r.accuracy['composite']})")
        else:
            print(f"ERR: {r.error[:80] if r.error else 'unknown'}")
        results.append(r)

    print_table(results, ground_truth)

    # Save raw results
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{args.doc_id}_{int(time.time())}.json"
    out_file.write_text(
        json.dumps(
            {
                "doc_id": args.doc_id,
                "ground_truth": ground_truth,
                "results": [
                    {
                        "model": r.model,
                        "ok": r.ok,
                        "latency_s": round(r.latency_s, 3),
                        "cost_usd": r.cost_usd,
                        "prompt_tokens": r.prompt_tokens,
                        "completion_tokens": r.completion_tokens,
                        "extraction": r.extraction,
                        "accuracy": r.accuracy,
                        "error": r.error,
                    }
                    for r in results
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"\nSaved: {out_file}")


if __name__ == "__main__":
    main()
