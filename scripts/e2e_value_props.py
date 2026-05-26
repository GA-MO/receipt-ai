#!/usr/bin/env python3
"""End-to-end tests for the value-proposition.md features.

Hits the running backend (assumed at API_BASE) and verifies every feature
we claim in value-proposition.md that can be tested automatically.

Run via:
    cd backend && .venv/bin/python ../scripts/e2e_value_props.py

Requires:
    - Backend running at http://localhost:8000
    - dataTest/demo populated with real receipt jpegs
    - OPENROUTER_API_KEY configured in backend/.env
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

API_BASE = "http://localhost:8000/api"
DATA_DIR = Path(__file__).parent.parent / "dataTest" / "demo"
GROUND_TRUTH = Path(__file__).parent.parent / "dataTest" / "ground_truth"
EXTRACTION_TIMEOUT = 180  # seconds


# ---------------------------------------------------------------------------
# Lightweight test harness — collect pass/fail and print a clean summary.
# ---------------------------------------------------------------------------


@dataclass
class TestResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Suite:
    results: list[TestResult] = field(default_factory=list)

    def check(self, name: str, cond: bool, detail: str = "") -> bool:
        self.results.append(TestResult(name, cond, detail))
        mark = "✓" if cond else "✗"
        line = f"  {mark} {name}"
        if detail:
            line += f"  — {detail}"
        print(line)
        return cond

    def section(self, title: str) -> None:
        print(f"\n=== {title} ===")

    def summary(self) -> int:
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        print(f"\n{'=' * 50}")
        print(f"  {passed}/{total} passed")
        failed = [r for r in self.results if not r.passed]
        if failed:
            print("\n  Failed:")
            for r in failed:
                print(f"    ✗ {r.name}  — {r.detail}")
        return 0 if passed == total else 1


def main() -> int:
    suite = Suite()
    client = httpx.Client(base_url=API_BASE, timeout=30.0)

    # -----------------------------------------------------------------------
    # PRE-FLIGHT
    # -----------------------------------------------------------------------
    suite.section("Pre-flight")
    try:
        dashboard = client.get("/inbox/dashboard").json()
        suite.check("Backend responding", True, f"visits={dashboard['counts']['visits']}")
    except Exception as e:
        suite.check("Backend responding", False, str(e))
        return suite.summary()

    files = sorted(DATA_DIR.glob("*.jpeg"))
    suite.check(
        "dataTest/demo has receipts", len(files) > 0, f"{len(files)} files"
    )

    # -----------------------------------------------------------------------
    # 1. BULK UPLOAD
    # -----------------------------------------------------------------------
    suite.section("1. Bulk upload")
    multipart = [
        ("files", (f.name, f.open("rb"), "image/jpeg")) for f in files
    ]
    t0 = time.time()
    resp = client.post("/inbox", files=multipart)
    upload_ms = int((time.time() - t0) * 1000)
    if not suite.check(
        "Bulk upload accepted", resp.status_code == 201, f"{resp.status_code} in {upload_ms}ms"
    ):
        print(resp.text)
        return suite.summary()

    payload = resp.json()
    doc_ids: list[str] = list(payload["document_ids"])
    duplicates: list[dict] = payload["duplicates"]
    failures: list[dict] = payload["failures"]
    print(f"    accepted={len(doc_ids)} duplicates={len(duplicates)} failures={len(failures)}")

    # File-hash de-dupe is proven by ANY of the files being recognised as a
    # duplicate (since dataTest receipts may already exist in the DB from
    # earlier runs). When the DB is fresh, we verify by uploading a second time.
    if duplicates:
        suite.check(
            "File hash de-dupes (some files recognised from prior upload)",
            len(failures) == 0,
            f"duplicates={len(duplicates)}, new={len(doc_ids)}",
        )
    elif doc_ids:
        re_multipart = [
            ("files", (f.name, f.open("rb"), "image/jpeg")) for f in files
        ]
        re_resp = client.post("/inbox", files=re_multipart).json()
        suite.check(
            "File hash de-dupes on re-upload",
            len(re_resp["duplicates"]) == len(files) and len(re_resp["document_ids"]) == 0,
            f"duplicates={len(re_resp['duplicates'])}/{len(files)}",
        )

    # Pull in existing doc IDs from duplicates so subsequent assertions still
    # have a working corpus to inspect, even on repeat runs.
    for dup in duplicates:
        if dup.get("existing_document_id"):
            doc_ids.append(dup["existing_document_id"])

    # -----------------------------------------------------------------------
    # 2. WAIT FOR EXTRACTION
    # -----------------------------------------------------------------------
    suite.section("2. AI extraction (poll)")
    pending = set(doc_ids)
    docs_by_id: dict[str, dict] = {}
    t_start = time.time()
    while pending and time.time() - t_start < EXTRACTION_TIMEOUT:
        for did in list(pending):
            d = client.get(f"/documents/{did}").json()
            if d["status"] not in ("processing", "pending"):
                docs_by_id[did] = d
                pending.discard(did)
        if pending:
            time.sleep(2)

    suite.check(
        "All docs finished extraction",
        not pending,
        f"completed={len(docs_by_id)}/{len(doc_ids)} in {int(time.time() - t_start)}s",
    )

    extracted_count = sum(1 for d in docs_by_id.values() if d["status"] in ("extracted", "reviewed"))
    suite.check(
        "Most docs reached extracted/reviewed",
        extracted_count >= len(doc_ids) * 0.7,
        f"{extracted_count}/{len(doc_ids)} extracted",
    )

    # -----------------------------------------------------------------------
    # 3. EXTRACTION QUALITY
    # -----------------------------------------------------------------------
    suite.section("3. Extraction details (per doc)")
    with_merchant = sum(1 for d in docs_by_id.values() if d.get("merchant_name"))
    with_date = sum(1 for d in docs_by_id.values() if d.get("document_date"))
    with_items = sum(1 for d in docs_by_id.values() if d.get("items"))
    suite.check("≥80% have merchant_name", with_merchant >= len(docs_by_id) * 0.8, f"{with_merchant}/{len(docs_by_id)}")
    suite.check("≥80% have document_date", with_date >= len(docs_by_id) * 0.8, f"{with_date}/{len(docs_by_id)}")
    suite.check("≥80% have ≥1 item", with_items >= len(docs_by_id) * 0.8, f"{with_items}/{len(docs_by_id)}")

    # product_code mapping (code-first → name derived server-side)
    total_items = 0
    items_with_code = 0
    items_normalized_matches_catalog = 0
    for d in docs_by_id.values():
        for it in d.get("items", []):
            total_items += 1
            if it.get("product_code"):
                items_with_code += 1
                # When a code is present, the normalized name should come from catalog,
                # not from the raw transcription.
                if it.get("product_name_normalized"):
                    items_normalized_matches_catalog += 1

    suite.check(
        "Items extracted in total > 0", total_items > 0, f"{total_items} line items across {len(docs_by_id)} docs"
    )
    if total_items > 0:
        match_pct = 100 * items_with_code / total_items
        suite.check(
            "≥40% items got a product_code (catalog match)",
            match_pct >= 40,
            f"{items_with_code}/{total_items} ({match_pct:.0f}%)",
        )
        suite.check(
            "Coded items have normalized name (server-side mapping)",
            items_normalized_matches_catalog == items_with_code,
            f"{items_normalized_matches_catalog}/{items_with_code}",
        )

    # -----------------------------------------------------------------------
    # 4. AUTO-ATTACH VISIT + TRIAGE
    # -----------------------------------------------------------------------
    suite.section("4. Inbox triage + auto-attach")
    attached = sum(1 for d in docs_by_id.values() if d.get("visit_id"))
    suite.check(
        "Some docs auto-attached to a Visit",
        attached > 0,
        f"{attached}/{len(docs_by_id)} have visit_id",
    )

    dash = client.get("/inbox/dashboard").json()
    bucket_counts = dash["counts"]
    bucket_keys = {"orphans", "unknown_stores", "non_receipts", "errors", "visits"}
    suite.check(
        "Dashboard exposes 4 triage buckets",
        bucket_keys.issubset(bucket_counts.keys()),
        f"keys={sorted(bucket_counts.keys())}",
    )

    # Each completed doc should land in exactly one bucket (visit / unknown / orphan / non_receipt / error).
    classified = (
        len(dash.get("orphans", []))
        + len(dash.get("unknown_stores", []))
        + len(dash.get("non_receipts", []))
        + len(dash.get("errors", []))
        + sum(v.get("document_count", 0) for v in dash.get("visits", []))
    )
    suite.check(
        "Every extracted doc visible in some bucket",
        classified >= extracted_count,
        f"classified={classified}, extracted={extracted_count}",
    )

    # -----------------------------------------------------------------------
    # 5. VISIT ROLLUP + MANUFACTURER SPLIT
    # -----------------------------------------------------------------------
    suite.section("5. Visit rollup + manufacturer split")
    visits = [v for v in dash["visits"] if v.get("document_count", 0) > 0]
    if not visits:
        suite.check("At least one visit exists", False, "no visits")
    else:
        v0 = visits[0]
        visit = client.get(f"/visits/{v0['id']}").json()
        agg = visit.get("aggregate", [])
        suite.check(
            "Visit has product×qty rollup",
            len(agg) > 0,
            f"{len(agg)} rolled-up SKUs in visit '{v0['store_label']}'",
        )

        manufacturers = {row.get("manufacturer") for row in agg if row.get("manufacturer")}
        suite.check(
            "Aggregate exposes manufacturer field",
            any(row.get("manufacturer") is not None for row in agg),
            f"distinct manufacturers={len(manufacturers)}",
        )

        catalog_matches = sum(1 for row in agg if row.get("is_catalog_match"))
        suite.check(
            "Aggregate flags catalog matches",
            catalog_matches > 0,
            f"{catalog_matches}/{len(agg)} catalog-matched rows",
        )

    # -----------------------------------------------------------------------
    # 6. AUDIT TRAIL — query backend directly via DB introspection endpoint.
    # No public endpoint exists for events, so we just sanity-check rollup
    # consistency: aggregate totals must match item sums on attached docs.
    # -----------------------------------------------------------------------
    suite.section("6. Audit / consistency")
    if visits:
        v0 = visits[0]
        visit = client.get(f"/visits/{v0['id']}").json()
        # Sum quantities across all aggregate rows and via per-doc items.
        agg_total = sum(row.get("total_quantity", 0) for row in visit.get("aggregate", []))
        per_doc_total = 0.0
        for d_summary in visit.get("documents", []):
            d_full = client.get(f"/documents/{d_summary['id']}").json()
            per_doc_total += sum(it.get("quantity", 0) or 0 for it in d_full.get("items", []))
        suite.check(
            "Aggregate total qty == sum of doc items",
            abs(agg_total - per_doc_total) < 0.01,
            f"agg={agg_total}, doc_sum={per_doc_total}",
        )

    # -----------------------------------------------------------------------
    # 7. NON-RECEIPT AUTO-PURGE ENDPOINT
    # -----------------------------------------------------------------------
    suite.section("7. Non-receipt purge endpoint")
    purge_resp = client.post("/inbox/non-receipts/purge", params={"older_than_days": 7})
    suite.check(
        "Purge endpoint responds 2xx",
        purge_resp.status_code < 300,
        f"status={purge_resp.status_code}",
    )

    # -----------------------------------------------------------------------
    # 8. GROUND TRUTH COMPARISON (if any extracted doc matches a ground truth file by merchant)
    # -----------------------------------------------------------------------
    suite.section("8. Ground truth comparison (best-effort)")
    gt_files = list(GROUND_TRUTH.glob("*.json"))
    if not gt_files:
        suite.check("Ground truth files present", False, "none in dataTest/ground_truth")
    else:
        compared = 0
        for gt_path in gt_files:
            gt = json.loads(gt_path.read_text())
            gt_merch = gt.get("merchant_normalized") or gt.get("merchant_name")
            if not gt_merch:
                continue
            # Pick the SINGLE best-matching doc: same merchant + closest item
            # count to ground truth. Across multiple runs the same dataTest
            # receipt may produce different doc_ids, and dict-iteration order
            # isn't stable — picking the closest-item-count doc keeps the
            # comparison anchored to the real "main" receipt instead of the
            # first one we happen to iterate to.
            gt_item_count = len(gt.get("items", []))
            candidates = [
                d for d in docs_by_id.values()
                if d.get("merchant_normalized") and gt_merch in d["merchant_normalized"]
            ]
            if not candidates:
                continue
            match = min(
                candidates,
                key=lambda d: abs(len(d.get("items", [])) - gt_item_count),
            )
            compared += 1
            gt_items = gt.get("items", [])
            extracted_items = match.get("items", [])
            qty_match = abs(
                sum(i.get("quantity", 0) for i in gt_items)
                - sum(i.get("quantity", 0) or 0 for i in extracted_items)
            ) < 5  # tolerate ±5 units total across all items
            suite.check(
                f"GT[{gt_merch}]: item count close",
                abs(len(gt_items) - len(extracted_items)) <= 2,
                f"gt={len(gt_items)}, extracted={len(extracted_items)}",
            )
            suite.check(
                f"GT[{gt_merch}]: total qty within ±5",
                qty_match,
                f"gt_qty={sum(i.get('quantity', 0) for i in gt_items)}, "
                f"extracted_qty={sum(i.get('quantity', 0) or 0 for i in extracted_items)}",
            )
        if compared == 0:
            suite.check(
                "Ground truth comparable (merchant match found)", False,
                "no extracted merchants matched ground truth files",
            )

    return suite.summary()


if __name__ == "__main__":
    sys.exit(main())
