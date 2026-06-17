"""Pre-create the 5 demo stores so uploaded receipts auto-file into visits
instead of landing in the unknown-store bucket.

Run:
    cd backend && .venv/bin/python -m app.scripts.seed_demo_stores

Idempotent: skips a store whose normalized_name already exists. The
``normalized_name`` is what ``find_matching_store`` matches against (after
``_rule_based_clean``), so it must equal the cleaned merchant the AI reads —
e.g. "ร้านสุดาพาณิชย์" / "บริษัท … จำกัด" both clean to the values below.
"""

from __future__ import annotations

import logging

from ..database import SessionLocal
from ..models import Store

logger = logging.getLogger(__name__)

# (code, display name, normalized_name, address)
DEMO_STORES = [
    ("DEMO-S1", "ร้านสุดาพาณิชย์", "สุดาพาณิชย์",
     "123/4 หมู่ 5 ต.บางแก้ว อ.เมือง จ.สมุทรปราการ"),
    ("DEMO-S2", "บริษัท ก.เจริญพาณิชย์ จำกัด", "ก.เจริญพาณิชย์",
     "88 ถ.เพชรเกษม จ.ราชบุรี"),
    ("DEMO-S3", "หจก. รวยทรัพย์เจริญ", "รวยทรัพย์เจริญ",
     "99 ถ.มิตรภาพ จ.ขอนแก่น"),
    ("DEMO-S4", "ร้านป้าแดง มินิมาร์ท", "ป้าแดง มินิมาร์ท",
     "สาขาบางนา กรุงเทพฯ"),
    ("DEMO-S5", "โชห่วยลุงสมชาย", "โชห่วยลุงสมชาย", None),
]


def seed_demo_stores() -> dict[str, int]:
    db = SessionLocal()
    created = skipped = 0
    try:
        for code, name, normalized, address in DEMO_STORES:
            existing = (
                db.query(Store)
                .filter(Store.normalized_name == normalized)
                .first()
            )
            if existing:
                skipped += 1
                logger.info("Store %r already exists — skipping", normalized)
                continue
            db.add(
                Store(
                    code=code,
                    name=name,
                    normalized_name=normalized,
                    address=address,
                    active=True,
                )
            )
            created += 1
            logger.info("Created store %r (%s)", name, code)
        db.commit()
    finally:
        db.close()
    return {"created": created, "skipped": skipped}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = seed_demo_stores()
    logger.info("Done — created=%d, skipped=%d", result["created"], result["skipped"])
