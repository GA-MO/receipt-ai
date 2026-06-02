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

    def test_name_derived_from_code_when_only_raw_and_code_present(self, monkeypatch):
        """The new prompt asks Gemini to emit only product_name_raw + product_code;
        the parser must derive product_name_normalized from the catalog.
        """
        from app.services import catalog

        monkeypatch.setattr(
            catalog,
            "name_by_code",
            lambda code: "เบียร์สิงห์ขวดใหญ่" if code == "INT-BEER-SINGHA-L" else None,
        )
        payload = {
            "items": [
                {
                    "product_name_raw": "สห์ใหญ่",
                    "product_code": "INT-BEER-SINGHA-L",
                    "category": "เครื่องดื่ม",
                    "quantity": 12,
                    "unit": "ขวด",
                },
                {
                    # Competitor: no code → display falls back to raw
                    "product_name_raw": "น้ำคริสตัล แพ็ค",
                    "product_code": None,
                    "category": "เครื่องดื่ม",
                    "quantity": 1,
                    "unit": "แพ็ค",
                },
            ],
        }
        items = parse_extraction_payload(payload).items
        assert items[0].product_name_raw == "สห์ใหญ่"
        assert items[0].product_name_normalized == "เบียร์สิงห์ขวดใหญ่"
        assert items[0].product_code == "INT-BEER-SINGHA-L"
        assert items[1].product_name_raw == "น้ำคริสตัล แพ็ค"
        assert items[1].product_name_normalized == "น้ำคริสตัล แพ็ค"
        assert items[1].product_code is None

    def test_product_code_overrides_inconsistent_normalized_name(self, monkeypatch):
        """When the LLM emits a (code, name) pair that disagree, the SKU code
        wins and product_name_normalized is rewritten from the catalog. Guards
        against the failure mode where raw 'สิงห์' got code INT-BEER-SINGHA-L
        but normalized 'น้ำสิงห์เพ็ท 600ml'."""
        from app.services import catalog

        monkeypatch.setattr(
            catalog,
            "name_by_code",
            lambda code: "เบียร์สิงห์ขวดใหญ่" if code == "INT-BEER-SINGHA-L" else None,
        )
        payload = {
            "items": [
                {
                    "product_name_raw": "สิงห์",
                    "product_name_normalized": "น้ำสิงห์เพ็ท 600ml",
                    "product_code": "INT-BEER-SINGHA-L",
                    "category": "เครื่องดื่ม",
                    "quantity": 1,
                },
            ],
        }
        item = parse_extraction_payload(payload).items[0]
        assert item.product_code == "INT-BEER-SINGHA-L"
        assert item.product_name_normalized == "เบียร์สิงห์ขวดใหญ่"
        assert item.product_name_raw == "สิงห์"

    def test_catalog_selling_unit_overrides_model_unit(self, monkeypatch):
        """The shop sells by ลัง/ถาด/แพ็ค, never a single ขวด. A catalog match
        must take its unit from the SKU's selling unit, overriding whatever the
        model guessed; the quantity is left untouched. Off-catalog items keep
        the extracted unit."""
        from app.services import catalog

        monkeypatch.setattr(
            catalog,
            "name_by_code",
            lambda code: "เบียร์สิงห์ขวดใหญ่" if code == "INT-BEER-SINGHA-L" else None,
        )
        monkeypatch.setattr(
            catalog,
            "selling_unit_by_code",
            lambda code: "ลัง" if code == "INT-BEER-SINGHA-L" else None,
        )
        payload = {
            "items": [
                {
                    "product_name_raw": "เบียร์สิงห์",
                    "product_code": "INT-BEER-SINGHA-L",
                    "category": "เครื่องดื่ม",
                    "quantity": 120,
                    "unit": "ขวด",  # model mislabel — must be overridden
                },
                {
                    "product_name_raw": "น้ำคริสตัล แพ็ค",
                    "product_code": None,
                    "category": "เครื่องดื่ม",
                    "quantity": 1,
                    "unit": "แพ็ค",  # off-catalog — kept as-is
                },
            ],
        }
        items = parse_extraction_payload(payload).items
        assert items[0].unit == "ลัง"
        assert items[0].quantity == 120  # quantity untouched
        assert items[1].unit == "แพ็ค"

    def test_derive_selling_unit_rules(self):
        """Selling unit derivation: explicit pack clause wins; beverages with a
        volume-only size fall back to the case unit; volume tokens are ignored."""
        from app.models import Product
        from app.services.catalog import _derive_selling_unit

        def mk(**kw):
            return Product(**kw)

        # explicit "จำนวน 1 X" wins even when a volume "1 ล." precedes it
        assert _derive_selling_unit(mk(size="1 ล. x 12 ขวด / จำนวน 1 ลัง")) == "ลัง"
        assert _derive_selling_unit(mk(size="325 มล. x 24 ขวด / จำนวน 1 ถาด")) == "ถาด"
        assert _derive_selling_unit(mk(size="1 แพ็ก")) == "แพ็ค"
        assert _derive_selling_unit(mk(size="1 ชิ้น")) == "ชิ้น"
        # beer with volume-only size → case unit from the name
        assert _derive_selling_unit(mk(size="630ml", canonical_name="เบียร์สิงห์ขวดใหญ่")) == "ลัง"
        assert _derive_selling_unit(mk(size="700ml", sub_category="วิสกี้", canonical_name="จอห์นนี่ฯ")) == "ลัง"
        # genuine single-bottle non-beverage → no override
        assert _derive_selling_unit(mk(size="350 มล. / จำนวน 1 ขวด", canonical_name="ซอสพริก")) is None
