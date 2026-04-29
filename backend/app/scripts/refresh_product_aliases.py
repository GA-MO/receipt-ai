"""Refresh ``products.aliases`` from real extraction history + user corrections.

Two data sources are merged into each product's ``aliases`` JSON column:

1. ``document_items`` — for every line item that resolved to a SKU code, group
   by ``(product_code, normalized(product_name_raw))``. A raw form is promoted
   to an alias when:

     * It appeared at least ``--min-hits`` times overall (default 3), and
     * That SKU accounts for at least ``--min-dominance`` of the hits for that
       raw form (default 0.7) — guards against ambiguous strings like
       ``"เบียร์"`` mapping to several SKUs.

   This is the self-improving loop: more documents → richer aliases.

2. ``product_aliases`` — user-confirmed corrections with ``hit_count`` at or
   above ``--min-user-hits`` (default 2). Their ``canonical_name`` is resolved
   back to a SKU code via :func:`catalog.find_code_by_name`. The ``source_text``
   must also have ``token_set_ratio`` ≥ ``--min-fuzzy`` (default 50) against
   the SKU's canonical / display name — this filters per-document overrides
   like "เหงือกฟิลเลอร์รูป (กอล์ฟ)" → "วิสกี้..." that are valid for one
   receipt but should not generalise.

Identity, casing-only duplicates, and matches against ``canonical_name`` /
``display_name`` are skipped. Existing aliases are preserved; this script
only appends — it never removes.

Idempotent: running twice is a no-op once the data is already present.

Usage::

    .venv/bin/python -m app.scripts.refresh_product_aliases             # dry-run
    .venv/bin/python -m app.scripts.refresh_product_aliases --apply     # write
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter, defaultdict

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import DocumentItem, Product, ProductAlias
from ..services import catalog

logger = logging.getLogger(__name__)


def _norm(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.strip().split()).lower()


def mine_from_extractions(
    db: Session,
    *,
    min_hits: int,
    min_dominance: float,
) -> dict[str, list[str]]:
    """Return ``{product_code: [proposed aliases]}`` mined from line items."""
    rows = (
        db.query(DocumentItem.product_code, DocumentItem.product_name_raw)
        .filter(DocumentItem.product_code.isnot(None))
        .filter(DocumentItem.product_name_raw.isnot(None))
        .all()
    )

    # (code, normalized_key) → Counter of original-cased raw forms with that key.
    pair_to_raw: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for code, raw in rows:
        key = _norm(raw)
        if not key or len(key) < 2:
            continue
        pair_to_raw[(code, key)][raw.strip()] += 1

    # For each key, sum hits across all SKUs to compute dominance.
    by_key: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for (code, key), counter in pair_to_raw.items():
        by_key[key].append((code, sum(counter.values())))

    proposals: dict[str, list[str]] = defaultdict(list)
    for key, code_counts in by_key.items():
        total = sum(c for _, c in code_counts)
        code_counts.sort(key=lambda x: -x[1])
        top_code, top_count = code_counts[0]
        if top_count < min_hits:
            continue
        if top_count / total < min_dominance:
            continue
        # Use the most common original-cased raw form for the dominant code.
        most_common_raw, _ = pair_to_raw[(top_code, key)].most_common(1)[0]
        proposals[top_code].append(most_common_raw)

    return proposals


def mine_from_user_aliases(
    db: Session,
    *,
    min_user_hits: int,
    min_fuzzy: int,
) -> tuple[dict[str, list[str]], list[tuple[str, str, int]]]:
    """Return ``{product_code: [source_texts]}`` from user-confirmed aliases.

    Only rows with ``hit_count >= min_user_hits`` are considered, and the
    canonical name is resolved back to a SKU via fuzzy match. ``source_text``
    is also required to have ``token_set_ratio >= min_fuzzy`` against the
    resolved SKU's canonical/display name; rejected rows are returned as
    ``(source_text, sku_label, score)`` so the user can audit them.
    """
    from rapidfuzz import fuzz

    aliases = (
        db.query(ProductAlias)
        .filter(ProductAlias.hit_count >= min_user_hits)
        .all()
    )
    out: dict[str, list[str]] = defaultdict(list)
    rejected: list[tuple[str, str, int]] = []
    for a in aliases:
        if not a.source_text or not a.canonical_name:
            continue
        code = catalog.find_code_by_name(db, a.canonical_name)
        if not code:
            continue
        product = db.query(Product).filter(Product.code == code).first()
        if not product:
            continue
        targets = [t for t in (product.canonical_name, product.display_name) if t]
        score = max(
            (fuzz.token_set_ratio(a.source_text, t) for t in targets), default=0
        )
        label = product.display_name or product.canonical_name or code
        if score < min_fuzzy:
            rejected.append((a.source_text, label, int(score)))
            continue
        out[code].append(a.source_text)
    return out, rejected


def apply_proposals(
    db: Session,
    proposals: dict[str, list[str]],
    *,
    dry_run: bool,
) -> dict:
    """Merge proposals into ``Product.aliases``; never removes existing entries."""
    products_updated = 0
    aliases_added = 0
    skipped_existing = 0
    skipped_identity = 0
    proposals_per_sku: dict[str, list[str]] = {}

    for code, new_aliases in proposals.items():
        product = db.query(Product).filter(Product.code == code).first()
        if not product:
            continue

        try:
            existing = json.loads(product.aliases) if product.aliases else []
            if not isinstance(existing, list):
                existing = []
        except json.JSONDecodeError:
            existing = []

        existing_keys = {_norm(a) for a in existing if isinstance(a, str)}
        canon_keys = {
            _norm(product.canonical_name),
            _norm(product.display_name or ""),
        }

        added_for_sku: list[str] = []
        for alias in new_aliases:
            k = _norm(alias)
            if not k:
                continue
            if k in canon_keys:
                skipped_identity += 1
                continue
            if k in existing_keys:
                skipped_existing += 1
                continue
            existing.append(alias)
            existing_keys.add(k)
            added_for_sku.append(alias)

        if added_for_sku:
            products_updated += 1
            aliases_added += len(added_for_sku)
            proposals_per_sku[code] = added_for_sku
            if not dry_run:
                product.aliases = json.dumps(existing, ensure_ascii=False)

    if not dry_run and products_updated:
        db.commit()
        catalog.invalidate_cache()

    return {
        "products_updated": products_updated,
        "aliases_added": aliases_added,
        "skipped_existing": skipped_existing,
        "skipped_identity": skipped_identity,
        "per_sku": proposals_per_sku,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh products.aliases from extraction history + user corrections.",
    )
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run).")
    parser.add_argument("--min-hits", type=int, default=3, help="Min times a raw form must appear.")
    parser.add_argument(
        "--min-dominance",
        type=float,
        default=0.7,
        help="Min share of hits the dominant SKU must own for a raw form to be promoted.",
    )
    parser.add_argument(
        "--min-user-hits",
        type=int,
        default=2,
        help="Min hit_count required to promote a product_aliases row.",
    )
    parser.add_argument(
        "--min-fuzzy",
        type=int,
        default=50,
        help=(
            "Min token_set_ratio between source_text and the resolved SKU's "
            "canonical/display name. Filters semantic-jump aliases that the "
            "user set per-document but shouldn't generalise."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-SKU listings; show summary only.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    db = SessionLocal()
    try:
        from_ext = mine_from_extractions(
            db,
            min_hits=args.min_hits,
            min_dominance=args.min_dominance,
        )
        from_users, user_rejected = mine_from_user_aliases(
            db,
            min_user_hits=args.min_user_hits,
            min_fuzzy=args.min_fuzzy,
        )

        merged: dict[str, list[str]] = defaultdict(list)
        for code, aliases in from_ext.items():
            merged[code].extend(aliases)
        for code, aliases in from_users.items():
            merged[code].extend(aliases)

        ext_total = sum(len(v) for v in from_ext.values())
        usr_total = sum(len(v) for v in from_users.values())

        print(f"Mined from extractions: {ext_total} proposals across {len(from_ext)} SKUs "
              f"(min-hits={args.min_hits}, min-dominance={args.min_dominance})")
        print(f"Mined from user aliases: {usr_total} proposals across {len(from_users)} SKUs "
              f"(min-user-hits={args.min_user_hits}, min-fuzzy={args.min_fuzzy})")
        if user_rejected:
            print(f"  Rejected {len(user_rejected)} user aliases below fuzzy threshold:")
            for source, label, score in user_rejected:
                print(f"    - {source!r} → {label!r} (score={score})")

        stats = apply_proposals(db, merged, dry_run=not args.apply)

        print()
        print(f"  Products updated:        {stats['products_updated']}")
        print(f"  Aliases added:           {stats['aliases_added']}")
        print(f"  Skipped (already alias): {stats['skipped_existing']}")
        print(f"  Skipped (canonical):     {stats['skipped_identity']}")

        if not args.quiet and stats["per_sku"]:
            print()
            print("Per-SKU additions:")
            for code, aliases in sorted(stats["per_sku"].items()):
                product = db.query(Product).filter(Product.code == code).first()
                label = product.display_name or product.canonical_name if product else code
                print(f"  {code} ({label})")
                for a in aliases:
                    print(f"    + {a}")

        print()
        if args.apply:
            print("APPLIED. Catalog cache invalidated.")
        else:
            print("DRY RUN — pass --apply to write changes.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
