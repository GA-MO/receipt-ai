"""Catalog service — the ``products`` table is the source of truth.

Used by:
* autocomplete — ``search_names()`` returns ranked canonical names
* alias service — ``is_canonical_name()`` prevents poisoning of catalog SKUs
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Iterable

from sqlalchemy.orm import Session

from ..models import Product

logger = logging.getLogger(__name__)


# Variant extractors, tried in priority order. First hit wins.
_VOLUME_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(CC|ml|L|ลิตร|มล\.|ล\.)", re.IGNORECASE)
_SIZE_LETTER_RE = re.compile(
    r"(?:ขนาด|SIZE|Size)\s*(XS|S|M|L|XL|XXL|2XL|3XL|4XL)", re.IGNORECASE
)
_BARE_SIZE_RE = re.compile(r"\((XS|S|M|L|XL|XXL|2XL|3XL|4XL|\d+)\)")
_CHEST_RE = re.compile(r"อก\s*(\d+)")
_PCS_RE = re.compile(r"(\d+)\s*ชิ้น")
_WEIGHT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ก\.|กก\.|กรัม)")


def _norm_volume(n: str, unit: str) -> str:
    unit = unit.lower()
    if unit in ("cc", "ml", "มล."):
        return f"{int(float(n))}ml"
    if unit in ("l", "ลิตร", "ล."):
        nf = float(n)
        return f"{int(nf) if nf.is_integer() else nf}L"
    return f"{n}{unit}"


def _extract_variant(name: str) -> str | None:
    """Pull the most-specific size/variant token from a catalog name."""
    m = _VOLUME_RE.search(name)
    if m:
        return _norm_volume(m.group(1), m.group(2))
    m = _SIZE_LETTER_RE.search(name)
    if m:
        return m.group(1).upper()
    m = _BARE_SIZE_RE.search(name)
    if m:
        return m.group(1).upper()
    m = _CHEST_RE.search(name)
    if m:
        return f"อก {m.group(1)}"
    m = _PCS_RE.search(name)
    if m:
        return f"{m.group(1)} ชิ้น"
    m = _WEIGHT_RE.search(name)
    if m:
        return f"{m.group(1)}{m.group(2).replace('.', '')}"
    return None


_LEMON_SODA_RE = re.compile(r"^สิงห์\s*(\S*?)เลมอนโซดา(.*)$")


def _normalize_brand_family(name: str) -> str:
    """Apply brand-specific canonicalisation for naming consistency.

    Currently handles the ``สิงห์เลมอนโซดา`` family only:
        "สิงห์ ครีมเลมอนโซดา"      → "สิงห์เลมอนโซดา ครีม"
        "สิงห์ เรดเลมอนโซดา"       → "สิงห์เลมอนโซดา เรด"
        "สิงห์ เลมอนโซดา"         → "สิงห์เลมอนโซดา"
        "สิงห์เลมอนโซดา รสแตงโม" (no change — already canonical)

    This moves the flavour qualifier to a trailing suffix so all variants
    share the same leading ``สิงห์เลมอนโซดา`` root, giving consistent sort
    order in autocomplete and dashboards.
    """
    m = _LEMON_SODA_RE.match(name)
    if not m:
        return name
    flavor = m.group(1).strip()
    suffix = m.group(2).strip()
    parts = ["สิงห์เลมอนโซดา"]
    if flavor:
        parts.append(flavor)
    if suffix:
        parts.append(suffix)
    return " ".join(parts)


def _strip_to_base(name: str) -> str:
    """Reduce a canonical_name to its "product family" base name.

    Drops parenthesised size/variant blocks, pack-count suffixes, marketing
    filler ("ใหม่", "New", "FREE ONPACK (TT)"), and collapses whitespace.
    Finally applies brand-family normalisation so variants share a
    consistent root.
    """
    s = re.sub(r"\s*\([^()]*\)\s*", " ", name)
    s = re.sub(r"\s*จำนวน\s+\d+\s*\S+\s*$", "", s)
    s = re.sub(r"(?:^|\s)\d+\s+(?:ถาด|ลัง|ชิ้น|แพ็[กค])\s*", " ", s)
    s = re.sub(r"FREE ONPACK\s*\([^)]*\)", "", s, flags=re.IGNORECASE)
    # Thai "ใหม่" — plain strip since Thai has no word boundary.
    s = re.sub(r"(?<![\w]) ?ใหม่ ?(?![\w])", " ", s)
    # English "New" — keep if followed by an uppercase brand word like "NEW ERA".
    s = re.sub(r"\bNew\b(?!\s+[A-Z]{2,})", "", s)
    s = re.sub(r"\s+-\s+Stackable", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+[-,/]\s*$", "", s)
    return _normalize_brand_family(s)


def build_display_names(items: list[tuple[str, str]]) -> dict[str, str]:
    """Compute the display_name for each ``(code, canonical_name)`` pair.

    Grouping rule: if multiple SKUs share the same base name, each display
    name gets its variant suffix (e.g. ``น้ำสิงห์เพ็ท 600ml``). If a base is
    unique, the bare base is used (no redundant size).

    Returns a ``{code: display_name}`` mapping.
    """
    base_by_code: dict[str, tuple[str, str | None]] = {}
    grouped: dict[str, list[str]] = defaultdict(list)
    for code, name in items:
        base = _strip_to_base(name)
        variant = _extract_variant(name)
        base_by_code[code] = (base, variant)
        grouped[base].append(code)

    out: dict[str, str] = {}
    for code, (base, variant) in base_by_code.items():
        if len(grouped[base]) > 1 and variant:
            out[code] = f"{base} {variant}".strip()
        else:
            out[code] = base
    return out


# In-memory cache of active canonical names, lower-cased for O(1) membership.
# Invalidated when admin endpoints mutate ``products``; rebuilt lazily.
_canonical_cache: frozenset[str] | None = None


def _norm(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.strip().split()).lower()


def invalidate_cache() -> None:
    global _canonical_cache
    _canonical_cache = None


def _load_canonicals(db: Session) -> frozenset[str]:
    rows = (
        db.query(Product.canonical_name)
        .filter(Product.active.is_(True))
        .all()
    )
    return frozenset(_norm(r[0]) for r in rows if r[0])


def canonical_set(db: Session) -> frozenset[str]:
    global _canonical_cache
    if _canonical_cache is None:
        _canonical_cache = _load_canonicals(db)
    return _canonical_cache


def is_canonical_name(db: Session, text: str | None) -> bool:
    if not text:
        return False
    return _norm(text) in canonical_set(db)


def search_names(
    db: Session,
    q: str = "",
    *,
    limit: int = 50,
    category: str | None = None,
) -> list[Product]:
    """Return active products whose canonical_name / brand / aliases match ``q``.

    Empty ``q`` returns the top ``limit`` active products ordered by name.
    """
    query = db.query(Product).filter(Product.active.is_(True))
    if category:
        query = query.filter(Product.category == category)
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            Product.canonical_name.ilike(pattern)
            | Product.brand_th.ilike(pattern)
            | Product.name_en.ilike(pattern)
            | Product.aliases.ilike(pattern)
        )
    return query.order_by(Product.canonical_name).limit(limit).all()


def iter_canonical_names(products: Iterable[Product]) -> list[str]:
    return [p.canonical_name for p in products if p.canonical_name]


_CATALOG_MATCH_THRESHOLD = 85


def find_code_by_name(db: Session, name: str | None) -> str | None:
    """Best-effort SKU lookup for ``name`` via RapidFuzz.

    Exact match wins (tried against both ``canonical_name`` and ``display_name``,
    case/space-insensitive). Falls back to ``token_set_ratio`` above
    ``_CATALOG_MATCH_THRESHOLD``.
    """
    key = _norm(name)
    if not key:
        return None

    from rapidfuzz import fuzz

    rows: list[tuple[str, str, str | None]] = (
        db.query(Product.code, Product.canonical_name, Product.display_name)
        .filter(Product.active.is_(True))
        .filter(Product.code.isnot(None))
        .all()
    )
    exact: str | None = None
    best_code: str | None = None
    best_score = 0.0
    for code, canon, display in rows:
        # Check both display_name and canonical_name for equality.
        for candidate in (display, canon):
            c_norm = _norm(candidate)
            if not c_norm:
                continue
            if c_norm == key:
                exact = code
                break
            score = fuzz.token_set_ratio(key, c_norm)
            if score > best_score:
                best_score = score
                best_code = code
        if exact:
            break
    if exact:
        return exact
    if best_code and best_score >= _CATALOG_MATCH_THRESHOLD:
        return best_code
    return None
