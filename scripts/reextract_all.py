"""Re-extract every document and print a demo-readiness summary.

Usage: python scripts/reextract_all.py [--api BASE_URL]

The script:
  1. Lists all documents.
  2. Triggers /reextract on each.
  3. Polls until all reach a terminal state (extracted | error).
  4. Prints a summary table: merchant / category / items / confidence / notes (truncated).
  5. Flags documents that need manual review (low confidence, non-Thai notes, missing
     normalized merchant, items without category, validation warnings).
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass

import urllib.request
import urllib.error
import json


def _http(method: str, url: str, timeout: int = 60) -> dict | list:
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_docs(base: str) -> list[dict]:
    return _http("GET", f"{base}/documents?limit=500")


def get_doc(base: str, doc_id: str) -> dict:
    return _http("GET", f"{base}/documents/{doc_id}")


def reextract(base: str, doc_id: str) -> dict:
    return _http("POST", f"{base}/documents/{doc_id}/reextract")


# Rough heuristic: notes should be mostly Thai. Allow numbers/punctuation/shop names in English,
# but flag if there's a contiguous English sentence fragment of > 25 chars.
_ENGLISH_SENTENCE_RE = re.compile(r"[A-Za-z][A-Za-z' ,./()0-9-]{24,}")


def flag_english_notes(notes: str | None) -> str | None:
    if not notes:
        return None
    match = _ENGLISH_SENTENCE_RE.search(notes)
    if match:
        return match.group(0)[:80]
    return None


@dataclass
class Row:
    idx: int
    doc_id: str
    filename: str
    merchant: str
    merchant_normalized: str
    category: str
    confidence: float
    item_count: int
    items_with_category: int
    notes_preview: str
    english_fragment: str | None
    status: str


def summarize(doc: dict, idx: int) -> Row:
    notes = (doc.get("notes") or "").strip()
    return Row(
        idx=idx,
        doc_id=doc["id"],
        filename=doc.get("filename", ""),
        merchant=doc.get("merchant_name") or "-",
        merchant_normalized=doc.get("merchant_normalized") or "-",
        category=doc.get("category") or "-",
        confidence=doc.get("confidence") or 0.0,
        item_count=len(doc.get("items") or []),
        items_with_category=sum(
            1 for it in doc.get("items") or [] if it.get("category")
        ),
        notes_preview=notes.replace("\n", " | ")[:90],
        english_fragment=flag_english_notes(notes),
        status=doc.get("status") or "?",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000/api")
    ap.add_argument("--poll", type=int, default=5, help="seconds between polls")
    ap.add_argument(
        "--timeout",
        type=int,
        default=60 * 40,
        help="max total wait time (seconds)",
    )
    args = ap.parse_args()

    docs = list_docs(args.api)
    print(f"Found {len(docs)} documents — triggering re-extract…\n")

    triggered: list[str] = []
    for d in docs:
        try:
            reextract(args.api, d["id"])
            triggered.append(d["id"])
        except urllib.error.HTTPError as exc:
            print(f"  ! failed to queue {d['id']}: {exc}")

    print(f"Queued {len(triggered)} re-extracts. Polling every {args.poll}s…\n")

    start = time.time()
    done: dict[str, dict] = {}
    while len(done) < len(triggered) and time.time() - start < args.timeout:
        remaining = [d for d in triggered if d not in done]
        for doc_id in remaining:
            try:
                current = get_doc(args.api, doc_id)
            except Exception:
                continue
            if current.get("status") in ("extracted", "error", "reviewed"):
                done[doc_id] = current

        elapsed = int(time.time() - start)
        print(
            f"  [{elapsed:>4}s] {len(done)}/{len(triggered)} done "
            f"({len(triggered) - len(done)} remaining)"
        )
        if len(done) < len(triggered):
            time.sleep(args.poll)

    print()
    print("=" * 110)
    print("SUMMARY")
    print("=" * 110)

    rows = [summarize(d, i + 1) for i, d in enumerate(done.values())]
    rows.sort(key=lambda r: r.confidence)

    header = f"{'#':>3} {'CONF':>5}  {'STATUS':<10} {'CAT':<22} {'ITEMS':>5} {'MERCHANT':<38}  NOTES"
    print(header)
    print("-" * 110)
    for r in rows:
        conf_pct = f"{int(r.confidence * 100)}%"
        items_marker = f"{r.items_with_category}/{r.item_count}"
        print(
            f"{r.idx:>3} {conf_pct:>5}  {r.status:<10} {r.category[:22]:<22} "
            f"{items_marker:>5} {r.merchant[:38]:<38}  {r.notes_preview}"
        )

    print()
    print("=" * 110)
    print("FLAGS — documents that need manual review")
    print("=" * 110)

    low_conf = [r for r in rows if r.confidence < 0.8]
    english_notes = [r for r in rows if r.english_fragment]
    no_normalized = [r for r in rows if r.merchant_normalized == "-" and r.merchant != "-"]
    incomplete_cat = [r for r in rows if r.item_count > 0 and r.items_with_category < r.item_count]
    errored = [r for r in rows if r.status == "error"]

    def print_group(title: str, group: list[Row], formatter=lambda r: ""):
        print(f"\n{title}: {len(group)}")
        for r in group:
            extra = formatter(r)
            print(f"  - [{r.doc_id[:8]}] {r.merchant[:40]}  {extra}")

    print_group("❗ Errored", errored, lambda r: "")
    print_group("⚠️ Low confidence (<80%)", low_conf, lambda r: f"conf={int(r.confidence*100)}%")
    print_group(
        "🔤 Notes contain English fragment",
        english_notes,
        lambda r: f"'{r.english_fragment}'",
    )
    print_group("🏷️ Missing merchant_normalized", no_normalized)
    print_group("📦 Items without category", incomplete_cat, lambda r: f"{r.items_with_category}/{r.item_count}")

    print()
    print("=" * 110)
    total = len(rows)
    print(
        f"DONE: {total}/{len(triggered)} processed, "
        f"{len(errored)} errored, "
        f"avg conf = {sum(r.confidence for r in rows) / max(total, 1):.1%}"
    )
    return 0 if not errored else 1


if __name__ == "__main__":
    sys.exit(main())
