"""Per-line confidence: familiarity + ambiguity against rival SKUs.

Pure functions over a dictionary, so the cases mirror real receipts without
any LLM call. The two wrong picks that slipped through green in the demo set
(bare "น้ำสิงห์" → PET 600; "โซดาสิงห์เปลี่ยนขวด" → water) must flag.
"""

from app.models import Product, ProductAlias
from app.services.line_confidence import build_known_forms, score_line


def _seed(db):
    rows = [
        # code, canonical, display, seed tags (JSON list)
        ("W-GLASS", "น้ำดื่มสิงห์ขวดแก้ว", "น้ำดื่มสิงห์ขวดแก้ว", '["น้ำสิงห์", "น้ำสิงห์เปลี่ยนขวด"]'),
        ("W-PET600", "น้ำสิงห์เพ็ท ใหม่ (12x600CC)", "น้ำสิงห์เพ็ท 600ml", '["น้ำสิงห์", "น้ำสิงห์ 600"]'),
        ("SODA", "โซดาสิงห์ 1 ถาด", "โซดาสิงห์", '["โซดา", "โซดาสิงห์เปลี่ยนขวด"]'),
        ("LEMON", "สิงห์ เลมอนโซดา", "สิงห์เลมอนโซดา", '["เลมอนโซดา"]'),
        ("LEMON-RED", "สิงห์ เรดเลมอนโซดา", "สิงห์เลมอนโซดา เรด", '["สิงห์เลมอนโซดา", "เรด"]'),
        ("BEER-L", "เบียร์สิงห์ขวดใหญ่", "เบียร์สิงห์ขวดใหญ่", '["เบียร์", "บส.ญ"]'),
        ("BEER-CAN", "เบียร์สิงห์กระป๋อง", "เบียร์สิงห์กระป๋อง", '["เบียร์", "สิงห์กระป๋อง"]'),
    ]
    for code, canon, disp, tags in rows:
        db.add(Product(code=code, canonical_name=canon, display_name=disp, aliases=tags, active=True))
    db.commit()


def test_shared_seed_tag_is_dropped_but_own_name_survives(db_session):
    _seed(db_session)
    kf = build_known_forms(db_session)
    # "เบียร์" is claimed by two SKUs as a tag → vouches for neither.
    assert "เบียร์" not in kf["BEER-L"] and "เบียร์" not in kf["BEER-CAN"]
    # The flavoured variant lists the plain SKU's display name as a tag; the
    # plain SKU's OWN name must still be its form.
    assert "สิงห์เลมอนโซดา" in kf["LEMON"]
    assert "สิงห์เลมอนโซดา" not in kf["LEMON-RED"]


def test_learned_alias_takes_ownership_of_a_shared_form(db_session):
    _seed(db_session)
    db_session.add(ProductAlias(source_text="น้ำสิงห์", canonical_name="น้ำดื่มสิงห์ขวดแก้ว", hit_count=3))
    db_session.commit()
    kf = build_known_forms(db_session)
    assert "น้ำสิงห์" in kf["W-GLASS"]
    assert "น้ำสิงห์" not in kf["W-PET600"]
    # ...and with the alias in place a bare "น้ำสิงห์" picked as glass is green,
    assert not score_line("น้ำสิงห์", "W-GLASS", kf).needs_review
    # while the same text picked as PET 600 (the 07.jpeg miss) is flagged even
    # though it token-matches PET's aliases perfectly.
    s = score_line("น้ำสิงห์", "W-PET600", kf)
    assert s.needs_review and "SKU อื่น" in s.reason


def test_exact_hit_beats_fuzzy_rival(db_session):
    _seed(db_session)
    kf = build_known_forms(db_session)
    # "น้ำสิงห์ 600" is PET's own tag; the fact that it *contains* a rival's
    # form must not make it ambiguous.
    s = score_line("น้ำสิงห์ 600", "W-PET600", kf)
    assert s.confidence == 1.0 and not s.needs_review


def test_wrong_sibling_pick_is_flagged(db_session):
    _seed(db_session)
    kf = build_known_forms(db_session)
    # The 05.jpeg miss: soda text filed under water. Soda owns this exact form.
    s = score_line("โซดาสิงห์เปลี่ยนขวด", "W-GLASS", kf)
    assert s.needs_review
    assert not score_line("โซดาสิงห์เปลี่ยนขวด", "SODA", kf).needs_review


def test_unfamiliar_and_unmatched_lines_still_flag(db_session):
    _seed(db_session)
    kf = build_known_forms(db_session)
    assert score_line("สัวเล็ก", "BEER-L", kf).needs_review
    assert score_line("อะไรก็ได้", None, kf).confidence == 0.3


# ---------- per-line quantity reason ----------

def test_quantity_disagreement_is_reported_per_line():
    from app.schemas import DocumentItemBase
    from app.services.validation import quantity_disagrees_with_bill

    # 09.jpeg: "3 ลัง" read as 30 while หน่วยละ 644 × amount 1932 says 3.
    item = DocumentItemBase(product_name_normalized="x", quantity=30, unit="ลัง", unit_price=644, amount=1932)
    assert quantity_disagrees_with_bill(item) == 3
    ok = DocumentItemBase(product_name_normalized="x", quantity=3, unit="ลัง", unit_price=644, amount=1932)
    assert quantity_disagrees_with_bill(ok) is None
    no_price = DocumentItemBase(product_name_normalized="x", quantity=30, unit="ลัง", amount=1932)
    assert quantity_disagrees_with_bill(no_price) is None
