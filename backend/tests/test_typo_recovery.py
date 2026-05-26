"""Tests for the typo_recovery_event path inside _resolve_product_code.

Trigger: Gemini emits a ``product_code`` that doesn't exist in the catalog,
*but* the normalized name is an exact canonical match. Trust the name,
recover the right code, and log the recovery so admins can spot recurring
mis-typing patterns (those usually warrant a SYSTEM_INSTRUCTION hint).
"""

from app.models import Product, TypoRecoveryEvent
from app.routers.documents import _resolve_product_code
from app.schemas import DocumentItemBase
from app.services.catalog import invalidate_cache


def _seed_product(db, code: str, canonical: str, display: str | None = None) -> None:
    db.add(
        Product(
            code=code,
            canonical_name=canonical,
            display_name=display or canonical,
            manufacturer="Boonrawd",
            category="เครื่องดื่ม",
            active=True,
        )
    )
    db.commit()
    # Module-level catalog caches persist across tests; clear so the freshly
    # seeded product is visible to ``is_canonical_name`` / ``find_code_by_name``.
    invalidate_cache()


class TestTypoRecovery:
    def test_typo_in_code_recovered_via_name(self, db_session):
        """LLM hallucinated a code that doesn't exist, but the name is a
        canonical match → recover the real code + log the event."""
        _seed_product(db_session, "SNG-320-BTL", "สิงห์ ขวด 320")

        item = DocumentItemBase(
            product_name_raw="สิงห์ ขวด 320",
            product_name_normalized="สิงห์ ขวด 320",
            product_code="SNG-320-BTLZ",  # extra Z = typo
            category="เครื่องดื่ม",
        )
        result = _resolve_product_code(db_session, item, document_id="doc-typo")
        db_session.commit()

        assert result == "SNG-320-BTL"  # recovered
        events = db_session.query(TypoRecoveryEvent).all()
        assert len(events) == 1
        assert events[0].emitted_code == "SNG-320-BTLZ"
        assert events[0].recovered_code == "SNG-320-BTL"
        assert events[0].product_name == "สิงห์ ขวด 320"
        assert events[0].document_id == "doc-typo"

    def test_invalid_code_and_invalid_name_no_recovery(self, db_session):
        """LLM emits a bad code AND a name that's not a canonical match →
        falls through to the catalog-gap path (not recovery)."""
        _seed_product(db_session, "SNG-320-BTL", "สิงห์ ขวด 320")

        item = DocumentItemBase(
            product_name_raw="ของแปลกที่ไม่มีใน catalog",
            product_name_normalized="ของแปลกที่ไม่มีใน catalog",
            product_code="MADE-UP-CODE",
            category="เครื่องดื่ม",
        )
        result = _resolve_product_code(db_session, item, document_id="doc-gap")
        db_session.commit()

        assert result is None
        # No typo_recovery_event because the name wasn't a canonical match.
        assert db_session.query(TypoRecoveryEvent).count() == 0

    def test_valid_code_no_recovery_event(self, db_session):
        """When the emitted code is already valid, we trust it and don't
        log a recovery event."""
        _seed_product(db_session, "SNG-320-BTL", "สิงห์ ขวด 320")

        item = DocumentItemBase(
            product_name_raw="สิงห์ ขวด 320",
            product_name_normalized="สิงห์ ขวด 320",
            product_code="SNG-320-BTL",  # correct
            category="เครื่องดื่ม",
        )
        result = _resolve_product_code(db_session, item, document_id="doc-clean")
        db_session.commit()

        assert result == "SNG-320-BTL"
        assert db_session.query(TypoRecoveryEvent).count() == 0
