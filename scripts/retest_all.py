"""
Upload all test files one by one, wait for processing, and dump results as JSON.

Usage: cd backend && uv run python ../scripts/retest_all.py
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

BASE = os.environ.get("API_BASE", "http://localhost:8000/api")
DATA_DIR = Path(__file__).resolve().parent.parent / "dataTest"
OUTPUT = Path(__file__).resolve().parent.parent / "dataTest" / "test_results.json"


def upload(filepath: str) -> dict | None:
    filename = os.path.basename(filepath)
    boundary = "----FormBoundary7MA4YWxkTrZu0gW"
    with open(filepath, "rb") as f:
        file_data = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{BASE}/documents/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        if e.code == 409:
            print(f"    (duplicate, skipped)")
            return None
        print(f"    ERROR {e.code}: {error_body[:200]}")
        return None


def get_doc(doc_id: str) -> dict:
    with urllib.request.urlopen(f"{BASE}/documents/{doc_id}") as resp:
        return json.loads(resp.read())


def wait_for(doc_id: str, timeout: int = 180) -> dict | None:
    for _ in range(timeout // 3):
        time.sleep(3)
        d = get_doc(doc_id)
        if d["status"] != "processing":
            return d
    return None


def main():
    groups = {}
    for group_dir in sorted(DATA_DIR.iterdir()):
        if not group_dir.is_dir() or group_dir.name.startswith("."):
            continue
        groups[group_dir.name] = sorted(
            f for f in group_dir.iterdir()
            if f.is_file() and not f.name.startswith("_") and not f.name.startswith(".")
        )

    all_results = []
    total = sum(len(files) for files in groups.values())
    idx = 0

    for group_name, files in groups.items():
        print(f"\n{'='*60}")
        print(f"  {group_name} ({len(files)} files)")
        print(f"{'='*60}")

        for f in files:
            idx += 1
            print(f"\n[{idx}/{total}] {group_name}/{f.name}")

            upload_result = upload(str(f))
            if not upload_result:
                all_results.append({
                    "group": group_name,
                    "filename": f.name,
                    "format": f.suffix.lstrip(".").upper(),
                    "size_kb": round(f.stat().st_size / 1024, 1),
                    "status": "skipped",
                })
                continue

            doc_id = upload_result["id"]
            print(f"    Uploaded → processing...")

            result = wait_for(doc_id)
            if not result:
                print(f"    TIMEOUT")
                all_results.append({
                    "group": group_name,
                    "filename": f.name,
                    "format": f.suffix.lstrip(".").upper(),
                    "size_kb": round(f.stat().st_size / 1024, 1),
                    "status": "timeout",
                })
                continue

            # Parse fraud
            fraud_risk = None
            fraud_flags_count = 0
            fraud_summary = ""
            fraud_flags_detail = []
            if result.get("fraud_flags"):
                try:
                    parsed = json.loads(result["fraud_flags"])
                    if isinstance(parsed, dict):
                        ai = parsed.get("ai_analysis", {})
                        flags = parsed.get("flags", [])
                        fraud_risk = ai.get("risk_score", 0) if ai else 0
                        fraud_flags_count = len(flags)
                        fraud_summary = ai.get("summary", "") if ai else ""
                        fraud_flags_detail = [f"{fl['severity']}: {fl['label']}" for fl in flags]
                except:
                    pass

            entry = {
                "group": group_name,
                "filename": f.name,
                "format": f.suffix.lstrip(".").upper(),
                "size_kb": round(f.stat().st_size / 1024, 1),
                "status": result["status"],
                "merchant": result.get("merchant_name"),
                "document_number": result.get("document_number"),
                "document_date": result.get("document_date"),
                "category": result.get("category"),
                "grand_total": result.get("grand_total"),
                "items_count": len(result.get("items", [])),
                "confidence": result.get("confidence"),
                "fraud_risk": fraud_risk,
                "fraud_flags_count": fraud_flags_count,
                "fraud_summary": fraud_summary,
                "fraud_flags": fraud_flags_detail,
                "error": result.get("error_message"),
                "notes": (result.get("notes") or "")[:200],
            }
            all_results.append(entry)

            status_icon = "✅" if result["status"] == "extracted" else "❌"
            total_str = f"฿{result['grand_total']:,.2f}" if result.get("grand_total") else "(none)"
            fraud_str = f"risk={fraud_risk*100:.0f}%" if fraud_risk is not None else ""
            print(f"    {status_icon} {result['status']} | {result.get('merchant_name','?')} | {total_str} | items={len(result.get('items',[]))} | conf={result.get('confidence',0):.0%} | {fraud_str}")

    # Save results
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n\nResults saved to {OUTPUT}")
    print(f"Total: {len(all_results)} files processed")

    # Summary
    extracted = sum(1 for r in all_results if r["status"] == "extracted")
    errors = sum(1 for r in all_results if r["status"] == "error")
    skipped = sum(1 for r in all_results if r["status"] == "skipped")
    print(f"Extracted: {extracted}, Errors: {errors}, Skipped: {skipped}")


if __name__ == "__main__":
    main()
