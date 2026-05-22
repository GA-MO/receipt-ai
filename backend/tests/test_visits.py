"""Tests for the Visit router + aggregate service."""

import io
import struct
import zlib
from unittest.mock import patch

import pytest

from app.models import Document, DocumentItem, Product, Store, Visit
from app.services.visit_aggregate import aggregate_visit
from app.services.visits import (
    check_period_mismatch,
    check_store_mismatch,
    ensure_visit_for_doc,
    get_or_create_visit_for_merchant,
    is_store_mismatch,
)


@pytest.fixture(autouse=True)
def _seed_default_stores(db_session):
    """Seed Store master rows for the merchant names used in these tests.

    Visit attachment now requires a matching Store, so without this fixture
    every legacy test that calls ``get_or_create_visit_for_merchant`` would
    get ``None`` back.
    """
    for name in ("ร้านA", "ร้านB", "ร้านX", "ร้านY"):
        db_session.add(
            Store(
                id=f"store-{name}",
                name=name,
                normalized_name=name,
                active=True,
            )
        )
    db_session.flush()


def _make_tiny_png() -> bytes:
    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = _chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
    iend = _chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _seed_doc(db, *, merchant_normalized="ร้านA", visit_id=None, items=None) -> Document:
    doc = Document(
        id=f"doc-{merchant_normalized}-{id(items)}",
        filename="r.png",
        file_path="/tmp/r.png",
        file_type="image",
        status="extracted",
        merchant_name=f"ร้าน {merchant_normalized}",
        merchant_normalized=merchant_normalized,
        document_date="2025-04-15",
        visit_id=visit_id,
    )
    db.add(doc)
    db.flush()
    for it in items or []:
        db.add(DocumentItem(document_id=doc.id, **it))
    db.flush()
    return doc


# ---------------------------------------------------------------------------
# Visit lifecycle helpers
# ---------------------------------------------------------------------------


class TestVisitHelpers:
    def test_get_or_create_visit_creates_new(self, db_session):
        v = get_or_create_visit_for_merchant(db_session, "ร้านA", report_period="2026-05", store_label="ร้าน A")
        assert v.id
        assert v.store_key == "ร้านA"
        assert v.store_label == "ร้าน A"

    def test_get_or_create_visit_reuses_existing(self, db_session):
        v1 = get_or_create_visit_for_merchant(db_session, "ร้านA", report_period="2026-05")
        v2 = get_or_create_visit_for_merchant(db_session, "ร้านA", report_period="2026-05")
        assert v1.id == v2.id

    def test_ensure_visit_for_doc_skips_when_no_merchant(self, db_session):
        doc = _seed_doc(db_session, merchant_normalized="")
        doc.merchant_normalized = None
        result = ensure_visit_for_doc(db_session, doc)
        assert result is None
        assert doc.visit_id is None

    def test_ensure_visit_for_doc_attaches(self, db_session):
        doc = _seed_doc(db_session, merchant_normalized="ร้านX")
        visit = ensure_visit_for_doc(db_session, doc)
        assert visit is not None
        assert doc.visit_id == visit.id


# ---------------------------------------------------------------------------
# Visit CRUD endpoints
# ---------------------------------------------------------------------------


class TestVisitsRouter:
    def test_create_visit(self, client):
        resp = client.post(
            "/api/visits",
            json={"store_label": "ร้านน้อย", "rep_name": "นาย เอ"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["store_label"] == "ร้านน้อย"
        assert data["rep_name"] == "นาย เอ"
        assert data["document_count"] == 0

    def test_list_visits_excludes_deleted(self, client):
        r = client.post("/api/visits", json={"store_label": "X"})
        visit_id = r.json()["id"]
        client.delete(f"/api/visits/{visit_id}")
        listing = client.get("/api/visits").json()
        assert all(v["id"] != visit_id for v in listing)

    def test_get_visit_404(self, client):
        resp = client.get("/api/visits/nope")
        assert resp.status_code == 404

    def test_patch_visit(self, client):
        r = client.post("/api/visits", json={"store_label": "X"})
        vid = r.json()["id"]
        resp = client.patch(f"/api/visits/{vid}", json={"rep_name": "B"})
        assert resp.status_code == 200
        assert resp.json()["rep_name"] == "B"

    def test_bulk_upload_creates_documents(self, client, db_session):
        v = client.post("/api/visits", json={"store_label": "X"}).json()
        png = _make_tiny_png()
        with patch("app.routers.documents._process_document"):
            resp = client.post(
                f"/api/visits/{v['id']}/documents",
                files=[
                    ("files", ("a.png", io.BytesIO(png), "image/png")),
                ],
            )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["document_ids"]) == 1
        # The doc must be attached to the visit.
        doc = db_session.query(Document).filter(Document.id == body["document_ids"][0]).first()
        assert doc.visit_id == v["id"]

    def test_bulk_upload_dedupes_existing_hashes(self, client):
        v = client.post("/api/visits", json={"store_label": "X"}).json()
        png = _make_tiny_png()
        with patch("app.routers.documents._process_document"):
            client.post(
                f"/api/visits/{v['id']}/documents",
                files=[("files", ("a.png", io.BytesIO(png), "image/png"))],
            )
            r2 = client.post(
                f"/api/visits/{v['id']}/documents",
                files=[("files", ("a.png", io.BytesIO(png), "image/png"))],
            )
        body = r2.json()
        assert body["document_ids"] == []
        assert len(body["duplicates"]) == 1


# ---------------------------------------------------------------------------
# Aggregate service
# ---------------------------------------------------------------------------


class TestAggregate:
    def test_empty_visit_returns_empty(self, db_session):
        v = get_or_create_visit_for_merchant(db_session, "ร้านA", report_period="2026-05")
        assert aggregate_visit(db_session, v.id) == []

    def test_groups_by_sku_across_docs(self, db_session):
        # Two docs in the same visit, both selling the same SKU.
        v = get_or_create_visit_for_merchant(db_session, "ร้านA", report_period="2026-05")
        _seed_doc(
            db_session,
            merchant_normalized="ร้านA",
            visit_id=v.id,
            items=[
                {
                    "product_code": "SKU1",
                    "product_name_normalized": "เบียร์สิงห์",
                    "quantity": 12,
                    "unit": "ขวด",
                }
            ],
        )
        _seed_doc(
            db_session,
            merchant_normalized="ร้านA",
            visit_id=v.id,
            items=[
                {
                    "product_code": "SKU1",
                    "product_name_normalized": "เบียร์สิงห์",
                    "quantity": 6,
                    "unit": "ขวด",
                }
            ],
        )
        rows = aggregate_visit(db_session, v.id)
        assert len(rows) == 1
        assert rows[0].product_code == "SKU1"
        assert rows[0].total_quantity == 18
        assert rows[0].source_count == 2
        assert rows[0].unit == "ขวด"
        assert rows[0].units_seen == ["ขวด"]

    def test_unknown_items_fallback_by_name(self, db_session):
        v = get_or_create_visit_for_merchant(db_session, "ร้านA", report_period="2026-05")
        _seed_doc(
            db_session,
            merchant_normalized="ร้านA",
            visit_id=v.id,
            items=[
                {
                    "product_code": None,
                    "product_name_normalized": "เบียร์ช้าง",
                    "quantity": 10,
                    "unit": "ขวด",
                }
            ],
        )
        _seed_doc(
            db_session,
            merchant_normalized="ร้านA",
            visit_id=v.id,
            items=[
                {
                    "product_code": None,
                    "product_name_normalized": "เบียร์ช้าง",
                    "quantity": 5,
                    "unit": "ขวด",
                }
            ],
        )
        rows = aggregate_visit(db_session, v.id)
        assert len(rows) == 1
        assert rows[0].product_code is None
        assert rows[0].is_catalog_match is False
        assert rows[0].total_quantity == 15

    def test_mixed_units_flagged(self, db_session):
        v = get_or_create_visit_for_merchant(db_session, "ร้านA", report_period="2026-05")
        _seed_doc(
            db_session,
            merchant_normalized="ร้านA",
            visit_id=v.id,
            items=[
                {
                    "product_code": None,
                    "product_name_normalized": "น้ำดื่ม",
                    "quantity": 2,
                    "unit": "ลัง",
                }
            ],
        )
        _seed_doc(
            db_session,
            merchant_normalized="ร้านA",
            visit_id=v.id,
            items=[
                {
                    "product_code": None,
                    "product_name_normalized": "น้ำดื่ม",
                    "quantity": 24,
                    "unit": "ขวด",
                }
            ],
        )
        rows = aggregate_visit(db_session, v.id)
        assert len(rows) == 1
        assert sorted(rows[0].units_seen) == ["ขวด", "ลัง"]

    def test_manufacturer_propagated_from_product(self, db_session):
        v = get_or_create_visit_for_merchant(db_session, "ร้านA", report_period="2026-05")
        db_session.add(
            Product(
                id="p1",
                code="SKU1",
                canonical_name="Beer Brand X",
                display_name="Brand X",
                manufacturer="Boonrawd",
                active=True,
            )
        )
        _seed_doc(
            db_session,
            merchant_normalized="ร้านA",
            visit_id=v.id,
            items=[
                {
                    "product_code": "SKU1",
                    "product_name_normalized": "X",
                    "quantity": 4,
                    "unit": "ขวด",
                }
            ],
        )
        rows = aggregate_visit(db_session, v.id)
        assert rows[0].manufacturer == "Boonrawd"
        assert rows[0].is_catalog_match is True
        assert rows[0].display_name == "Brand X"

    def test_date_filter(self, db_session):
        v = get_or_create_visit_for_merchant(db_session, "ร้านA", report_period="2026-05")
        d1 = _seed_doc(
            db_session,
            merchant_normalized="ร้านA",
            visit_id=v.id,
            items=[
                {
                    "product_code": None,
                    "product_name_normalized": "A",
                    "quantity": 1,
                    "unit": "ขวด",
                }
            ],
        )
        d1.document_date = "2025-01-01"
        d2 = _seed_doc(
            db_session,
            merchant_normalized="ร้านA",
            visit_id=v.id,
            items=[
                {
                    "product_code": None,
                    "product_name_normalized": "A",
                    "quantity": 7,
                    "unit": "ขวด",
                }
            ],
        )
        d2.document_date = "2025-04-15"
        db_session.flush()
        rows = aggregate_visit(
            db_session, v.id, date_from="2025-04-01", date_to="2025-04-30"
        )
        assert rows[0].total_quantity == 7


class TestReportPeriod:
    def test_create_visit_accepts_period(self, client):
        r = client.post(
            "/api/visits",
            json={"store_label": "X", "report_period": "2025-04"},
        )
        assert r.status_code == 200
        assert r.json()["report_period"] == "2025-04"

    def test_create_visit_rejects_invalid_period_silently(self, client):
        r = client.post(
            "/api/visits",
            json={"store_label": "X", "report_period": "not-a-period"},
        )
        # Invalid period is treated as None (not a hard error) so the legacy
        # /upload flow that doesn't supply one keeps working.
        assert r.status_code == 200
        assert r.json()["report_period"] is None

    def test_patch_visit_updates_period(self, client):
        v = client.post("/api/visits", json={"store_label": "X"}).json()
        r = client.patch(f"/api/visits/{v['id']}", json={"report_period": "2025-12"})
        assert r.status_code == 200
        assert r.json()["report_period"] == "2025-12"

    def test_check_period_mismatch_inside_period(self, db_session):
        v = Visit(id="v1", store_label="X", report_period="2025-04")
        db_session.add(v)
        db_session.flush()
        doc = Document(
            id="d1",
            filename="r.png",
            file_path="/tmp/r.png",
            file_type="image",
            status="extracted",
            document_date="2025-04-15",
            visit_id=v.id,
        )
        db_session.add(doc)
        db_session.flush()
        assert check_period_mismatch(doc) is None

    def test_check_period_mismatch_outside_period(self, db_session):
        v = Visit(id="v1", store_label="X", report_period="2025-04")
        db_session.add(v)
        db_session.flush()
        doc = Document(
            id="d1",
            filename="r.png",
            file_path="/tmp/r.png",
            file_type="image",
            status="extracted",
            document_date="2025-05-02",
            visit_id=v.id,
        )
        db_session.add(doc)
        db_session.flush()
        warning = check_period_mismatch(doc)
        assert warning is not None
        assert "นอกเดือน" in warning

    def test_create_visit_is_idempotent_on_store_and_period(self, client):
        s = client.post("/api/stores", json={"name": "ร้านลุง"}).json()
        v1 = client.post(
            "/api/visits",
            json={"store_id": s["id"], "report_period": "2025-04"},
        ).json()
        v2 = client.post(
            "/api/visits",
            json={"store_id": s["id"], "report_period": "2025-04"},
        ).json()
        # Returns the same Visit id rather than creating a duplicate.
        assert v1["id"] == v2["id"]

    def test_create_visit_different_periods_are_separate(self, client):
        s = client.post("/api/stores", json={"name": "ร้านลุง"}).json()
        v1 = client.post(
            "/api/visits",
            json={"store_id": s["id"], "report_period": "2025-04"},
        ).json()
        v2 = client.post(
            "/api/visits",
            json={"store_id": s["id"], "report_period": "2025-05"},
        ).json()
        assert v1["id"] != v2["id"]

    def test_visit_detail_marks_doc_period_mismatch(self, client, db_session):
        v = client.post(
            "/api/visits", json={"store_label": "X", "report_period": "2025-04"}
        ).json()
        # Seed one in-period doc and one out-of-period doc directly.
        for did, date in (("d1", "2025-04-10"), ("d2", "2025-05-01")):
            db_session.add(
                Document(
                    id=did,
                    filename=f"{did}.png",
                    file_path=f"/tmp/{did}.png",
                    file_type="image",
                    status="extracted",
                    document_date=date,
                    visit_id=v["id"],
                )
            )
        db_session.commit()
        detail = client.get(f"/api/visits/{v['id']}").json()
        by_id = {d["id"]: d for d in detail["documents"]}
        assert by_id["d1"]["period_mismatch"] is False
        assert by_id["d2"]["period_mismatch"] is True

    def test_is_store_mismatch_same_store(self, db_session):
        v = Visit(id="v1", store_label="ร้านA", store_key="ร้านA")
        db_session.add(v)
        db_session.flush()
        doc = _seed_doc(db_session, merchant_normalized="ร้านA", visit_id=v.id)
        assert is_store_mismatch(doc) is False
        assert check_store_mismatch(doc) is None

    def test_is_store_mismatch_different_store(self, db_session):
        v = Visit(id="v1", store_label="ร้านA", store_key="ร้านA")
        db_session.add(v)
        db_session.flush()
        doc = _seed_doc(db_session, merchant_normalized="ร้านB", visit_id=v.id)
        assert is_store_mismatch(doc) is True
        warning = check_store_mismatch(doc)
        assert warning is not None
        assert "คนละ" in warning or "ร้าน" in warning

    def test_is_store_mismatch_missing_data_is_false(self, db_session):
        v = Visit(id="v1", store_label="ร้านA", store_key=None)
        db_session.add(v)
        db_session.flush()
        doc = _seed_doc(db_session, merchant_normalized="ร้านA", visit_id=v.id)
        assert is_store_mismatch(doc) is False

    def test_visit_detail_marks_doc_store_mismatch(self, client, db_session):
        s = client.post("/api/stores", json={"name": "ร้านA"}).json()
        v = client.post(
            "/api/visits", json={"store_id": s["id"]}
        ).json()
        # Seed one matching-store doc and one different-store doc.
        for did, merchant in (("d1", "ร้านA"), ("d2", "ร้านB")):
            db_session.add(
                Document(
                    id=did,
                    filename=f"{did}.png",
                    file_path=f"/tmp/{did}.png",
                    file_type="image",
                    status="extracted",
                    merchant_name=merchant,
                    merchant_normalized=merchant,
                    visit_id=v["id"],
                )
            )
        db_session.commit()
        detail = client.get(f"/api/visits/{v['id']}").json()
        by_id = {d["id"]: d for d in detail["documents"]}
        assert by_id["d1"]["store_mismatch"] is False
        assert by_id["d2"]["store_mismatch"] is True
