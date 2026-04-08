"""Tests for app.services.validation.validate_extraction."""

from app.schemas import DocumentItemBase, ExtractionResult
from app.services.validation import validate_extraction


def _make_item(**overrides) -> DocumentItemBase:
    defaults = {
        "product_name_raw": "สินค้า A",
        "quantity": 2,
        "unit": "ชิ้น",
        "unit_price": 50.0,
        "line_total": 100.0,
    }
    defaults.update(overrides)
    return DocumentItemBase(**defaults)


def _make_result(**overrides) -> ExtractionResult:
    defaults = {
        "merchant_name": "ร้านทดสอบ",
        "document_number": "INV-001",
        "document_date": "2025-04-03",
        "items": [_make_item()],
        "subtotal": 100.0,
        "discount": 0.0,
        "vat": 7.0,
        "grand_total": 107.0,
        "confidence": 0.95,
        "notes": None,
        "needs_review_fields": [],
    }
    defaults.update(overrides)
    return ExtractionResult(**defaults)


class TestValidateExtraction:
    """Validate the business-rule checker."""

    def test_valid_data_no_warnings(self):
        result = _make_result()
        warnings = validate_extraction(result)
        assert warnings == []

    def test_missing_merchant_name(self):
        result = _make_result(merchant_name=None)
        warnings = validate_extraction(result)
        assert any("ไม่พบชื่อร้านค้า" in w for w in warnings)

    def test_missing_items(self):
        result = _make_result(items=[], grand_total=100.0)
        warnings = validate_extraction(result)
        assert any("ไม่พบรายการสินค้า" in w for w in warnings)

    def test_missing_grand_total(self):
        result = _make_result(grand_total=None)
        warnings = validate_extraction(result)
        assert any("ไม่พบยอดรวมสุทธิ" in w for w in warnings)

    def test_wrong_totals(self):
        """Items sum to 100 but grand_total/subtotal is 200 -- should warn."""
        result = _make_result(
            items=[_make_item(line_total=100.0)],
            subtotal=200.0,
            grand_total=200.0,
        )
        warnings = validate_extraction(result)
        assert any("ยอดรวมรายการสินค้าไม่ตรง" in w for w in warnings)

    def test_totals_within_tolerance(self):
        """Difference <= 1.0 should NOT trigger a warning."""
        result = _make_result(
            items=[_make_item(line_total=100.0)],
            subtotal=100.5,
            grand_total=107.5,
        )
        warnings = validate_extraction(result)
        assert not any("ยอดรวมรายการสินค้าไม่ตรง" in w for w in warnings)

    def test_invalid_date_buddhist_era(self):
        """Year > 2500 is likely still Buddhist Era."""
        result = _make_result(document_date="2569-04-03")
        warnings = validate_extraction(result)
        assert any("พ.ศ." in w for w in warnings)

    def test_valid_date_no_warning(self):
        result = _make_result(document_date="2025-04-03")
        warnings = validate_extraction(result)
        assert not any("พ.ศ." in w for w in warnings)

    def test_malformed_date(self):
        result = _make_result(document_date="not-a-date")
        warnings = validate_extraction(result)
        assert any("รูปแบบวันที่" in w for w in warnings)

    def test_vat_mismatch(self):
        """VAT should be ~7% of subtotal; a large discrepancy warns."""
        result = _make_result(
            subtotal=1000.0,
            vat=100.0,  # 10% instead of 7%
            grand_total=1100.0,
            items=[_make_item(line_total=1000.0)],
        )
        warnings = validate_extraction(result)
        assert any("VAT" in w for w in warnings)

    def test_vat_correct(self):
        """VAT at exactly 7% should not warn."""
        result = _make_result(
            subtotal=1000.0,
            vat=70.0,
            grand_total=1070.0,
            items=[_make_item(line_total=1000.0)],
        )
        warnings = validate_extraction(result)
        assert not any("VAT" in w for w in warnings)

    def test_item_missing_product_name(self):
        item = _make_item(product_name_raw=None)
        result = _make_result(items=[item])
        warnings = validate_extraction(result)
        assert any("ไม่มีชื่อสินค้า" in w for w in warnings)

    def test_item_invalid_quantity(self):
        item = _make_item(quantity=0)
        result = _make_result(items=[item])
        warnings = validate_extraction(result)
        assert any("จำนวนสินค้าไม่ถูกต้อง" in w for w in warnings)

    def test_item_null_quantity(self):
        item = _make_item(quantity=None)
        result = _make_result(items=[item])
        warnings = validate_extraction(result)
        assert any("จำนวนสินค้าไม่ถูกต้อง" in w for w in warnings)
