"""One-shot: re-run merchant normalization for every existing document.

Use after updating the rule-based cleaner so old records (that were normalised
by an earlier version of the cleaner) are brought up to current standards.

Run with::

    cd backend && .venv/bin/python scripts/clean_merchant_normalized.py

Prints a summary of what changed.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a script: add the backend root to sys.path so `app` imports work.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import Document  # noqa: E402
from app.services.merchants import _rule_based_clean  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        docs = db.query(Document).all()
        changes: list[tuple[str, str, str]] = []
        for doc in docs:
            if not doc.merchant_name and not doc.merchant_normalized:
                continue
            # Prefer the raw name — it's the most reliable source of truth.
            new_value = _rule_based_clean(doc.merchant_name or "") or None
            if new_value != doc.merchant_normalized:
                changes.append(
                    (doc.id, doc.merchant_normalized or "", new_value or "")
                )
                doc.merchant_normalized = new_value

        db.commit()

        print(f"Scanned {len(docs)} documents, {len(changes)} updated:\n")
        for doc_id, before, after in changes:
            print(f"  [{doc_id[:8]}] {before!r}")
            print(f"              → {after!r}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
