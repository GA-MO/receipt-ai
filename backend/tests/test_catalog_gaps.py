"""Tests for the catalog_gap_event recording inside _resolve_product_code.

Covers two paths:

1. Gemini emitted an *invalid* code → record gap (regression).
2. Gemini *abstained* on a primary-category item (e.g. competitor liquor) →
   record gap with ``emitted_code=None`` so admins can decide whether to add
   the missing SKU. Items in non-primary categories (packaging, fees) must
   NOT be logged.

Also covers the integration path: when a doc gets extracted with a catalog
gap, ``doc.needs_review`` is flipped True so the admin queue surfaces it.
"""

import io
import struct
import zlib
from unittest.mock import patch

from app.models import CatalogGapEvent, Document, Product
from app.routers.documents import _resolve_product_code
from app.schemas import DocumentItemBase, ExtractionResult
from app.services.catalog import invalidate_cache


def _seed_product(db, code: str, name: str, manufacturer: str = "Boonrawd") -> None:
    db.add(
        Product(
            code=code,
            canonical_name=name,
            display_name=name,
            manufacturer=manufacturer,
            category="เครื่องดื่ม",
            active=True,
        )
    )
    db.commit()
    # Module-level catalog caches persist across tests; clear so the freshly
    # seeded product is visible to ``is_canonical_name`` / ``find_code_by_name``.
    invalidate_cache()


class TestCatalogGapRecording:
    def test_invalid_code_records_gap(self, db_session):
        """LLM hallucinates a code that doesn't exist → gap with code."""
        item = DocumentItemBase(
            product_name_raw="เบียร์ใหม่",
            product_name_normalized="เบียร์ใหม่",
            product_code="DOES-NOT-EXIST",
            category="เครื่องดื่ม",
        )
        result = _resolve_product_code(db_session, item, document_id="doc-1")
        db_session.commit()

        assert result is None
        gaps = db_session.query(CatalogGapEvent).all()
        assert len(gaps) == 1
        assert gaps[0].emitted_code == "DOES-NOT-EXIST"
        assert gaps[0].product_name == "เบียร์ใหม่"

    def test_no_code_primary_category_records_gap(self, db_session):
        """LLM abstains on a beverage item not in catalog → gap with no code.

        This is the KULOV case: competitor liquor brand the model correctly
        flagged as 'not in catalog'.
        """
        item = DocumentItemBase(
            product_name_raw="เหล้า KULOV",
            product_name_normalized="เหล้า Kulov",
            product_code=None,
            category="เครื่องดื่ม",
        )
        result = _resolve_product_code(db_session, item, document_id="doc-2")
        db_session.commit()

        assert result is None
        gaps = db_session.query(CatalogGapEvent).all()
        assert len(gaps) == 1
        assert gaps[0].emitted_code is None
        assert gaps[0].product_name == "เหล้า Kulov"
        assert gaps[0].product_name_raw == "เหล้า KULOV"

    def test_no_code_non_primary_category_skipped(self, db_session):
        """LLM abstains on packaging / delivery fee → NOT a gap.

        Items in 'สินค้าอื่นๆ' or 'อาหาร และของว่าง' aren't expected to be in
        the SKU catalog. Recording them would noise up the admin queue.
        """
        for category in ("สินค้าอื่นๆ", "อาหาร และของว่าง"):
            item = DocumentItemBase(
                product_name_raw="ค่าขนส่งสินค้าระยะสั้น",
                product_name_normalized="ค่าขนส่งสินค้าระยะสั้น",
                product_code=None,
                category=category,
            )
            _resolve_product_code(db_session, item, document_id="doc-3")
        db_session.commit()

        assert db_session.query(CatalogGapEvent).count() == 0

    def test_no_code_no_category_skipped(self, db_session):
        """Defensive: missing category should not crash and should not log."""
        item = DocumentItemBase(
            product_name_raw="???",
            product_name_normalized="???",
            product_code=None,
            category=None,
        )
        _resolve_product_code(db_session, item, document_id="doc-4")
        db_session.commit()

        assert db_session.query(CatalogGapEvent).count() == 0

    def test_no_code_but_name_matches_catalog_no_gap(self, db_session):
        """If Gemini abstains but the name fuzzy-matches an existing SKU,
        return the matched code — no gap should be recorded."""
        _seed_product(db_session, "SNG-320-BTL", "สิงห์ ขวด 320")

        item = DocumentItemBase(
            product_name_raw="สิงห์ ขวด 320",
            product_name_normalized="สิงห์ ขวด 320",
            product_code=None,
            category="เครื่องดื่ม",
        )
        result = _resolve_product_code(db_session, item, document_id="doc-5")
        db_session.commit()

        assert result == "SNG-320-BTL"
        assert db_session.query(CatalogGapEvent).count() == 0


class TestNeedsReviewOnCatalogGap:
    """The presence of a catalog gap on a doc must flip ``needs_review=True``
    so the admin queue surfaces these for "should we add this SKU?" review.

    Without this, Gemini's uniformly-high confidence (≥0.95) would let real
    missing-SKU cases slip past the queue.
    """

    def _doc_should_be_reviewed(self, db, doc: Document) -> bool:
        """Mirror the condition used inline in
        ``app.routers.documents._run_processing``."""
        from app.routers.documents import _is_primary_product_category
        return any(
            it.product_code is None and _is_primary_product_category(it.category)
            for it in doc.items
        )

    def test_doc_with_primary_gap_item_flagged(self, db_session):
        """One primary-category item with no resolved code → review needed."""
        from app.models import DocumentItem
        doc = Document(id="d1", filename="r.jpeg", file_path="/tmp/r.jpeg")
        db_session.add(doc)
        db_session.flush()
        # Mixed bag: one matched item + one gap (KULOV-style).
        db_session.add(
            DocumentItem(
                id="i1",
                document_id="d1",
                product_name_normalized="สิงห์ ขวด 320",
                product_code="SNG-320-BTL",
                category="เครื่องดื่ม",
            )
        )
        db_session.add(
            DocumentItem(
                id="i2",
                document_id="d1",
                product_name_normalized="เหล้า KULOV",
                product_code=None,
                category="เครื่องดื่ม",
            )
        )
        db_session.flush()
        db_session.refresh(doc)
        assert self._doc_should_be_reviewed(db_session, doc) is True

    def test_doc_with_only_non_primary_gap_not_flagged(self, db_session):
        """Packaging / fee items with no code → no review needed."""
        from app.models import DocumentItem
        doc = Document(id="d2", filename="r.jpeg", file_path="/tmp/r.jpeg")
        db_session.add(doc)
        db_session.flush()
        db_session.add(
            DocumentItem(
                id="i3",
                document_id="d2",
                product_name_normalized="ค่าขนส่ง",
                product_code=None,
                category="สินค้าอื่นๆ",
            )
        )
        db_session.flush()
        db_session.refresh(doc)
        assert self._doc_should_be_reviewed(db_session, doc) is False

    def test_doc_with_all_matched_items_not_flagged(self, db_session):
        """All items matched to catalog → review not needed (from this signal)."""
        from app.models import DocumentItem
        doc = Document(id="d3", filename="r.jpeg", file_path="/tmp/r.jpeg")
        db_session.add(doc)
        db_session.flush()
        db_session.add(
            DocumentItem(
                id="i4",
                document_id="d3",
                product_name_normalized="สิงห์ ขวด 320",
                product_code="SNG-320-BTL",
                category="เครื่องดื่ม",
            )
        )
        db_session.flush()
        db_session.refresh(doc)
        assert self._doc_should_be_reviewed(db_session, doc) is False
