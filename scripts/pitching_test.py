"""
Pitching-day end-to-end measurement.
Uploads dataTest/demo/* one by one, captures per-file metrics,
verifies same-merchant clustering and fraud detection, prints a summary.

Usage: cd backend && .venv/bin/python ../scripts/pitching_test.py
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("API_BASE", "http://localhost:8000/api")
DATA_DIR = Path(__file__).resolve().parent.parent / "dataTest" / "demo"
OUT = Path(__file__).resolve().parent.parent / "dataTest" / "pitching_results.json"


def upload(filepath: Path) -> dict | None:
    boundary = "----PitchingBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filepath.name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + filepath.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{BASE}/documents/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}: {e.read().decode()[:200]}")
    except Exception as e:
        print(f"    upload error: {e}")
    return None


def get_doc(doc_id: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"{BASE}/documents/{doc_id}", timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"    get error: {e}")
        return None


def wait(doc_id: str, timeout: int = 180) -> tuple[dict | None, float]:
    start = time.time()
    while time.time() - start < timeout:
        d = get_doc(doc_id)
        if d and d["status"] != "processing":
            return d, time.time() - start
        time.sleep(1.5)
    return None, time.time() - start


def parse_fraud(s: str | None) -> dict:
    if not s:
        return {"risk_score": 0, "flags": [], "summary": ""}
    try:
        p = json.loads(s)
        ai = p.get("ai_analysis", {}) or {}
        return {
            "risk_score": ai.get("risk_score", 0),
            "flags": [f"{f.get('severity')}:{f.get('label')}" for f in p.get("flags", [])],
            "summary": ai.get("summary", "") or "",
        }
    except Exception:
        return {"risk_score": 0, "flags": [], "summary": ""}


def main() -> int:
    files = sorted(DATA_DIR.glob("*"))
    files = [f for f in files if f.is_file() and not f.name.startswith(".")]
    if not files:
        print(f"No files in {DATA_DIR}")
        return 1

    print(f"\n{'=' * 70}")
    print(f"  PITCHING DAY END-TO-END TEST  ({len(files)} files)")
    print(f"{'=' * 70}\n")

    results = []
    latencies: list[float] = []

    for i, f in enumerate(files, 1):
        size_kb = round(f.stat().st_size / 1024, 1)
        print(f"[{i:2d}/{len(files)}] {f.name}  ({size_kb} KB)")
        t_up_start = time.time()
        up = upload(f)
        t_up = time.time() - t_up_start
        if not up:
            results.append({"file": f.name, "status": "upload_failed"})
            continue
        doc_id = up["id"]
        doc, t_proc = wait(doc_id)
        if not doc:
            print(f"    TIMEOUT after {t_proc:.1f}s")
            results.append({"file": f.name, "status": "timeout", "doc_id": doc_id})
            continue
        latencies.append(t_proc)
        fraud = parse_fraud(doc.get("fraud_flags"))
        result = {
            "file": f.name,
            "doc_id": doc_id,
            "status": doc.get("status"),
            "merchant_raw": doc.get("merchant_name"),
            "merchant_normalized": doc.get("merchant_normalized"),
            "doc_number": doc.get("document_number"),
            "doc_date": doc.get("document_date"),
            "subtotal": doc.get("subtotal"),
            "discount": doc.get("discount"),
            "vat": doc.get("vat"),
            "grand_total": doc.get("grand_total"),
            "confidence": doc.get("confidence"),
            "items": len(doc.get("items") or []),
            "fraud_risk_score": fraud["risk_score"],
            "fraud_flags": fraud["flags"],
            "fraud_summary": fraud["summary"],
            "upload_seconds": round(t_up, 2),
            "processing_seconds": round(t_proc, 2),
            "error": doc.get("error_message"),
        }
        results.append(result)
        print(
            f"    {doc.get('status'):>10s}  "
            f"merchant={doc.get('merchant_normalized') or doc.get('merchant_name') or '-'}  "
            f"total={doc.get('grand_total') or '-'}  "
            f"conf={doc.get('confidence')}  "
            f"items={len(doc.get('items') or [])}  "
            f"fraud={fraud['risk_score']}/{len(fraud['flags'])}  "
            f"⏱ {t_proc:.1f}s"
        )

    # Summary
    print(f"\n{'=' * 70}")
    print("  SUMMARY")
    print(f"{'=' * 70}\n")

    successful = [r for r in results if r.get("status") in ("extracted", "reviewed")]
    failed = [r for r in results if r.get("status") not in ("extracted", "reviewed")]
    confs = [r["confidence"] for r in successful if r.get("confidence") is not None]

    print(f"  Total uploaded     : {len(results)}")
    print(f"  Successful         : {len(successful)}")
    print(f"  Failed/timeout     : {len(failed)}")
    if latencies:
        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)]
        print(f"  Latency mean       : {statistics.mean(latencies):.2f}s")
        print(f"  Latency p50        : {p50:.2f}s")
        print(f"  Latency p95        : {p95:.2f}s")
        print(f"  Latency min/max    : {min(latencies):.2f}s / {max(latencies):.2f}s")
    if confs:
        print(f"  Confidence mean    : {statistics.mean(confs):.2f}")
        print(f"  Confidence min     : {min(confs):.2f}")

    # Fraud detection check — 05.jpeg (สุดาพาณิชย์) should flag date anomaly
    fraud_target = next((r for r in results if r["file"] == "05.jpeg"), None)
    if fraud_target:
        score = fraud_target.get("fraud_risk_score", 0)
        flags = fraud_target.get("fraud_flags", [])
        verdict = "✅ DETECTED" if score >= 0.5 or flags else "❌ MISSED"
        print(f"\n  Fraud target (05)  : {verdict}  risk={score}  flags={flags}")

    # Same-merchant clustering — 03.jpeg + 04.jpeg both = รวยสุรา
    same_merch = [r for r in results if r["file"] in ("03.jpeg", "04.jpeg")]
    if len(same_merch) >= 2:
        norms = {r["merchant_normalized"] for r in same_merch}
        verdict = "✅ MATCH" if len(norms) == 1 and None not in norms else "❌ MISMATCH"
        print(f"  Same-merchant test : {verdict}  normalized={norms}")

    # Persist
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n  Results saved to: {OUT}")
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
