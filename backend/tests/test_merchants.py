"""Tests for app.services.merchants normalization + fuzzy clustering."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Store
from app.services.merchants import _rule_based_clean, normalize_merchant


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _add_store(session, name: str, normalized: str, active: bool = True) -> Store:
    """Seed an active Store master row. Merchant clustering keys off this."""
    store = Store(name=name, normalized_name=normalized, active=active)
    session.add(store)
    session.commit()
    return store


def _add_doc(session, merchant_name: str, normalized: str) -> None:
    """Legacy alias retained for tests that intent to assert clustering;
    rewritten to seed a Store master row instead of a Document so it matches
    the new ``_load_known_canonicals`` source."""
    _add_store(session, merchant_name, normalized)


class TestRuleBasedClean:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("บริษัท ก.เจริญ พาณิชย์ จำกัด", "ก.เจริญ พาณิชย์"),
            ("ร้าน ลุงหมู ของชำ", "ลุงหมู ของชำ"),
            ("หจก. สมชาย เทรดดิ้ง", "สมชาย เทรดดิ้ง"),
            ("บจก. เอบีซี จำกัด", "เอบีซี"),
            ("7-Eleven สาขาสุขุมวิท 101", "7-Eleven"),
            ("  พี่ทุย  ", "พี่ทุย"),
            # Head-office markers in parentheses must be stripped, even when
            # glued together with "จำกัด" without a space.
            ("บริษัท มิตรราชบุรีเทรดดิ้ง จำกัด(สำนักงานใหญ่)", "มิตรราชบุรีเทรดดิ้ง"),
            ("บริษัท เอบีซี จำกัด (สำนักงานใหญ่)", "เอบีซี"),
            ("บริษัท เอบีซี จำกัด (สนญ.)", "เอบีซี"),
            ("Acme Corp. (HQ)", "Acme"),
            ("Acme Inc.", "Acme"),
            # Plain "สำนักงานใหญ่" without parentheses
            ("บริษัท เอบีซี จำกัด สำนักงานใหญ่", "เอบีซี"),
            # Public company marker — trailing period is canonicalized off so
            # "ปตท." and "ปตท" map to the same canonical.
            ("บริษัท ปตท. จำกัด (มหาชน)", "ปตท"),
            # Romanised (English) form in trailing parens — receipts often print
            # both the Thai name and an English translation. Strip the
            # romanisation so it doesn't skew token_set_ratio.
            ("จำปิสโตร์ (Jampi Store)", "จำปิสโตร์"),
            ("จำปิสโตร์(Jampi Store)", "จำปิสโตร์"),
            ("ร้านสมศักดิ์ (Somsak Shop)", "สมศักดิ์"),
            # Thai-content parens are preserved — they may disambiguate
            # genuinely different stores (e.g. branch markers, old vs new).
            ("ร้านโจ (เก่า)", "โจ (เก่า)"),
            # Branch markers with opening paren should leave nothing dangling.
            ("ร้านโจ (สาขา 2)", "โจ"),
        ],
    )
    def test_strips_common_thai_prefixes_and_suffixes(self, raw, expected):
        assert _rule_based_clean(raw) == expected


class TestNormalizeMerchant:
    def test_returns_none_for_all_empty(self, db):
        assert normalize_merchant(None, None, db) is None

    def test_uses_llm_hint_when_provided(self, db):
        result = normalize_merchant(
            raw_name="ร้าน ก.เจริญ",
            llm_hint="ก.เจริญ พาณิชย์",
            db=db,
        )
        assert result == "ก.เจริญ พาณิชย์"

    def test_cleans_llm_hint_with_residual_noise(self, db):
        """LLM sometimes forgets to strip 'จำกัด(สำนักงานใหญ่)'. We must still clean it."""
        result = normalize_merchant(
            raw_name="บริษัท มิตรราชบุรีเทรดดิ้ง จำกัด(สำนักงานใหญ่)",
            llm_hint="มิตรราชบุรีเทรดดิ้ง จำกัด(สำนักงานใหญ่)",
            db=db,
        )
        assert result == "มิตรราชบุรีเทรดดิ้ง"

    def test_falls_back_to_rule_cleaning(self, db):
        result = normalize_merchant(
            raw_name="บริษัท สมชาย จำกัด",
            llm_hint=None,
            db=db,
        )
        assert result == "สมชาย"

    def test_fuzzy_matches_existing_canonical(self, db):
        _add_doc(db, "ร้าน สมชาย ของชำ", "สมชาย ของชำ")

        # Same store written with a company prefix should cluster to the canonical.
        result = normalize_merchant(
            raw_name="บริษัท สมชาย ของชำ จำกัด",
            llm_hint=None,
            db=db,
        )
        assert result == "สมชาย ของชำ"

    def test_fuzzy_matches_through_romanised_parens(self, db):
        """LLM-emitted name with English translation in parens should still
        cluster to the existing canonical."""
        _add_store(db, "จำปีสโตร์", "จำปีสโตร์")

        # 'จำปิสโตร์ (Jampi Store)' (one-char typo + romanisation) should
        # collapse to the existing 'จำปีสโตร์' after stripping the parens.
        result = normalize_merchant(
            raw_name="จำปิสโตร์ (Jampi Store)",
            llm_hint=None,
            db=db,
        )
        assert result == "จำปีสโตร์"

    def test_inactive_store_does_not_influence_clustering(self, db):
        """Soft-deleted (active=False) stores must NOT pull future merchants
        toward their old names. Store master is the single source of truth.

        Regression for: admin deletes a duplicate store ("จำปิสโตร์ (Jampi Store)")
        but its merchant string keeps clustering future docs to it because
        clustering used Document.merchant_normalized history instead of
        active Store master.
        """
        _add_store(db, "จำปีสโตร์", "จำปีสโตร์")
        _add_store(db, "จำปิสโตร์ (Jampi Store)", "จำปิสโตร์", active=False)

        # A new doc reads almost-identical name to the deleted store. Without
        # the fix, it would match the inactive store's canonical and "resurrect"
        # the duplicate identity. With the fix, it must fall to the active
        # 'จำปีสโตร์'.
        result = normalize_merchant(
            raw_name="จำปิสโตร์",
            llm_hint=None,
            db=db,
        )
        assert result == "จำปีสโตร์"

    def test_no_clustering_when_only_inactive_stores_present(self, db):
        """If every candidate Store is inactive, clustering must return the
        cleaned candidate as-is — never a stale inactive name."""
        _add_store(db, "Old Shop", "Old Shop", active=False)

        result = normalize_merchant(
            raw_name="ร้านโอลด์ ชอป",
            llm_hint=None,
            db=db,
        )
        # No active stores → just returns the rule-cleaned candidate.
        assert result == "โอลด์ ชอป"

    def test_fuzzy_matches_with_extra_branch_suffix(self, db):
        _add_doc(db, "ร้านสมชาย", "สมชาย")

        # Same store but written with a branch suffix → same canonical.
        result = normalize_merchant(
            raw_name="ร้านสมชาย สาขา 2",
            llm_hint=None,
            db=db,
        )
        assert result == "สมชาย"

    def test_does_not_match_unrelated_merchants(self, db):
        _add_doc(db, "7-Eleven", "7-Eleven")
        result = normalize_merchant(
            raw_name="Family Mart",
            llm_hint="Family Mart",
            db=db,
        )
        # Completely different name -> shouldn't match above threshold
        assert result == "Family Mart"
