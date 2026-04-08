#!/usr/bin/env python3
"""Quick script to upload test receipts and show extraction results."""

import json
import sys
import time
from pathlib import Path

import httpx

API_BASE = "http://localhost:8000/api"
DATA_DIR = Path(__file__).parent.parent / "dataTest"


def upload_file(client: httpx.Client, file_path: Path) -> dict:
    """Upload a single file and return the response."""
    with open(file_path, "rb") as f:
        resp = client.post(
            f"{API_BASE}/documents/upload",
            files={"file": (file_path.name, f)},
        )
    resp.raise_for_status()
    return resp.json()


def poll_until_done(client: httpx.Client, doc_id: str, timeout: int = 120) -> dict:
    """Poll until the document status is no longer 'processing'."""
    start = time.time()
    while time.time() - start < timeout:
        resp = client.get(f"{API_BASE}/documents/{doc_id}")
        resp.raise_for_status()
        doc = resp.json()
        if doc["status"] != "processing":
            return doc
        time.sleep(2)
    raise TimeoutError(f"Document {doc_id} still processing after {timeout}s")


def print_result(doc: dict) -> None:
    """Pretty-print the extraction result."""
    print(f"  Status:     {doc['status']}")
    print(f"  Merchant:   {doc['merchant_name'] or '-'}")
    print(f"  Doc No:     {doc['document_number'] or '-'}")
    print(f"  Date:       {doc['document_date'] or '-'}")
    print(f"  Subtotal:   {doc['subtotal']}")
    print(f"  Discount:   {doc['discount']}")
    print(f"  VAT:        {doc['vat']}")
    print(f"  Total:      {doc['grand_total']}")
    print(f"  Confidence: {doc['confidence']}")
    print(f"  Items:      {len(doc['items'])}")
    for i, item in enumerate(doc["items"], 1):
        print(f"    {i}. {item['product_name_raw']} "
              f"x{item['quantity']} {item['unit'] or ''} "
              f"@{item['unit_price']} = {item['line_total']}")
    if doc.get("ocr_text"):
        lines = doc["ocr_text"].strip().split("\n")
        print(f"  OCR Text:   ({len(lines)} lines)")
    if doc.get("notes"):
        print(f"  Notes:      {doc['notes'][:100]}")
    if doc.get("error_message"):
        print(f"  ERROR:      {doc['error_message']}")


def main():
    files = sorted(DATA_DIR.glob("*"))
    if not files:
        print(f"No files found in {DATA_DIR}")
        sys.exit(1)

    print(f"Found {len(files)} test files in {DATA_DIR}\n")

    client = httpx.Client(timeout=180)

    for file_path in files:
        print(f"{'='*60}")
        print(f"Uploading: {file_path.name} ({file_path.stat().st_size / 1024:.1f} KB)")
        print(f"{'='*60}")

        try:
            doc = upload_file(client, file_path)
            print(f"  Uploaded!  ID: {doc['id']}")
            print(f"  Waiting for processing...")

            result = poll_until_done(client, doc["id"])
            print_result(result)
        except httpx.HTTPStatusError as e:
            print(f"  HTTP Error: {e.response.status_code} — {e.response.text[:200]}")
        except Exception as e:
            print(f"  Error: {e}")

        print()

    client.close()
    print("Done!")


if __name__ == "__main__":
    main()
