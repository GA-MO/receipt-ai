"""Merchant name normalization.

The LLM may already return ``merchant_normalized``. This module:

1. Applies rule-based cleaning to strip prefixes like "ร้าน", "บริษัท", "จำกัด"
   when the LLM's value is missing or still noisy.
2. Fuzzy-matches the cleaned name against the list of known canonical
   ``merchant_normalized`` values in the DB so that three variants of the same
   store end up with the exact same canonical string.

That canonical string is then used for top-merchants aggregation, fraud
history, and dedup — eliminating the "ก.เจริญ" vs "ร้าน ก.เจริญ" vs
"ก.เจริญ การค้า" split in dashboards.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Store

logger = logging.getLogger(__name__)

# Prefixes / suffixes commonly glued onto Thai merchant names that we want to
# strip. Thai doesn't use spaces between words so many prefixes like "ร้าน" /
# "บริษัท" are glued directly to the name — patterns below allow an optional
# whitespace boundary.
#
# Order matters: parenthesised branch / head-office tags must be stripped
# *before* "จำกัด$" so that e.g. "จำกัด(สำนักงานใหญ่)" reduces properly.
_STRIP_PATTERNS = [
    # Branch / head-office markers that often appear in parentheses at the end.
    re.compile(
        r"\s*[(（]\s*(สำนักงานใหญ่|สนญ\.?|HQ|Head\s*Office)\s*[)）]\s*$",
        re.IGNORECASE,
    ),
    # Trailing parens containing only ASCII (a romanized form of the Thai name,
    # e.g. "จำปิสโตร์ (Jampi Store)"). We strip these because Thai merchants
    # often include the English translation but it skews token_set_ratio.
    # Kept conservative: only matches when the *entire* parenthesised content
    # is ASCII printable + spaces — Thai-language clarifiers like "(เก่า)" or
    # "(สาขา 2)" are preserved as they may disambiguate genuinely different
    # stores.
    re.compile(r"\s*[(（]\s*[\x20-\x7E]+\s*[)）]\s*$"),
    # Trailing standalone "สำนักงานใหญ่" without parentheses.
    re.compile(r"\s*สำนักงานใหญ่\s*$", re.IGNORECASE),
    # \b doesn't work well with Thai (no word boundaries), so just match everything after "สาขา".
    # Optional opening paren in front so "(สาขา 2)" doesn't leave a dangling "(".
    re.compile(r"\s*[(（]?\s*สาขา.*$", re.IGNORECASE),
    # Company-type prefixes at the start.
    re.compile(
        r"^\s*(บริษัท|บจก\.?|หจก\.?|ห้างหุ้นส่วนจำกัด|ห้างหุ้นส่วนสามัญ)\s*",
        re.IGNORECASE,
    ),
    # "จำกัด" suffix with optional "(มหาชน)" — applied after branch markers so
    # cases like "จำกัด (สำนักงานใหญ่)" collapse correctly.
    re.compile(r"\s*(จำกัด|จก\.?)\s*(\(มหาชน\))?\s*$", re.IGNORECASE),
    re.compile(r"^\s*ร้าน\s*", re.IGNORECASE),
    re.compile(r"\s*Co\.?\s*Ltd\.?\s*$", re.IGNORECASE),
    re.compile(r"\s*(Inc\.?|LLC|Ltd\.?|Corp\.?)\s*$", re.IGNORECASE),
]

_WHITESPACE = re.compile(r"\s+")


def _rule_based_clean(name: str) -> str:
    cleaned = name.strip()
    # Apply each strip pattern repeatedly until it no longer matches.
    for pattern in _STRIP_PATTERNS:
        while True:
            new = pattern.sub(" ", cleaned).strip()
            if new == cleaned:
                break
            cleaned = new
    cleaned = _WHITESPACE.sub(" ", cleaned).strip(" .,-")
    return cleaned


def _load_known_canonicals(db: Session) -> list[str]:
    """Canonical merchant names come from the **active** Store master.

    Store master is the single source of truth for merchants (see CLAUDE.md).
    Document.merchant_normalized must not be used here — a soft-deleted store
    would otherwise keep influencing future clustering through orphaned doc
    rows. Each Store contributes both its ``normalized_name`` and ``name`` so
    cleaning catches either form.
    """
    rows = (
        db.query(Store.normalized_name, Store.name)
        .filter(Store.active.is_(True))
        .all()
    )
    canonicals: list[str] = []
    for normalized, name in rows:
        for val in (normalized, name):
            if val:
                canonicals.append(val)
    return canonicals


def _fuzzy_match(candidate: str, known: Iterable[str], threshold: int) -> str | None:
    """Return the best known canonical if similarity >= threshold."""
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        logger.debug("rapidfuzz not installed; skipping fuzzy merchant match")
        return None

    known_list = list(known)
    if not known_list:
        return None

    match = process.extractOne(
        candidate,
        known_list,
        scorer=fuzz.token_set_ratio,
    )
    if match and match[1] >= threshold:
        return match[0]
    return None


def normalize_merchant(
    raw_name: str | None,
    llm_hint: str | None,
    db: Session,
    threshold: int | None = None,
) -> str | None:
    """Produce a canonical merchant string for grouping / dedup.

    Preference order:
      1. Fuzzy match against an active Store master row.
      2. LLM-provided ``merchant_normalized`` — but always passed through
         rule-based cleaning to catch leftover company-type / branch markers
         (LLMs sometimes forget to strip "จำกัด(สำนักงานใหญ่)", for example).
      3. Rule-based cleaning of the raw name.
    """
    if not raw_name and not llm_hint:
        return None

    # Always rule-clean both the LLM hint (if any) and the raw name. Prefer
    # the LLM hint as a starting point because it often already stripped
    # company prefixes.
    hint_clean = _rule_based_clean(llm_hint or "")
    raw_clean = _rule_based_clean(raw_name or "")
    candidate = hint_clean or raw_clean
    if not candidate:
        return None

    # Fuzzy-match against cleaned-up names from the active Store master.
    # Inactive (soft-deleted) stores are excluded so they don't keep
    # poisoning future clustering after the admin has cleaned them up.
    raw_known = _load_known_canonicals(db)
    # Map cleaned -> original-cleaned so the returned canonical is already normalised.
    cleaned_known = {_rule_based_clean(k) for k in raw_known if k}
    cleaned_known.discard("")

    matched = _fuzzy_match(
        candidate,
        cleaned_known,
        threshold=threshold if threshold is not None else settings.merchant_fuzzy_threshold,
    )
    if matched:
        return matched
    return candidate


def assign_normalized_merchant(doc: Document, db: Session) -> None:
    """Set ``doc.merchant_normalized`` in place based on current data + history."""
    doc.merchant_normalized = normalize_merchant(
        raw_name=doc.merchant_name,
        llm_hint=doc.merchant_normalized,
        db=db,
    )
