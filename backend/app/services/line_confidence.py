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
  * ambiguity — does some OTHER SKU explain the read text at least as well as
    the picked one? Familiarity alone is blind inside a product family: a bare
    "น้ำสิงห์" is a token-subset of every Singha-water alias, so it scores 1.0
    for the glass bottle, PET 600 and PET 1.5L alike — and the one wrong SKU
    in the demo set slipped through green exactly that way. If a rival ties or
    wins, the text does not say which SKU it is, and the line is flagged even
    when its own score is high. Forms shared by several SKUs ("เบียร์",
    "โซดา", "สิงห์") are dropped from the dictionary for this reason; a
    reviewer-confirmed alias belongs to one SKU, so the flag heals as the
    dictionary warms.
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
from .app_settings import use_learned_aliases
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
    # Every form with the codes that claim it, by evidence strength. A form
    # that several SKUs claim cannot vouch for any one of them, so ownership
    # is resolved per form: a reviewer-confirmed alias beats a SKU's own name,
    # which beats a seed tag ("เบียร์" is a seed tag of 17 codes; the
    # flavoured lemon sodas list the plain one's name as a tag). Losing forms
    # are dropped from the confidence dictionary — they stay in the LLM
    # prompt, where breadth helps.
    names: dict[str, set[str]] = {}
    tags: dict[str, set[str]] = {}
    canon_to_code: dict[str, str] = {}
    for p in products:
        for nm in (p.canonical_name, p.display_name):
            key = _norm(nm)
            if key:
                names.setdefault(key, set()).add(p.code)
                canon_to_code[key] = p.code
        for a in _parse_seed_aliases(p.aliases):
            key = _norm(a)
            if key:
                tags.setdefault(key, set()).add(p.code)

    learned: dict[str, set[str]] = {}
    alias_rows = (
        db.query(ProductAlias).filter(ProductAlias.hit_count >= CONFIRM_CORROBORATION)
        if use_learned_aliases(db)
        else []
    )
    for a in alias_rows:
        code = canon_to_code.get(_norm(a.canonical_name))
        key = _norm(a.source_text)
        if code and key:
            learned.setdefault(key, set()).add(code)

    forms: dict[str, set[str]] = {p.code: set() for p in products}
    for key in set(names) | set(tags) | set(learned):
        for tier in (learned.get(key), names.get(key), tags.get(key)):
            if tier:
                if len(tier) == 1:
                    forms[next(iter(tier))].add(key)
                break  # a tie at the strongest tier drops the form entirely
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
        # Exact dictionary hit. No other SKU can hold the same form (shared
        # forms are dropped in build_known_forms), so nothing to disambiguate.
        return LineScore(1.0, False, "ตรงกับคำย่อ/ชื่อที่ยืนยันแล้ว")

    picked = _best_match(key, forms)
    # Ambiguity: an exact hit on another SKU, or a fuzzy rival at least as
    # close, means the text does not single out the picked SKU. Reported with
    # the picked score intact — the number stays "how well the text matches",
    # the flag says why it still needs eyes.
    rival_exact = any(key in f for c, f in known_forms.items() if c != code)
    rival = max(
        (_best_match(key, f) for c, f in known_forms.items() if c != code and f),
        default=0.0,
    )
    if rival_exact or (rival >= picked and picked >= REVIEW_THRESHOLD):
        return LineScore(
            round(picked, 2), True, "ข้อความนี้ตรง SKU อื่นได้เท่ากัน — ระบุขนาด/แบบไม่ได้ เทียบกับรูป"
        )
    needs = picked < REVIEW_THRESHOLD
    reason = "ตัวย่อนี้ยังไม่เคยยืนยัน — รอตรวจ" if needs else "ใกล้เคียงชื่อใน catalog"
    return LineScore(round(picked, 2), needs, reason)


def _best_match(key: str, forms: set[str]) -> float:
    return max((fuzz.token_set_ratio(key, f) for f in forms), default=0) / 100.0
