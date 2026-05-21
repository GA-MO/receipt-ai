"""Tests for app.services.validation.validate_extraction.

Price-related checks were removed when the visit pivot dropped price/VAT
fields from the schema; only merchant + items + date sanity remain.
"""

from app.schemas import DocumentItemBase, ExtractionResult
from app.services.validation import validate_extraction


def _make_item(**overrides):
    base = {
        "product_name_normalized": "เบียร์สิงห์",
        "category": "เครื่องดื่ม",
        "quantity": 2,
        "unit": "ขวด",
    }
    base.update(overrides)
    return DocumentItemBase(**base)


def _make_result(**overrides):
    base = {
        "merchant_name": "ร้านสมชาย",
        "document_date": "2026-04-01",
        "category": "เครื่องดื่ม",
        "items": [_make_item()],
        "confidence": 0.95,
    }
    base.update(overrides)
    return ExtractionResult(**base)


class TestValidateExtraction:
    def test_happy_path_has_no_warnings(self):
        assert validate_extraction(_make_result()) == []

    def test_missing_merchant(self):
        result = _make_result(merchant_name=None)
        assert "ไม่พบชื่อร้านค้า" in validate_extraction(result)

    def test_missing_items(self):
        result = _make_result(items=[])
        assert "ไม่พบรายการสินค้า" in validate_extraction(result)

    def test_item_without_name(self):
        result = _make_result(items=[_make_item(product_name_normalized=None)])
        assert any("ไม่มีชื่อสินค้า" in w for w in validate_extraction(result))

    def test_item_with_zero_quantity(self):
        result = _make_result(items=[_make_item(quantity=0)])
        assert any("จำนวนสินค้าไม่ถูกต้อง" in w for w in validate_extraction(result))

    def test_unconverted_buddhist_year_is_flagged(self):
        result = _make_result(document_date="2568-04-01")
        warnings = validate_extraction(result)
        assert any("พ.ศ." in w for w in warnings)
