"""Per-line confidence — verifiable, NOT model self-grading.

The model never grades its own reading here. Confidence for one extracted line
is computed server-side from signals we can check against the catalog and the
confirmation history:

  * familiarity — does the text the model READ (``product_name_raw``) match a
    KNOWN form of the SKU it picked? "Known forms" = the SKU's canonical/display
    name + its seed aliases + every shorthand a reviewer has already confirmed
    (``product_aliases``). So a wildly-abbreviated but *proven* shorthand like
    "บส.ญ" → เบียร์สิงห์ขวดใหญ่ scores high once confirmed, while a one-off
    misread like "สัวเล็ก" stays low. The discriminator is "have we seen this
    mapping confirmed before", not "does the text look like the full name".
  * catalog gap — no SKU resolved at all → low, always flag.

Cold-start caveat: before the alias dictionary is warm, even correct shorthand
is unproven and gets flagged. That is safe (more review, never a silent wrong
value); the dictionary fills from reviewer confirmations and the flag set
shrinks to true anomalies over time.

This score is for TRIAGE — sort/highlight risky lines for the human reviewer —
never to auto-accept. The review step stays.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from ..models import Product, ProductAlias
from .catalog import _norm, _parse_seed_aliases

# A line at/above this blended score is treated as trusted (no per-line flag).
# Tuned so proven shorthand (exact known alias = 1.0) passes and unproven /
# dissimilar reads fall below.
REVIEW_THRESHOLD = 0.80
# Confidence floor for a line whose product never resolved to a catalog SKU.
CATALOG_GAP_CONFIDENCE = 0.30
# A learned shorthand is only trusted after this many confirmations
# (corroboration) — one reviewer mis-confirming a single receipt must not be
# enough to make a bad mapping look certain forever.
CONFIRM_CORROBORATION = 2


@dataclass(frozen=True)
class LineScore:
    confidence: float
    needs_review: bool
    reason: str  # short, human-readable: why this score (auditable)


def build_known_forms(db: Session) -> dict[str, set[str]]:
    """Map ``code -> {normalized trusted forms}``.

    Always-trusted: the SKU's canonical/display name + curated seed aliases
    (the catalog's shorthand column). Learned shorthand from reviewer
    confirmations is trusted only once corroborated ``hit_count >=
    CONFIRM_CORROBORATION`` — so a brand-new confirmation needs a second sighting
    before it stops being flagged.
    """
    products = (
        db.query(Product)
        .filter(Product.active.is_(True), Product.code.isnot(None))
        .all()
    )
    forms: dict[str, set[str]] = {}
    canon_to_code: dict[str, str] = {}
    for p in products:
        bag = {_norm(p.display_name), _norm(p.canonical_name)}
        bag.update(_norm(a) for a in _parse_seed_aliases(p.aliases))
        forms[p.code] = {b for b in bag if b}
        for nm in (p.canonical_name, p.display_name):
            if nm:
                canon_to_code[_norm(nm)] = p.code

    for a in db.query(ProductAlias).filter(
        ProductAlias.hit_count >= CONFIRM_CORROBORATION
    ):
        code = canon_to_code.get(_norm(a.canonical_name))
        key = _norm(a.source_text)
        if code and key:
            forms.setdefault(code, set()).add(key)
    return forms


def score_line(raw: str | None, code: str | None, known_forms: dict[str, set[str]]) -> LineScore:
    """Score one extracted line. Pure function of (read text, picked SKU, dictionary)."""
    if not code:
        return LineScore(CATALOG_GAP_CONFIDENCE, True, "ไม่พบสินค้าใน catalog")

    key = _norm(raw)
    forms = known_forms.get(code) or set()
    if not key:
        return LineScore(CATALOG_GAP_CONFIDENCE, True, "อ่านชื่อสินค้าไม่ได้")

    if key in forms:
        return LineScore(1.0, False, "ตรงกับคำย่อ/ชื่อที่ยืนยันแล้ว")

    best = max((fuzz.token_set_ratio(key, f) for f in forms), default=0) / 100.0
    needs = best < REVIEW_THRESHOLD
    reason = "ตัวย่อนี้ยังไม่เคยยืนยัน — รอตรวจ" if needs else "ใกล้เคียงชื่อใน catalog"
    return LineScore(round(best, 2), needs, reason)
