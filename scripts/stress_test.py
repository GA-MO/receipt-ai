"""
Comprehensive API stability test — run against the live dev server.
Tests edge cases, error handling, concurrent uploads, and data integrity.

Usage: cd backend && uv run python ../scripts/stress_test.py
"""

import concurrent.futures
import io
import json
import os
import struct
import sys
import time
import zlib
from pathlib import Path

import requests

BASE = os.environ.get("API_BASE", "http://localhost:8000/api")
DATA_DIR = Path(__file__).resolve().parent.parent / "dataTest"

passed = 0
failed = 0
errors: list[str] = []


def ok(label: str):
    global passed
    passed += 1
    print(f"  ✅ {label}")


def fail(label: str, detail: str = ""):
    global failed
    failed += 1
    msg = f"  ❌ {label}: {detail}"
    errors.append(msg)
    print(msg)


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def make_tiny_png() -> bytes:
    def chunk(t: bytes, d: bytes) -> bytes:
        c = t + d
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(d)) + c + crc

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def upload_file(filepath: str | None = None, filename: str = "test.png", content: bytes | None = None):
    if filepath:
        with open(filepath, "rb") as f:
            return requests.post(f"{BASE}/documents/upload", files={"file": (os.path.basename(filepath), f)})
    return requests.post(f"{BASE}/documents/upload", files={"file": (filename, io.BytesIO(content or make_tiny_png()), "image/png")})


def wait_for_processing(doc_id: str, timeout: int = 120) -> dict | None:
    for _ in range(timeout // 2):
        r = requests.get(f"{BASE}/documents/{doc_id}")
        if r.status_code != 200:
            return None
        d = r.json()
        if d["status"] != "processing":
            return d
        time.sleep(2)
    return None


def cleanup_doc(doc_id: str):
    requests.delete(f"{BASE}/documents/{doc_id}")


# ──────────────────────────────────────────────────────────────
# 1. Upload Tests
# ──────────────────────────────────────────────────────────────

def test_upload_valid_formats():
    section("1. Upload — Valid Formats")
    created_ids = []

    for ext in ["jpg", "png", "webp"]:
        files = list(DATA_DIR.glob(f"*.{ext}"))
        if not files:
            print(f"  ⚠️  No .{ext} files in dataTest/, skipping")
            continue
        f = files[0]
        r = upload_file(str(f))
        if r.status_code == 200:
            ok(f"Upload .{ext} ({f.name}) → 200")
            created_ids.append(r.json()["id"])
        elif r.status_code == 409:
            ok(f"Upload .{ext} ({f.name}) → 409 duplicate (already uploaded)")
        else:
            fail(f"Upload .{ext} ({f.name})", f"status={r.status_code} body={r.text[:200]}")

    return created_ids


def test_upload_invalid():
    section("2. Upload — Invalid Files")

    # Wrong extension
    r = requests.post(f"{BASE}/documents/upload", files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")})
    if r.status_code == 400:
        ok("Reject .txt file → 400")
    else:
        fail("Reject .txt file", f"expected 400, got {r.status_code}")

    r = requests.post(f"{BASE}/documents/upload", files={"file": ("test.exe", io.BytesIO(b"\x00\x01"), "application/octet-stream")})
    if r.status_code == 400:
        ok("Reject .exe file → 400")
    else:
        fail("Reject .exe file", f"expected 400, got {r.status_code}")

    # Empty file
    r = requests.post(f"{BASE}/documents/upload", files={"file": ("empty.png", io.BytesIO(b""), "image/png")})
    if r.status_code in (200, 400, 422):
        ok(f"Empty file handled → {r.status_code}")
    else:
        fail("Empty file", f"unexpected status={r.status_code}")
    if r.status_code == 200:
        cleanup_doc(r.json()["id"])

    # No file at all
    r = requests.post(f"{BASE}/documents/upload")
    if r.status_code == 422:
        ok("Missing file field → 422")
    else:
        fail("Missing file field", f"expected 422, got {r.status_code}")


def test_upload_duplicate():
    section("3. Upload — Duplicate Detection")
    png = make_tiny_png()

    r1 = upload_file(content=png, filename="dup_test.png")
    if r1.status_code == 200:
        ok("First upload → 200")
        doc_id = r1.json()["id"]

        r2 = upload_file(content=png, filename="dup_test.png")
        if r2.status_code == 409:
            ok("Duplicate upload → 409")
        else:
            fail("Duplicate upload", f"expected 409, got {r2.status_code}")
            if r2.status_code == 200:
                cleanup_doc(r2.json()["id"])

        cleanup_doc(doc_id)
    elif r1.status_code == 409:
        ok("First upload was already a duplicate → 409 (OK)")
    else:
        fail("First upload", f"status={r1.status_code}")


# ──────────────────────────────────────────────────────────────
# 2. Document CRUD Tests
# ──────────────────────────────────────────────────────────────

def test_crud():
    section("4. Document CRUD")

    # Create
    r = upload_file(content=make_tiny_png(), filename=f"crud_{int(time.time())}.png")
    if r.status_code != 200:
        fail("Create document", f"status={r.status_code}")
        return
    doc_id = r.json()["id"]
    ok("Create document → 200")

    # Read
    r = requests.get(f"{BASE}/documents/{doc_id}")
    if r.status_code == 200:
        ok("Read document → 200")
    else:
        fail("Read document", f"status={r.status_code}")

    # Read 404
    r = requests.get(f"{BASE}/documents/nonexistent-id-12345")
    if r.status_code == 404:
        ok("Read nonexistent → 404")
    else:
        fail("Read nonexistent", f"expected 404, got {r.status_code}")

    # Update
    r = requests.put(f"{BASE}/documents/{doc_id}", json={
        "merchant_name": "ร้านทดสอบ API",
        "grand_total": 1234.56,
        "document_date": "2026-04-03",
        "category": "เบียร์",
    })
    if r.status_code == 200:
        d = r.json()
        checks = [
            d["merchant_name"] == "ร้านทดสอบ API",
            d["grand_total"] == 1234.56,
            d["document_date"] == "2026-04-03",
            d["category"] == "อาหารและเครื่องดื่ม",
        ]
        if all(checks):
            ok("Update document — all fields correct")
        else:
            fail("Update document", f"field mismatch: {d}")
    else:
        fail("Update document", f"status={r.status_code}")

    # Update 404
    r = requests.put(f"{BASE}/documents/nonexistent-id", json={"merchant_name": "x"})
    if r.status_code == 404:
        ok("Update nonexistent → 404")
    else:
        fail("Update nonexistent", f"expected 404, got {r.status_code}")

    # Update with Thai special chars
    r = requests.put(f"{BASE}/documents/{doc_id}", json={
        "merchant_name": "บจก. ทดสอบ (ไทย) 123 ™",
        "notes": "หมายเหตุ: ส่วนลด ฿50 — ภาษี 7%\nบรรทัดที่ 2",
    })
    if r.status_code == 200:
        d = r.json()
        if "ทดสอบ (ไทย)" in (d["merchant_name"] or "") and "\n" in (d["notes"] or ""):
            ok("Update with Thai + special chars — preserved")
        else:
            fail("Update with Thai chars", "content not preserved correctly")
    else:
        fail("Update with Thai chars", f"status={r.status_code}")

    # Approve
    r = requests.post(f"{BASE}/documents/{doc_id}/approve")
    if r.status_code == 200:
        d = r.json()
        if d["status"] == "reviewed" and d["needs_review"] is False and d["reviewed_at"]:
            ok("Approve document — status=reviewed, needs_review=False")
        else:
            fail("Approve document", f"unexpected state: {d['status']}, needs_review={d['needs_review']}")
    else:
        fail("Approve document", f"status={r.status_code}")

    # Approve 404
    r = requests.post(f"{BASE}/documents/nonexistent-id/approve")
    if r.status_code == 404:
        ok("Approve nonexistent → 404")
    else:
        fail("Approve nonexistent", f"expected 404, got {r.status_code}")

    # Delete
    r = requests.delete(f"{BASE}/documents/{doc_id}")
    if r.status_code == 200:
        ok("Delete document → 200")
    else:
        fail("Delete document", f"status={r.status_code}")

    # Verify deleted
    r = requests.get(f"{BASE}/documents/{doc_id}")
    if r.status_code == 404:
        ok("Verify deleted → 404")
    else:
        fail("Verify deleted", f"expected 404, got {r.status_code}")

    # Delete 404
    r = requests.delete(f"{BASE}/documents/nonexistent-id")
    if r.status_code == 404:
        ok("Delete nonexistent → 404")
    else:
        fail("Delete nonexistent", f"expected 404, got {r.status_code}")


# ──────────────────────────────────────────────────────────────
# 3. List / Filter / Pagination
# ──────────────────────────────────────────────────────────────

def test_list_and_filter():
    section("5. List / Filter / Pagination")

    r = requests.get(f"{BASE}/documents")
    if r.status_code == 200 and isinstance(r.json(), list):
        ok(f"List documents → 200 ({len(r.json())} docs)")
    else:
        fail("List documents", f"status={r.status_code}")

    # Count
    r = requests.get(f"{BASE}/documents/count")
    if r.status_code == 200 and "count" in r.json():
        ok(f"Count documents → {r.json()['count']}")
    else:
        fail("Count documents", f"status={r.status_code}")

    # Pagination
    r = requests.get(f"{BASE}/documents?skip=0&limit=2")
    if r.status_code == 200:
        ok(f"Pagination skip=0 limit=2 → {len(r.json())} docs")
    else:
        fail("Pagination", f"status={r.status_code}")

    # Filter by status
    for status in ["extracted", "reviewed", "error", "processing"]:
        r = requests.get(f"{BASE}/documents?status={status}")
        if r.status_code == 200:
            ok(f"Filter status={status} → {len(r.json())} docs")
        else:
            fail(f"Filter status={status}", f"status={r.status_code}")

    # Search
    r = requests.get(f"{BASE}/documents?search=ร้าน")
    if r.status_code == 200:
        ok(f"Search 'ร้าน' → {len(r.json())} docs")
    else:
        fail("Search Thai", f"status={r.status_code}")

    # Search with no results
    r = requests.get(f"{BASE}/documents?search=xyznonexistent999")
    if r.status_code == 200 and len(r.json()) == 0:
        ok("Search no results → empty list")
    else:
        fail("Search no results", f"status={r.status_code}, len={len(r.json())}")

    # Date range filter
    r = requests.get(f"{BASE}/documents?date_from=2020-01-01&date_to=2030-12-31")
    if r.status_code == 200:
        ok(f"Date range filter → {len(r.json())} docs")
    else:
        fail("Date range filter", f"status={r.status_code}")

    # Category filter
    r = requests.get(f"{BASE}/documents?category=อาหารและเครื่องดื่ม")
    if r.status_code == 200:
        ok(f"Category filter → {len(r.json())} docs")
    else:
        fail("Category filter", f"status={r.status_code}")


# ──────────────────────────────────────────────────────────────
# 4. Dashboard Endpoints
# ──────────────────────────────────────────────────────────────

def test_dashboard():
    section("6. Dashboard Endpoints")

    endpoints = [
        ("/dashboard/stats", "Stats"),
        ("/dashboard/daily-sales?days=30", "Daily Sales"),
        ("/dashboard/top-merchants?limit=5", "Top Merchants"),
        ("/dashboard/category-breakdown", "Category Breakdown"),
        ("/dashboard/vat-summary", "VAT Summary"),
        ("/dashboard/fraud-summary", "Fraud Summary"),
        ("/dashboard/spending-heatmap?days=90", "Spending Heatmap"),
    ]

    for endpoint, label in endpoints:
        r = requests.get(f"{BASE}{endpoint}")
        if r.status_code == 200:
            ok(f"{label} → 200")
        else:
            fail(label, f"status={r.status_code} body={r.text[:200]}")

    # VAT summary with date filter
    r = requests.get(f"{BASE}/dashboard/vat-summary?date_from=2020-01-01&date_to=2030-12-31")
    if r.status_code == 200:
        ok("VAT Summary with date filter → 200")
    else:
        fail("VAT Summary with date filter", f"status={r.status_code}")

    # Export CSV
    r = requests.get(f"{BASE}/dashboard/export")
    if r.status_code == 200 and "text/csv" in r.headers.get("content-type", ""):
        ok("Export CSV → 200 (text/csv)")
    else:
        fail("Export CSV", f"status={r.status_code}, content-type={r.headers.get('content-type')}")

    # Export CSV with filters
    r = requests.get(f"{BASE}/dashboard/export?date_from=2020-01-01")
    if r.status_code == 200:
        ok("Export CSV with date filter → 200")
    else:
        fail("Export CSV with date filter", f"status={r.status_code}")


# ──────────────────────────────────────────────────────────────
# 5. Concurrent Uploads
# ──────────────────────────────────────────────────────────────

def test_concurrent_uploads():
    section("7. Concurrent Uploads (5 files at once)")
    ids = []

    def do_upload(i: int):
        png = make_tiny_png()
        png_mod = png + bytes([i])  # slightly different to avoid hash collision
        r = upload_file(content=png_mod, filename=f"concurrent_{i}_{int(time.time())}.png")
        return i, r.status_code, r.json().get("id") if r.status_code == 200 else None

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(do_upload, i) for i in range(5)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    success_count = 0
    for i, status, doc_id in results:
        if status == 200 and doc_id:
            success_count += 1
            ids.append(doc_id)

    if success_count == 5:
        ok(f"All 5 concurrent uploads succeeded")
    else:
        fail(f"Concurrent uploads", f"only {success_count}/5 succeeded")

    # Cleanup
    for doc_id in ids:
        cleanup_doc(doc_id)
    ok(f"Cleaned up {len(ids)} concurrent test docs")


# ──────────────────────────────────────────────────────────────
# 6. Edge Cases
# ──────────────────────────────────────────────────────────────

def test_edge_cases():
    section("8. Edge Cases")

    # Update with zero/negative values
    r = upload_file(content=make_tiny_png(), filename=f"edge_{int(time.time())}.png")
    if r.status_code != 200:
        fail("Edge case setup", "cannot upload")
        return
    doc_id = r.json()["id"]

    r = requests.put(f"{BASE}/documents/{doc_id}", json={"grand_total": 0})
    if r.status_code == 200 and r.json()["grand_total"] == 0:
        ok("Update grand_total=0 → accepted")
    else:
        fail("Update grand_total=0", f"status={r.status_code}")

    r = requests.put(f"{BASE}/documents/{doc_id}", json={"grand_total": -100})
    if r.status_code == 200:
        ok("Update grand_total=-100 → accepted (no server-side validation)")
    else:
        fail("Update grand_total=-100", f"status={r.status_code}")

    # Update with null values
    r = requests.put(f"{BASE}/documents/{doc_id}", json={
        "merchant_name": None,
        "grand_total": None,
        "document_date": None,
    })
    if r.status_code == 200:
        d = r.json()
        if d["merchant_name"] is None and d["grand_total"] is None:
            ok("Update with null values → fields cleared")
        else:
            fail("Update with null values", f"fields not cleared: merchant={d['merchant_name']}")
    else:
        fail("Update with null values", f"status={r.status_code}")

    # Update with very long string
    long_name = "ร้าน" * 500
    r = requests.put(f"{BASE}/documents/{doc_id}", json={"merchant_name": long_name})
    if r.status_code == 200:
        ok(f"Update with long Thai string ({len(long_name)} chars) → accepted")
    else:
        fail("Update with long string", f"status={r.status_code}")

    # Update with empty string
    r = requests.put(f"{BASE}/documents/{doc_id}", json={"merchant_name": ""})
    if r.status_code == 200:
        ok("Update with empty string → accepted")
    else:
        fail("Update with empty string", f"status={r.status_code}")

    # Invalid JSON body
    r = requests.put(
        f"{BASE}/documents/{doc_id}",
        data="not json",
        headers={"Content-Type": "application/json"},
    )
    if r.status_code == 422:
        ok("Invalid JSON body → 422")
    else:
        fail("Invalid JSON body", f"expected 422, got {r.status_code}")

    # Image endpoint
    r = requests.get(f"{BASE}/documents/{doc_id}/image")
    if r.status_code == 200:
        ok("Get document image → 200")
    else:
        fail("Get document image", f"status={r.status_code}")

    # Image 404
    r = requests.get(f"{BASE}/documents/nonexistent-id/image")
    if r.status_code == 404:
        ok("Get nonexistent image → 404")
    else:
        fail("Get nonexistent image", f"expected 404, got {r.status_code}")

    cleanup_doc(doc_id)


# ──────────────────────────────────────────────────────────────
# 7. Full Pipeline Test (upload real receipt → wait → verify)
# ──────────────────────────────────────────────────────────────

def test_full_pipeline():
    section("9. Full Pipeline (upload → OCR → extract → approve)")

    test_files = sorted(DATA_DIR.glob("*"))[:2]
    if not test_files:
        print("  ⚠️  No test files in dataTest/, skipping pipeline test")
        return

    for f in test_files:
        print(f"\n  📄 Testing with {f.name}...")
        r = upload_file(str(f))
        if r.status_code == 409:
            ok(f"{f.name}: already uploaded (409), skipping")
            continue
        if r.status_code != 200:
            fail(f"{f.name}: upload", f"status={r.status_code}")
            continue
        ok(f"{f.name}: uploaded → processing")

        doc_id = r.json()["id"]
        result = wait_for_processing(doc_id, timeout=120)

        if result is None:
            fail(f"{f.name}: processing", "timed out after 120s")
            continue

        if result["status"] == "extracted":
            ok(f"{f.name}: extracted (confidence={result['confidence']})")

            if result["merchant_name"]:
                ok(f"{f.name}: merchant_name='{result['merchant_name']}'")
            else:
                print(f"  ⚠️  {f.name}: no merchant_name extracted")

            if result["items"] and len(result["items"]) > 0:
                ok(f"{f.name}: {len(result['items'])} items extracted")
            else:
                print(f"  ⚠️  {f.name}: no items extracted")

            if result["category"]:
                ok(f"{f.name}: category='{result['category']}'")

            # Approve
            r = requests.post(f"{BASE}/documents/{doc_id}/approve")
            if r.status_code == 200 and r.json()["status"] == "reviewed":
                ok(f"{f.name}: approved → reviewed")
            else:
                fail(f"{f.name}: approve", f"status={r.status_code}")

        elif result["status"] == "error":
            fail(f"{f.name}: extraction error", result.get("error_message", "unknown"))
        else:
            fail(f"{f.name}: unexpected status", result["status"])


# ──────────────────────────────────────────────────────────────
# 8. Rapid-fire requests (stability check)
# ──────────────────────────────────────────────────────────────

def test_rapid_fire():
    section("10. Rapid-fire Requests (50 GETs in parallel)")

    def do_get(i: int):
        r = requests.get(f"{BASE}/documents")
        return r.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(do_get, i) for i in range(50)]
        statuses = [f.result() for f in concurrent.futures.as_completed(futures)]

    ok_count = statuses.count(200)
    if ok_count == 50:
        ok("All 50 parallel GETs → 200")
    else:
        fail("Parallel GETs", f"only {ok_count}/50 returned 200")

    # Rapid dashboard stats
    def do_stats(i: int):
        r = requests.get(f"{BASE}/dashboard/stats")
        return r.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(do_stats, i) for i in range(20)]
        statuses = [f.result() for f in concurrent.futures.as_completed(futures)]

    ok_count = statuses.count(200)
    if ok_count == 20:
        ok("All 20 parallel dashboard/stats → 200")
    else:
        fail("Parallel dashboard/stats", f"only {ok_count}/20 returned 200")


# ──────────────────────────────────────────────────────────────
# Run All
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🧪 Thai Receipt Intelligence — API Stability Test")
    print(f"   Target: {BASE}")
    print(f"   Data:   {DATA_DIR}")

    # Check server is up
    try:
        r = requests.get(f"{BASE}/dashboard/stats", timeout=5)
        if r.status_code != 200:
            print(f"\n❌ Server returned {r.status_code}. Is it running?")
            sys.exit(1)
    except requests.ConnectionError:
        print(f"\n❌ Cannot connect to {BASE}. Run 'make dev' first.")
        sys.exit(1)

    t0 = time.time()

    test_upload_valid_formats()
    test_upload_invalid()
    test_upload_duplicate()
    test_crud()
    test_list_and_filter()
    test_dashboard()
    test_concurrent_uploads()
    test_edge_cases()
    test_rapid_fire()
    test_full_pipeline()

    elapsed = time.time() - t0

    print(f"\n{'='*60}")
    print(f"  RESULTS: {passed} passed, {failed} failed ({elapsed:.1f}s)")
    print(f"{'='*60}")

    if errors:
        print("\nFailed tests:")
        for e in errors:
            print(e)

    sys.exit(1 if failed > 0 else 0)
