"""Export / import the Store master as JSON.

A fresh deployment auto-seeds the product catalog but not the stores — those
are admin-created data. Without them every uploaded receipt lands in the
Unknown-store pile and nobody can see a visit form, which makes a new box look
broken rather than empty. This carries the store list across.

    # on the machine that has the stores
    cd backend && .venv/bin/python scripts/stores_seed.py export

    # on the target (respects DATABASE_URL; skips names already present)
    cd backend && .venv/bin/python scripts/stores_seed.py import

    # into a container (copy the JSON in first, the image has no deploy/ dir)
    docker compose cp deploy/seed/stores.json backend:/app/stores.json
    docker compose exec -T backend python scripts/stores_seed.py import \
        --file /app/stores.json
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Lives in backend/scripts so it ships inside the image: the target of an
# import is usually a running container.
BACKEND = Path(__file__).resolve().parent.parent
SEED = BACKEND.parent / "deploy" / "seed" / "stores.json"
sys.path.insert(0, str(BACKEND))

from app.database import SessionLocal  # noqa: E402
from app.models import Store  # noqa: E402

FIELDS = ("code", "name", "normalized_name", "address", "notes")


def export(path: Path, include_inactive: bool) -> None:
    db = SessionLocal()
    try:
        q = db.query(Store)
        if not include_inactive:
            q = q.filter(Store.active.is_(True))
        rows = [{f: getattr(s, f) for f in FIELDS} for s in q.order_by(Store.name)]
    finally:
        db.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"stores": rows}, ensure_ascii=False, indent=2))
    print(f"exported {len(rows)} stores -> {path}")


def load(path: Path) -> None:
    rows = json.loads(path.read_text())["stores"]
    db = SessionLocal()
    added = skipped = 0
    try:
        for row in rows:
            # Match on name: ids differ per database, and codes are optional.
            if db.query(Store).filter(Store.name == row["name"]).first():
                skipped += 1
                continue
            now = datetime.now()
            db.add(Store(id=str(uuid.uuid4()), active=True, created_at=now,
                         updated_at=now, **row))
            added += 1
        db.commit()
    finally:
        db.close()
    print(f"imported {added} stores, skipped {skipped} already present")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["export", "import"])
    ap.add_argument("--file", default=str(SEED))
    ap.add_argument("--include-inactive", action="store_true",
                    help="export only: carry deactivated stores across too")
    args = ap.parse_args()
    path = Path(args.file)
    if args.action == "export":
        export(path, args.include_inactive)
    else:
        load(path)


if __name__ == "__main__":
    main()
