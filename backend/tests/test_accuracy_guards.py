"""Tests for the silent-error accuracy guards added to close rollup gaps:
mixed-unit split, semantic dedup, store-match confidence, quantity sanity,
and the validation-only amount cross-check. All zero extra LLM cost.
"""

from app.models import Document, Store
from app.schemas import DocumentItemBase, ExtractionResult
from app.services.validation import validate_extraction
from app.services.visits import check_duplicate_receipt, check_store_match_confidence


def _item(**kw):
    base = dict(product_name_normalized="เบียร์สิงห์ขวดใหญ่",
               product_code="INT-BEER-SINGHA-L", quantity=2, unit="ลัง")
    base.update(kw)
    return DocumentItemBase(**base)


def _result(items, **kw):
    base = dict(merchant_name="ร้านทดสอบ", document_date="2025-12-01",
               category="เครื่องดื่ม", confidence=0.95, items=items)
    base.update(kw)
    return ExtractionResult(**base)


# ---------- quantity sanity (#4) ----------

def test_fractional_qty_on_discrete_unit_flagged():
    w = validate_extraction(_result([_item(quantity=2.5, unit="ลัง")]))
    assert any("มีเศษ" in m for m in w)


def test_whole_qty_on_discrete_unit_ok():
    w = validate_extraction(_result([_item(quantity=3, unit="ลัง")]))
    assert not any("มีเศษ" in m for m in w)


def test_absurd_qty_flagged():
    w = validate_extraction(_result([_item(quantity=5000)]))
    assert any("สูงผิดปกติ" in m for m in w)


# ---------- amount cross-check (#5) ----------

def test_amount_total_mismatch_flagged():
    items = [_item(quantity=2, amount=5600), _item(product_code="INT-BEER-LEO-L", amount=9300)]
    w = validate_extraction(_result(items, validation_total=24700))
    assert any("ไม่ตรงยอดท้ายบิล" in m for m in w)


def test_amount_total_match_ok():
    items = [_item(amount=5600), _item(product_code="INT-BEER-LEO-L", amount=9300)]
    w = validate_extraction(_result(items, validation_total=14900))
    assert not any("ไม่ตรงยอดท้ายบิล" in m for m in w)


def test_amount_check_skipped_when_amounts_missing():
    # No amounts read → no false positive
    w = validate_extraction(_result([_item(amount=None)], validation_total=5600))
    assert not any("ไม่ตรงยอดท้ายบิล" in m for m in w)


# ---------- quantity x unit_price cross-check (#6) ----------

def test_quantity_digit_misread_flagged():
    # The 09.jpeg case: "3ลัง" read as 30. Line amount and bill total still
    # agree (both read off the paper), so only the หน่วยละ column catches it.
    items = [_item(quantity=30, unit_price=644, amount=1932)]
    w = validate_extraction(_result(items, validation_total=1932))
    assert any("น่าจะเป็น 3" in m for m in w)


def test_quantity_matching_unit_price_ok():
    items = [_item(quantity=3, unit_price=644, amount=1932)]
    assert not any("น่าจะเป็น" in m for m in validate_extraction(_result(items)))


def test_quantity_check_skipped_without_unit_price():
    items = [_item(quantity=30, unit_price=None, amount=1932)]
    assert not any("น่าจะเป็น" in m for m in validate_extraction(_result(items)))


def test_quantity_check_skipped_when_division_is_fractional():
    # 1932 / 700 = 2.76 — we misread the price, not the quantity. Stay quiet.
    items = [_item(quantity=3, unit_price=700, amount=1932)]
    assert not any("น่าจะเป็น" in m for m in validate_extraction(_result(items)))


def test_quantity_rounding_within_tolerance_ok():
    # 1,930 charged on 3 x 644 (satang knocked off) must not trip the guard.
    items = [_item(quantity=3, unit_price=644, amount=1930)]
    assert not any("น่าจะเป็น" in m for m in validate_extraction(_result(items)))


def test_pack_size_annotation_not_treated_as_price():
    # "1 ลัง @12" — 12 is bottles per case, not baht. 12,960/12 = 1,080 is a
    # 135x gap: no digit misread looks like that, so distrust the price.
    items = [_item(quantity=8, unit_price=12, amount=12960)]
    assert not any("น่าจะเป็น" in m for m in validate_extraction(_result(items)))


def test_quantity_warning_names_product_and_hides_price():
    items = [_item(quantity=30, unit_price=644, amount=1932)]
    w = [m for m in validate_extraction(_result(items)) if "น่าจะเป็น" in m]
    assert w and "เบียร์สิงห์ขวดใหญ่" in w[0]
    assert "644" not in w[0] and "1932" not in w[0] and "1,932" not in w[0]


# ---------- semantic dedup (#2) ----------

def test_duplicate_receipt_flagged(db_session):
    db_session.add(Document(id="d1", filename="a.jpg", file_path="/tmp/a", file_hash="h1",
                            status="extracted", merchant_normalized="รวยสุรา",
                            document_number="OCP-001"))
    db_session.flush()
    new = Document(id="d2", filename="b.jpg", file_path="/tmp/b", file_hash="h2",
                   status="extracted", merchant_normalized="รวยสุรา", document_number="OCP-001")
    db_session.add(new); db_session.flush()
    assert check_duplicate_receipt(db_session, new) is not None


def test_different_docnumber_not_duplicate(db_session):
    db_session.add(Document(id="d3", filename="a.jpg", file_path="/tmp/a", file_hash="h1",
                            status="extracted", merchant_normalized="รวยสุรา",
                            document_number="OCP-001"))
    db_session.flush()
    new = Document(id="d4", filename="b.jpg", file_path="/tmp/b", file_hash="h2",
                   status="extracted", merchant_normalized="รวยสุรา", document_number="OCP-002")
    db_session.add(new); db_session.flush()
    assert check_duplicate_receipt(db_session, new) is None


def test_no_docnumber_no_dedup(db_session):
    new = Document(id="d5", filename="b.jpg", file_path="/tmp/b", file_hash="h2",
                   status="extracted", merchant_normalized="รวยสุรา", document_number=None)
    db_session.add(new); db_session.flush()
    assert check_duplicate_receipt(db_session, new) is None


# ---------- store-match confidence (#5/#4 surfacing) ----------

def test_exact_store_match_not_flagged(db_session):
    db_session.add(Store(id="s1", name="สุดาพาณิชย์", normalized_name="สุดาพาณิชย์",
                         code="ST1", active=True))
    db_session.flush()
    doc = Document(id="d6", filename="x.jpg", file_path="/tmp/x", file_hash="h3",
                   status="extracted", merchant_normalized="สุดาพาณิชย์")
    assert check_store_match_confidence(db_session, doc) is None


def test_fuzzy_store_match_flagged(db_session):
    db_session.add(Store(id="s2", name="ก.เจริญพาณิชย์",
                         normalized_name="ก.เจริญพาณิชย์", code="ST2", active=True))
    db_session.flush()
    # A typo'd merchant that fuzzy-matches at ~93 (in the [88,96) confirm band)
    doc = Document(id="d7", filename="x.jpg", file_path="/tmp/x", file_hash="h4",
                   status="extracted", merchant_normalized="ก.เจริญพานิชย์")
    msg = check_store_match_confidence(db_session, doc)
    assert msg is not None and "ยืนยันว่าถูกร้าน" in msg
