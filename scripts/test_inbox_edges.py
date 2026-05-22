#!/usr/bin/env python3
"""Edge-case smoke tests for the Drop & Review inbox flow.

Run AFTER ``test_inbox.py`` has populated the DB. Exercises:

1. Naming an orphan → it gets attached to a (new) Visit.
2. Editing a doc's merchant → it jumps to a different Visit.
3. Editing a doc's document_date → it jumps to a different month's Visit.
4. Marking a Visit reviewed → ``last_reviewed_at`` is stamped.
5. Re-uploading a known file → duplicate is reported (not re-processed).
6. Non-receipt purge endpoint runs without error.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

API_BASE = "http://localhost:8000/api"
DEMO = Path(__file__).parent.parent / "dataTest" / "demo"

OK = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"


def check(label: str, cond: bool, extra: str = ""):
    print(f"  {OK if cond else FAIL} {label}{(' — ' + extra) if extra and not cond else ''}")
    return cond


def main():
    with httpx.Client(timeout=30) as c:
        d = c.get(f"{API_BASE}/inbox/dashboard").json()

        # 1. Orphan naming
        print("1. Orphan naming")
        if d["orphans"]:
            orphan = d["orphans"][0]
            r = c.post(
                f"{API_BASE}/inbox/documents/{orphan['id']}/name",
                json={"merchant_name": "ร้านทดสอบ Orphan"},
            )
            check("name endpoint returns 200", r.status_code == 200, f"got {r.status_code}")
            after = c.get(f"{API_BASE}/documents/{orphan['id']}").json()
            check("doc now has visit_id", after["visit_id"] is not None)
            check(
                "doc merchant_name set",
                after["merchant_name"] == "ร้านทดสอบ Orphan",
                str(after["merchant_name"]),
            )
        else:
            print("  (no orphans to test)")

        # 2. Edit merchant → visit reassign
        print()
        print("2. Edit merchant → visit reassign")
        d = c.get(f"{API_BASE}/inbox/dashboard").json()
        # Pick any visit's first doc
        visit_with_docs = next((v for v in d["visits"] if v["document_count"] >= 1), None)
        if visit_with_docs:
            visit_detail = c.get(f"{API_BASE}/visits/{visit_with_docs['id']}").json()
            doc = visit_detail["documents"][0]
            old_visit_id = doc["visit_id"]
            r = c.put(
                f"{API_BASE}/documents/{doc['id']}",
                json={"merchant_name": "ร้านใหม่เปลี่ยนไป", "merchant_normalized": "ร้านใหม่เปลี่ยนไป"},
            )
            check("PUT returns 200", r.status_code == 200, f"got {r.status_code}")
            updated = r.json()
            check(
                "visit_id changed",
                updated["visit_id"] != old_visit_id,
                f"was {old_visit_id} now {updated['visit_id']}",
            )
            new_visit = c.get(f"{API_BASE}/visits/{updated['visit_id']}").json()
            check(
                "new visit store_key normalized correctly",
                new_visit["store_key"] == "ร้านใหม่เปลี่ยนไป",
                str(new_visit["store_key"]),
            )

        # 3. Edit document_date → cross-month reassign
        print()
        print("3. Edit document_date → cross-month reassign")
        d = c.get(f"{API_BASE}/inbox/dashboard?month=2025-12").json()
        v_dec = next((v for v in d["visits"] if v["document_count"] >= 1), None)
        if v_dec:
            detail = c.get(f"{API_BASE}/visits/{v_dec['id']}").json()
            doc = detail["documents"][0]
            old_visit_id = doc["visit_id"]
            r = c.put(f"{API_BASE}/documents/{doc['id']}", json={"document_date": "2024-06-15"})
            check("PUT returns 200", r.status_code == 200, f"got {r.status_code}")
            updated = r.json()
            check(
                "moved to different visit",
                updated["visit_id"] != old_visit_id,
                f"was {old_visit_id} now {updated['visit_id']}",
            )
            new_visit = c.get(f"{API_BASE}/visits/{updated['visit_id']}").json()
            check(
                "new visit report_period = 2024-06",
                new_visit["report_period"] == "2024-06",
                str(new_visit["report_period"]),
            )

        # 4. Mark visit reviewed
        print()
        print("4. Mark visit reviewed")
        d = c.get(f"{API_BASE}/inbox/dashboard").json()
        if d["visits"]:
            target_vid = d["visits"][0]["id"]
            r = c.post(f"{API_BASE}/inbox/visits/{target_vid}/mark-reviewed")
            check("mark-reviewed returns 200", r.status_code == 200)
            check("last_reviewed_at stamped", bool(r.json().get("last_reviewed_at")))

        # 5. Duplicate upload guard
        print()
        print("5. Duplicate upload rejected")
        files_to_send = [(p.name, p.read_bytes(), "image/jpeg") for p in [next(DEMO.glob("18_same_merchant_a.jpeg"))]]
        r = c.post(
            f"{API_BASE}/inbox",
            files=[("files", f) for f in files_to_send],
        )
        body = r.json()
        check("duplicate detected", len(body["duplicates"]) == 1 and len(body["document_ids"]) == 0)

        # 6. Non-receipt purge runs
        print()
        print("6. Non-receipt purge")
        r = c.post(f"{API_BASE}/inbox/non-receipts/purge")
        check("purge returns 200", r.status_code == 200)
        check("response has purged count", "purged" in r.json())

        print()
        print("Done.")


if __name__ == "__main__":
    main()
