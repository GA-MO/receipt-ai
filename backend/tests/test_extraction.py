"""Tests for app.services.extraction.parse_extraction_payload.

Covers the edge cases Gemini sometimes produces: array-instead-of-object,
nested item lists, invalid categories, and missing fields.
"""

from app.services.extraction import PRODUCT_CATEGORIES, parse_extraction_payload


class TestParseExtractionPayload:
    def test_happy_path(self):
        payload = {
            "merchant_name": "ร้านสมชาย",
            "merchant_normalized": "สมชาย",
            "document_number": "INV-001",
            "document_date": "2026-04-01",
            "category": "เครื่องดื่ม",
            "items": [
                {
                    "product_name_normalized": "เบียร์สิงห์ขวดใหญ่",
                    "category": "เครื่องดื่ม",
                    "quantity": 2,
                    "unit": "ขวด",
                },
            ],
            "confidence": 0.95,
        }
        result = parse_extraction_payload(payload)
        assert result.merchant_name == "ร้านสมชาย"
        assert result.merchant_normalized == "สมชาย"
        assert result.category == "เครื่องดื่ม"
        assert len(result.items) == 1
        assert result.items[0].category == "เครื่องดื่ม"
        assert result.items[0].product_name_normalized == "เบียร์สิงห์ขวดใหญ่"

    def test_product_name_raw_falls_through_to_normalized(self):
        """If Gemini only sends product_name_raw, that value is used as normalized too."""
        payload = {
            "category": "เครื่องดื่ม",
            "items": [
                {"product_name_raw": "สห์ใหญ่", "category": "เครื่องดื่ม", "quantity": 1},
            ],
        }
        result = parse_extraction_payload(payload)
        assert result.items[0].product_name_raw == "สห์ใหญ่"
        assert result.items[0].product_name_normalized == "สห์ใหญ่"

    def test_legacy_category_is_remapped(self):
        """Pre-2026-04 categories (เบียร์/อาหาร/อื่นๆ/…) auto-remap to new taxonomy."""
        result = parse_extraction_payload({"category": "เบียร์", "items": []})
        assert result.category == "เครื่องดื่ม"
        result = parse_extraction_payload({"category": "อาหาร", "items": []})
        assert result.category == "อาหาร และของว่าง"
        result = parse_extraction_payload({"category": "อื่นๆ", "items": []})
        assert result.category == "สินค้าอื่นๆ"

    def test_array_response_takes_first_element(self):
        """Gemini sometimes returns a JSON array instead of an object."""
        payload = [
            {"merchant_name": "ร้าน A", "items": [], "category": "อาหาร และของว่าง"},
            {"merchant_name": "ร้าน B"},
        ]
        result = parse_extraction_payload(payload)
        assert result.merchant_name == "ร้าน A"
        assert result.category == "อาหาร และของว่าง"

    def test_empty_array_response_returns_empty_result(self):
        result = parse_extraction_payload([])
        assert result.merchant_name is None
        assert result.items == []
        assert result.category == "สินค้าอื่นๆ"

    def test_nested_item_list(self):
        """Gemini sometimes wraps items in an outer list: items = [[…]]."""
        payload = {
            "category": "เครื่องดื่ม",
            "items": [
                [
                    {"product_name_normalized": "A", "quantity": 1},
                    {"product_name_normalized": "B", "quantity": 2},
                ]
            ],
        }
        result = parse_extraction_payload(payload)
        assert [i.product_name_normalized for i in result.items] == ["A", "B"]

    def test_invalid_category_falls_back_to_other(self):
        payload = {"category": "หมวดแปลกๆ", "items": []}
        result = parse_extraction_payload(payload)
        assert result.category == "สินค้าอื่นๆ"

    def test_all_categories_are_accepted(self):
        for cat in PRODUCT_CATEGORIES:
            payload = {"category": cat, "items": []}
            assert parse_extraction_payload(payload).category == cat

    def test_item_category_defaults_to_document_category(self):
        """Items missing ``category`` inherit the document category."""
        payload = {
            "category": "เครื่องดื่ม",
            "items": [
                {"product_name_normalized": "A", "quantity": 1},  # no category
                {"product_name_normalized": "B", "quantity": 1, "category": "อาหาร และของว่าง"},
                {"product_name_normalized": "C", "quantity": 1, "category": "BOGUS"},
            ],
        }
        result = parse_extraction_payload(payload)
        assert result.items[0].category == "เครื่องดื่ม"
        assert result.items[1].category == "อาหาร และของว่าง"
        # BOGUS is not in the allowed list → falls back to document category
        assert result.items[2].category == "เครื่องดื่ม"

    def test_non_dict_items_are_skipped(self):
        payload = {
            "items": [
                {"product_name_normalized": "A", "quantity": 1},
                "garbage",
                None,
                42,
            ],
        }
        result = parse_extraction_payload(payload)
        assert len(result.items) == 1

    def test_missing_all_fields(self):
        result = parse_extraction_payload({})
        assert result.merchant_name is None
        assert result.items == []
        assert result.confidence == 0.0
