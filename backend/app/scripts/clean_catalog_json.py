"""Rewrite the bundled singhaonline.com dump with pack variants removed.

The raw API dump contains the same SKU at multiple pack quantities (×1, ×6,
×10, …). For receipt matching we only want the base SKU per family. This
script uses the same detection logic as ``prune_pack_variants`` but mutates
the JSON file directly so:

* Fresh installs seed only base SKUs (no auto-prune runtime dependency).
* Re-scraping from Singha writes a new raw file; running this script again
  makes it match the pruned contract.

Usage:
    cd backend && .venv/bin/python -m app.scripts.clean_catalog_json            # preview
    cd backend && .venv/bin/python -m app.scripts.clean_catalog_json --apply    # rewrite in place
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from pathlib import Path

from .prune_pack_variants import is_multi_pack, pack_quantity

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path(__file__).parent / "singha_catalog.json"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=str(_DEFAULT_PATH))
    parser.add_argument("--apply", action="store_true", help="Overwrite the file (default: dry-run)")
    parser.add_argument("--no-backup", action="store_true", help="Skip writing a .bak next to the original")
    args = parser.parse_args()

    path = Path(args.file)
    data = json.loads(path.read_text(encoding="utf-8"))
    products = data.get("result", {}).get("products", [])

    keep: list[dict] = []
    drop: list[dict] = []
    for p in products:
        name = (p.get("nameTH") or "").strip()
        if name and is_multi_pack(name):
            drop.append(p)
        else:
            keep.append(p)

    logger.info("Original: %d products", len(products))
    logger.info("Keep    : %d (base SKUs)", len(keep))
    logger.info("Drop    : %d (multi-pack variants)", len(drop))

    if drop:
        for p in drop[:10]:
            name = p.get("nameTH") or ""
            logger.info("  drop: [qty=%d] %s", pack_quantity(name), name)
        if len(drop) > 10:
            logger.info("  ... and %d more", len(drop) - 10)

    if not args.apply:
        logger.info("Dry run — pass --apply to rewrite %s", path)
        return

    if not args.no_backup:
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copyfile(path, backup)
        logger.info("Backup written to %s", backup)

    data["result"]["products"] = keep
    data["result"]["totalResult"] = len(keep)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Rewrote %s (%d products)", path, len(keep))


if __name__ == "__main__":
    main()
