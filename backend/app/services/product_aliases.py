"""Learned product-name aliases.

Mirror of :mod:`services.aliases` for line-item products. Key differences
from the merchant version:

* **Higher fuzzy threshold** (``merchant_fuzzy_threshold + 4`` ≈ 92) because
  product names are short and share common substrings (e.g. "เบียร์ช้าง" vs
  "เบียร์ลีโอ" share "เบียร์"), so a looser threshold causes false positives.
* **Unit/quantity/price are never overridden** — only ``product_name_normalized``
  and ``category`` are learned.
* Applied per-item inside the extraction pipeline, not per-document.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ProductAlias
from ..schemas import DocumentItemBase
from .catalog import is_canonical_name as is_db_canonical

logger = logging.getLogger(__name__)


# Fuzzy score below this = the user's correction is not a "typo/variation"
# but a semantic override, and we refuse to learn it as a global alias.
_SEMANTIC_JUMP_THRESHOLD = 50


# ---------------------------------------------------------------------------
# Auto-trigger background alias refresh
# ---------------------------------------------------------------------------
#
# After every N successful user-confirmed alias upserts, fire the same logic
# as ``make refresh-aliases-apply`` in a background thread. Closes the loop:
#   user correct → ProductAlias row → counter++ → background mining →
#   Product.aliases JSON updated → next extraction sees richer aliases.
#
# Rate-limited via ``_REFRESH_MIN_GAP_SECONDS`` so a burst of corrections
# doesn't trigger N concurrent refreshes.

_REFRESH_TRIGGER_THRESHOLD = 10
_REFRESH_MIN_GAP_SECONDS = 600  # 10 min
_corrections_counter = 0
_last_refresh_at = 0.0
_refresh_lock = threading.Lock()


def _maybe_trigger_background_refresh() -> None:
    """Increment the correction counter; fire refresh if threshold reached.

    Idempotent and thread-safe. Failures are logged but never raised — alias
    upsert is the user-facing operation and must not be blocked by mining.
    """
    global _corrections_counter, _last_refresh_at

    with _refresh_lock:
        _corrections_counter += 1
        if _corrections_counter < _REFRESH_TRIGGER_THRESHOLD:
            return
        if time.monotonic() - _last_refresh_at < _REFRESH_MIN_GAP_SECONDS:
            return
        _corrections_counter = 0
        _last_refresh_at = time.monotonic()

    def _runner() -> None:
        try:
            from ..scripts.refresh_product_aliases import run_refresh

            stats = run_refresh(apply=True)
            logger.info(
                "Auto alias refresh complete: %d products updated, %d aliases added",
                stats.get("products_updated", 0),
                stats.get("aliases_added", 0),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Background alias refresh failed: %s", exc)

    threading.Thread(target=_runner, daemon=True, name="alias-refresh").start()
    logger.info("Triggered background alias refresh after %d corrections", _REFRESH_TRIGGER_THRESHOLD)


class AliasSkipReason(str, Enum):
    CATALOG_CONFLICT = "catalog_conflict"
    SEMANTIC_JUMP = "semantic_jump"
    EMPTY = "empty"
    IDENTITY = "identity"
    AMBIGUOUS_SOURCE = "ambiguous_source"


@dataclass
class UpsertResult:
    """Outcome of an ``upsert_alias`` call.

    If ``alias`` is ``None`` the alias was refused; ``skipped_reason`` explains
    why and UIs can surface it to the user.
    """

    alias: ProductAlias | None = None
    skipped_reason: AliasSkipReason | None = None
    skipped_detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.alias is not None


def _is_catalog_canonical(text: str, db: Session) -> bool:
    """True if ``text`` is the canonical name of an active catalog SKU.

    The catalog used to live in two places (a hardcoded list in
    ``extraction.py`` plus the ``products`` table). Both are now sourced from
    ``products``, so this is a thin wrapper around :func:`is_db_canonical`
    that guards alias learning from poisoning catalog SKUs.
    """
    return is_db_canonical(db, text)


_PARTIAL_RATIO_MIN_LENGTH_RATIO = 0.6


def _fuzzy_score(a: str, b: str) -> float:
    """Fuzzy score between two strings, tuned for Thai product names.

    ``partial_ratio`` returns 100 whenever one string is a substring of the
    other, which makes short aliases (e.g. ``สิงห์``) match every longer item
    name (e.g. ``น้ำสิงห์เปลี่ยนถาด``). We only apply partial_ratio when the
    two strings are roughly similar in length — otherwise a short catalog
    fragment hijacks matches from more specific aliases.
    """
    score = fuzz.token_set_ratio(a, b)
    la, lb = len(a), len(b)
    if la and lb and min(la, lb) / max(la, lb) >= _PARTIAL_RATIO_MIN_LENGTH_RATIO:
        score = max(score, fuzz.partial_ratio(a, b))
    return score


# Threshold boost above the merchant fuzzy threshold. Products have shorter
# text and share common prefixes, so we need to be stricter.
_PRODUCT_FUZZY_BOOST = 4


def _threshold() -> int:
    return min(100, settings.merchant_fuzzy_threshold + _PRODUCT_FUZZY_BOOST)


def normalize_key(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.strip().split()).lower()


def lookup_alias(db: Session, raw_text: str) -> ProductAlias | None:
    """Exact match then fuzzy (``max(token_set, partial)`` ≥ threshold)."""
    key = normalize_key(raw_text)
    if not key:
        return None

    exact = (
        db.query(ProductAlias)
        .filter(ProductAlias.source_text == key)
        .first()
    )
    if exact:
        return exact

    all_aliases = db.query(ProductAlias).all()
    if not all_aliases:
        return None

    pool: dict[str, ProductAlias] = {}
    for a in all_aliases:
        pool[a.source_text] = a
        canon_key = normalize_key(a.canonical_name)
        if canon_key and canon_key not in pool:
            pool[canon_key] = a

    threshold = _threshold()
    best_key: str | None = None
    best_score = 0.0
    for candidate in pool:
        score = _fuzzy_score(key, candidate)
        if score > best_score:
            best_score = score
            best_key = candidate
    if best_key is None or best_score < threshold:
        return None
    logger.info("Fuzzy product-alias match: %r ≈ %r (score=%.1f)", key, best_key, best_score)
    return pool[best_key]


def upsert_alias(
    db: Session,
    *,
    source_text: str,
    canonical_name: str,
    category: str | None = None,
) -> UpsertResult:
    """Persist an alias from ``source_text`` → ``canonical_name``, with guards.

    Refuses (and returns :class:`AliasSkipReason`) when:

    * ``source_text`` is a canonical SKU in the products catalog — learning it
      would rewrite every future document that legitimately matches it.
    * ``fuzzy(source, canonical) < 50`` — a big semantic jump (e.g.
      ``เบียร์ลีโอขวดเล็ก`` → ``สิงห์เลม่อนโซดา``) is almost always a
      per-document fix, not a global rule.
    """
    key = normalize_key(source_text)
    canonical = (canonical_name or "").strip()
    if not key or not canonical:
        return UpsertResult(skipped_reason=AliasSkipReason.EMPTY)

    if normalize_key(canonical) == key and category is None:
        return UpsertResult(skipped_reason=AliasSkipReason.IDENTITY)

    # Guard 1: source is a catalog canonical → learning would poison the
    # mapping for every receipt that correctly matched that canonical.
    if _is_catalog_canonical(source_text, db):
        logger.warning(
            "Refused product alias: source %r is a catalog canonical",
            source_text,
        )
        return UpsertResult(
            skipped_reason=AliasSkipReason.CATALOG_CONFLICT,
            skipped_detail=source_text,
        )

    # Guard 2: if the correction is semantically far from the source, the
    # user is almost certainly fixing a mis-normalization specific to this
    # document. Do not generalize.
    score = _fuzzy_score(source_text, canonical)
    if score < _SEMANTIC_JUMP_THRESHOLD:
        logger.warning(
            "Refused product alias: %r → %r is too different (fuzzy=%.1f)",
            source_text,
            canonical,
            score,
        )
        return UpsertResult(
            skipped_reason=AliasSkipReason.SEMANTIC_JUMP,
            skipped_detail=f"fuzzy={score:.0f}",
        )

    existing = (
        db.query(ProductAlias)
        .filter(ProductAlias.source_text == key)
        .first()
    )
    if existing:
        existing.canonical_name = canonical
        if category is not None:
            existing.category = category or None
        existing.hit_count = int(existing.hit_count or 0) + 1
        existing.updated_at = datetime.now(UTC)
        db.commit()
        _maybe_trigger_background_refresh()
        return UpsertResult(alias=existing)

    alias = ProductAlias(
        source_text=key,
        canonical_name=canonical,
        category=(category or None),
        hit_count=1,
    )
    db.add(alias)
    db.commit()
    db.refresh(alias)
    logger.info("Learned new product alias: %r → %r (cat=%s)", key, canonical, category)
    _maybe_trigger_background_refresh()
    return UpsertResult(alias=alias)


def apply_alias_to_item(db: Session, item: DocumentItemBase) -> ProductAlias | None:
    """Override ``product_name_normalized`` + ``category`` in-place if match.

    Lookup priority:
      1. ``product_name_raw`` — the OCR signal Gemini captured. Stable across
         edits, so this is the authoritative source for alias learning.
      2. ``product_name_normalized`` — fallback when raw is missing (legacy
         rows created before migration 0011).

    Unit, quantity, and price are never touched — those are per-receipt facts.
    Skipped entirely when the item already has a ``product_code`` — code is the
    unambiguous DB pointer, so a fuzzy alias match on raw (which can return a
    different SKU) must not be allowed to desync name from code.
    Increments ``hit_count`` on the matched alias.
    """
    if getattr(item, "product_code", None):
        return None
    raw = getattr(item, "product_name_raw", None)
    lookup_text = raw or item.product_name_normalized or ""
    alias = lookup_alias(db, lookup_text)
    if not alias:
        return None
    item.product_name_normalized = alias.canonical_name
    if alias.category:
        item.category = alias.category
    try:
        alias.hit_count = int(alias.hit_count or 0) + 1
        alias.updated_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to bump product alias hit_count: %s", exc)
        db.rollback()
    return alias


def apply_aliases_to_items(db: Session, items: list[DocumentItemBase]) -> int:
    """Bulk-apply; returns the number of items that matched an alias."""
    return sum(1 for it in items if apply_alias_to_item(db, it) is not None)
