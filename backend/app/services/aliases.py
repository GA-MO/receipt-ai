"""Learned merchant/category aliases.

User corrections are cheap supervision: if a human renames "7-11 อโศก" to
"7-Eleven" and bumps the category to "อาหาร", future extractions of that same
raw merchant text should auto-apply both without bothering the user again.

Public API:
    - :func:`normalize_key` — lowercase + strip whitespace for stable lookups.
    - :func:`lookup_alias` — fetch a single alias by raw text.
    - :func:`upsert_alias` — insert or increment ``hit_count`` on an existing row.
    - :func:`apply_alias_to_extraction` — mutate ``ExtractionResult`` in place if
      a learned alias exists for the incoming merchant text.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from ..config import settings
from ..models import MerchantAlias
from ..schemas import ExtractionResult

logger = logging.getLogger(__name__)


def normalize_key(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.strip().split()).lower()


def lookup_alias(db: Session, raw_text: str) -> MerchantAlias | None:
    """Find a learned alias for ``raw_text``.

    First tries exact match on normalized source. Falls back to fuzzy match
    (RapidFuzz token_set_ratio) above ``merchant_fuzzy_threshold`` so Gemini's
    natural variation in reading the same receipt still hits the right alias.
    """
    key = normalize_key(raw_text)
    if not key:
        return None

    exact = (
        db.query(MerchantAlias)
        .filter(MerchantAlias.source_text == key)
        .first()
    )
    if exact:
        return exact

    # Fuzzy fallback against both source_text and canonical_name — Gemini
    # sometimes returns the already-corrected canonical form instead of the
    # original raw text, and we still want to count that as a match.
    # We score with the max of two metrics:
    #   - token_set_ratio (good for word re-orderings / extra tokens)
    #   - partial_ratio  (good for shared substrings — critical for Thai,
    #                     which has no word spaces so token-level scoring
    #                     underweights common inner substrings)
    all_aliases = db.query(MerchantAlias).all()
    if not all_aliases:
        return None

    pool: dict[str, MerchantAlias] = {}
    for a in all_aliases:
        pool[a.source_text] = a
        canon_key = normalize_key(a.canonical_name)
        if canon_key and canon_key not in pool:
            pool[canon_key] = a

    threshold = settings.merchant_fuzzy_threshold
    best_key: str | None = None
    best_score = 0.0
    for candidate in pool:
        score = max(
            fuzz.token_set_ratio(key, candidate),
            fuzz.partial_ratio(key, candidate),
        )
        if score > best_score:
            best_score = score
            best_key = candidate
    if best_key is None or best_score < threshold:
        return None
    logger.info("Fuzzy alias match: %r ≈ %r (score=%.1f)", key, best_key, best_score)
    return pool[best_key]


def upsert_alias(
    db: Session,
    *,
    source_text: str,
    canonical_name: str,
    category: str | None = None,
) -> MerchantAlias | None:
    """Insert a new alias or bump ``hit_count`` on an existing one.

    Returns the persisted alias, or ``None`` if inputs are invalid.
    """
    key = normalize_key(source_text)
    canonical = (canonical_name or "").strip()
    if not key or not canonical:
        return None

    existing = (
        db.query(MerchantAlias)
        .filter(MerchantAlias.source_text == key)
        .first()
    )
    if existing:
        existing.canonical_name = canonical
        if category is not None:
            existing.category = category or None
        existing.hit_count = int(existing.hit_count or 0) + 1
        existing.updated_at = datetime.now(UTC)
        db.commit()
        return existing

    alias = MerchantAlias(
        source_text=key,
        canonical_name=canonical,
        category=(category or None),
        hit_count=1,
    )
    db.add(alias)
    db.commit()
    db.refresh(alias)
    logger.info("Learned new alias: %r → %r (cat=%s)", key, canonical, category)
    return alias


def apply_alias_to_extraction(
    db: Session,
    result: ExtractionResult,
) -> MerchantAlias | None:
    """If a learned alias matches the raw merchant name, override fields.

    Lookup order: exact match on ``merchant_name``, then ``merchant_normalized``
    (with RapidFuzz fallback for near-misses). User corrections are treated as
    authoritative — if the alias has a ``category``, it overrides whatever
    Gemini guessed. Increments ``hit_count`` on the matched alias so the UI
    can show how often the correction was actually reused.
    """
    candidates = [result.merchant_name, result.merchant_normalized]
    for cand in candidates:
        alias = lookup_alias(db, cand or "")
        if alias:
            result.merchant_name = alias.canonical_name
            result.merchant_normalized = alias.canonical_name
            if alias.category:
                result.category = alias.category
            try:
                alias.hit_count = int(alias.hit_count or 0) + 1
                alias.updated_at = datetime.now(UTC)
                db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to bump alias hit_count: %s", exc)
                db.rollback()
            return alias
    return None
