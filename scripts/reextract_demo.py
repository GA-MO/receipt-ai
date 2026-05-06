"""Re-extract demo documents and print a demo-ready report.

Targets filenames that match dataTest/demo/*, runs them serially (Semaphore(1)
in the backend already serializes anyway) so we can print per-document progress.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request

API = "http://localhost:8000/api"

DEMO_FILENAMES = [f"{i:02d}.jpeg" for i in range(1, 12)]


def _http(method: str, url: str):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_for(doc_id: str, timeout: int = 120) -> dict:
    start = time.time()
    while time.time() - start < timeout:
        d = _http("GET", f"{API}/documents/{doc_id}")
        if d["status"] != "processing":
            return d
        time.sleep(3)
    raise TimeoutError(f"timed out waiting on {doc_id}")


_ENG_RE = re.compile(r"[A-Za-z][A-Za-z' ,./()0-9-]{24,}")


def main() -> int:
    all_docs = _http("GET", f"{API}/documents?limit=500")
    by_filename = {d["filename"]: d for d in all_docs}

    targets = []
    for name in DEMO_FILENAMES:
        if name in by_filename:
            targets.append(by_filename[name])
        else:
            print(f"  ✗ {name}: not in DB (likely duplicate hash)")
    print(f"\nWill re-extract {len(targets)} demo documents.\n")

    results: list[dict] = []
    for i, doc in enumerate(targets, 1):
        print(f"[{i:>2}/{len(targets)}] {doc['filename']} — triggering…", flush=True)
        _http("POST", f"{API}/documents/{doc['id']}/reextract")
        t0 = time.time()
        final = wait_for(doc["id"])
        dt = time.time() - t0
        status = final["status"]
        conf = final.get("confidence") or 0.0
        print(f"         → {status} in {dt:.1f}s (conf={conf:.0%})", flush=True)
        results.append(final)

    print()
    print("=" * 120)
    print("DEMO RESULTS")
    print("=" * 120)

    for i, d in enumerate(results, 1):
        print()
        print(f"─── [{i}] {d['filename']} ".ljust(120, "─"))
        print(f"  Status      : {d['status']}   Confidence: {int((d.get('confidence') or 0) * 100)}%")
        print(f"  Merchant    : {d.get('merchant_name') or '-'}")
        print(f"  Normalized  : {d.get('merchant_normalized') or '-'}")
        print(
            f"  Doc No      : {d.get('document_number') or '-'}    "
            f"Date: {d.get('document_date') or '-'}"
        )
        print(f"  Category    : {d.get('category') or '-'}")
        print(
            f"  Subtotal/VAT/Total: "
            f"{d.get('subtotal') or 0:>10} / {d.get('vat') or 0:>8} / {d.get('grand_total') or 0:>10}"
        )

        items = d.get("items") or []
        print(f"  Items       : {len(items)}")
        for it in items:
            print(
                f"    - [{it.get('category') or '?':<22}] "
                f"{(it.get('product_name_raw') or '-'):<32} "
                f"→ {(it.get('product_name_normalized') or '-'):<26} "
                f"x{it.get('quantity') or '-'} @ {it.get('unit_price') or '-'} "
                f"= {it.get('line_total') or '-'}"
            )

        notes = (d.get("notes") or "").strip()
        if notes:
            print(f"  Notes       : {notes[:200]}")

        fraud_raw = d.get("fraud_flags")
        if fraud_raw:
            try:
                fj = json.loads(fraud_raw)
                ai = (fj.get("ai_analysis") or {}) if isinstance(fj, dict) else {}
                flags = fj.get("flags") if isinstance(fj, dict) else fj
                if ai.get("risk_score", 0) > 0 or flags:
                    print(
                        f"  Fraud       : risk={ai.get('risk_score', 0):.2f} "
                        f"({ai.get('risk_level')}) — {ai.get('summary', '')[:80]}"
                    )
                    for f in (flags or [])[:5]:
                        print(
                            f"                ● [{f.get('severity', '?')}] "
                            f"{f.get('label', '?')} — {f.get('detail', '')[:80]}"
                        )
            except Exception:
                pass

        eng = _ENG_RE.search(notes)
        if eng:
            print(f"  ⚠ English fragment in notes: '{eng.group(0)[:80]}'")

    # Aggregate flags
    print()
    print("=" * 120)
    print("FLAGS")
    print("=" * 120)

    def flag_list(label: str, items: list[dict], fmt):
        print(f"\n{label}: {len(items)}")
        for it in items:
            print(f"  - {it['filename']}: {fmt(it)}")

    low_conf = [d for d in results if (d.get("confidence") or 0) < 0.8]
    errored = [d for d in results if d["status"] == "error"]
    english_notes = [
        d for d in results if _ENG_RE.search((d.get("notes") or ""))
    ]
    no_normalized = [
        d for d in results
        if not d.get("merchant_normalized") and d.get("merchant_name")
    ]
    incomplete_cat = [
        d for d in results
        if d.get("items") and any(not it.get("category") for it in d["items"])
    ]

    flag_list("❗ Errored", errored, lambda d: d.get("error_message") or "?")
    flag_list("⚠️  Confidence < 80%", low_conf, lambda d: f"{int((d.get('confidence') or 0)*100)}%")
    flag_list(
        "🔤 English fragment in notes",
        english_notes,
        lambda d: _ENG_RE.search(d["notes"]).group(0)[:80],
    )
    flag_list("🏷️  No merchant_normalized", no_normalized, lambda d: d.get("merchant_name") or "-")
    flag_list(
        "📦 Items missing category",
        incomplete_cat,
        lambda d: f"{sum(1 for it in d['items'] if not it.get('category'))}/{len(d['items'])}",
    )

    avg_conf = sum((d.get("confidence") or 0) for d in results) / max(len(results), 1)
    print()
    print("=" * 120)
    print(f"DONE: {len(results)} docs, avg confidence = {avg_conf:.1%}")
    return 0 if not errored else 1


if __name__ == "__main__":
    sys.exit(main())
