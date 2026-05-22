#!/usr/bin/env python3
"""End-to-end smoke test for the Drop & Review inbox flow.

Steps:

1. Upload all files in ``dataTest/demo/`` to ``POST /api/inbox`` in one batch.
2. Poll the dashboard until processing settles (or 5 min timeout).
3. Print a summary of how the system auto-grouped the receipts: orphans,
   non-receipts, errors, and visits per store × month.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

API_BASE = "http://localhost:8000/api"
DATA_DIR = Path(__file__).parent.parent / "dataTest" / "demo"


def upload_all(client: httpx.Client) -> dict:
    files = sorted(p for p in DATA_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".jpeg", ".jpg", ".png", ".pdf"})
    if not files:
        print(f"❌ No files in {DATA_DIR}")
        sys.exit(1)
    print(f"📤 Uploading {len(files)} files to /api/inbox ...")
    multipart = [
        ("files", (f.name, f.read_bytes(), "image/jpeg" if f.suffix.lower() in {".jpeg", ".jpg"} else "application/octet-stream"))
        for f in files
    ]
    r = client.post(f"{API_BASE}/inbox", files=multipart, timeout=60)
    r.raise_for_status()
    body = r.json()
    print(f"   ✓ {len(body['document_ids'])} accepted, {len(body['duplicates'])} dup, {len(body['failures'])} failed")
    for fail in body["failures"]:
        print(f"     ✗ {fail['filename']}: {fail['detail']}")
    return body


def poll_dashboard(client: httpx.Client, timeout: int = 600) -> dict:
    start = time.time()
    last_print = 0.0
    while time.time() - start < timeout:
        r = client.get(f"{API_BASE}/inbox/dashboard")
        r.raise_for_status()
        d = r.json()
        c = d["counts"]
        now = time.time()
        if now - last_print > 5:
            print(
                f"   processing={c['processing']:>3} orphans={c['orphans']:>3} "
                f"non_receipts={c['non_receipts']:>3} errors={c['errors']:>3} "
                f"visits={c['visits']:>3}",
            )
            last_print = now
        if c["processing"] == 0:
            return d
        time.sleep(3)
    raise TimeoutError(f"Still processing after {timeout}s")


def print_summary(d: dict) -> None:
    c = d["counts"]
    print()
    print("=" * 70)
    print("📊  DASHBOARD SUMMARY")
    print("=" * 70)
    print(f"  visits:       {c['visits']:>3}   ({c['attention']} needs attention)")
    print(f"  orphans:      {c['orphans']:>3}   (AI couldn't read merchant)")
    print(f"  non_receipts: {c['non_receipts']:>3}   (Gemini said: not a receipt)")
    print(f"  errors:       {c['errors']:>3}   (extraction failed)")
    print(f"  months:       {', '.join(d['available_months']) or '—'}")
    print()
    if d["visits"]:
        print("─── VISITS ─────────────────────────────────────────────────────────")
        for v in d["visits"]:
            mark = "🆕" if v["new_doc_count"] > 0 else "  "
            label = v["store_label"] or v["store_key"] or "(no label)"
            period = v["report_period"] or "no-period"
            print(
                f"  {mark} {label:30s}  {period}  · {v['document_count']:>2} ใบ "
                f"({v['reviewed_count']}/{v['document_count']} reviewed)"
            )
    if d["orphans"]:
        print()
        print("─── ORPHANS (no merchant) ─────────────────────────────────────────")
        for o in d["orphans"]:
            print(f"  • {o['filename']}  conf={o['confidence']}")
    if d["non_receipts"]:
        print()
        print("─── NON-RECEIPTS ───────────────────────────────────────────────────")
        for n in d["non_receipts"]:
            print(f"  • {n['filename']}  conf={n['confidence']}  notes={(n.get('merchant_name') or '')[:40]}")
    if d["errors"]:
        print()
        print("─── ERRORS ─────────────────────────────────────────────────────────")
        for e in d["errors"]:
            print(f"  • {e['filename']}")
    print("=" * 70)


def main():
    if not DATA_DIR.exists():
        print(f"❌ No demo dir at {DATA_DIR}")
        sys.exit(1)
    with httpx.Client(timeout=60) as client:
        # Health check.
        try:
            client.get(f"{API_BASE}/inbox/dashboard", timeout=5).raise_for_status()
        except Exception as e:
            print(f"❌ Backend unreachable at {API_BASE}: {e}")
            sys.exit(1)

        upload_all(client)
        print()
        print("⏳ Waiting for extraction to finish...")
        d = poll_dashboard(client)
        print_summary(d)


if __name__ == "__main__":
    main()
