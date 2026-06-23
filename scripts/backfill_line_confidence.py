"""Recompute verifiable per-line confidence for existing document_items.

Same logic as the upload path (services/line_confidence) — run once after
deploying the feature so historical rows get a real per-line confidence +
needs_review flag instead of the old doc-level copy.

    cd backend && .venv/bin/python ../scripts/backfill_line_confidence.py
    cd backend && .venv/bin/python ../scripts/backfill_line_confidence.py --apply
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.models import DocumentItem  # noqa: E402
from app.services.line_confidence import build_known_forms, score_line  # noqa: E402


def main() -> None:
    apply = "--apply" in sys.argv
    db = SessionLocal()
    known = build_known_forms(db)
    items = db.query(DocumentItem).all()
    flagged = 0
    changed = 0
    for it in items:
        s = score_line(it.product_name_raw, it.product_code, known)
        if it.confidence != s.confidence or bool(it.needs_review) != s.needs_review:
            changed += 1
        if s.needs_review:
            flagged += 1
        if apply:
            it.confidence = s.confidence
            it.needs_review = s.needs_review
    if apply:
        db.commit()
    print(f"{len(items)} items | would change {changed} | flagged {flagged} "
          f"({flagged/len(items)*100:.0f}%) | {'APPLIED' if apply else 'dry-run'}")
    db.close()


if __name__ == "__main__":
    main()
