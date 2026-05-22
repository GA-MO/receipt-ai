"""Tests for the Drop & Review inbox dashboard."""

from __future__ import annotations

import struct
import zlib
from datetime import UTC, datetime, timedelta

from app.models import Document, Store, Visit


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


def _seed_doc(
    db,
    *,
    doc_id: str,
    status: str = "extracted",
    merchant: str | None = None,
    document_date: str | None = None,
    visit_id: str | None = None,
    uploaded_at: datetime | None = None,
) -> Document:
    doc = Document(
        id=doc_id,
        filename=f"{doc_id}.png",
        file_path=f"/tmp/{doc_id}.png",
        file_type="image",
        status=status,
        merchant_name=merchant,
        merchant_normalized=merchant,
        document_date=document_date,
        visit_id=visit_id,
        uploaded_at=uploaded_at or datetime.now(UTC),
    )
    db.add(doc)
    db.flush()
    return doc


class TestInboxUpload:
    def test_upload_accepts_multiple_files(self, client, monkeypatch):
        from app.routers import documents as docs_mod

        monkeypatch.setattr(docs_mod, "_enqueue_processing", lambda *a, **k: None)
        png = _make_tiny_png()
        resp = client.post(
            "/api/inbox",
            files=[("files", ("a.png", png, "image/png"))],
        )
        assert resp.status_code == 201
        body = resp.json()
        assert len(body["document_ids"]) == 1

    def test_upload_sets_auto_attach_true(self, client, db_session, monkeypatch):
        # In Drop & Review the worker auto-attaches the doc once extracted,
        # so the upload endpoint must NOT disable that.
        from app.routers import documents as docs_mod

        monkeypatch.setattr(docs_mod, "_enqueue_processing", lambda *a, **k: None)
        png = _make_tiny_png()
        resp = client.post(
            "/api/inbox",
            files=[("files", ("a.png", png, "image/png"))],
        )
        doc_id = resp.json()["document_ids"][0]
        doc = db_session.query(Document).filter(Document.id == doc_id).first()
        assert doc.auto_attach_visit is True


class TestDashboard:
    def test_lists_orphans_non_receipts_errors(self, client, db_session):
        _seed_doc(db_session, doc_id="orphan", merchant=None, status="extracted")
        _seed_doc(db_session, doc_id="junk", status="not_receipt")
        _seed_doc(db_session, doc_id="bad", status="error")
        db_session.commit()

        body = client.get("/api/inbox/dashboard").json()
        assert body["counts"]["orphans"] == 1
        assert body["counts"]["non_receipts"] == 1
        assert body["counts"]["errors"] == 1
        assert {d["id"] for d in body["orphans"]} == {"orphan"}
        assert {d["id"] for d in body["non_receipts"]} == {"junk"}
        assert {d["id"] for d in body["errors"]} == {"bad"}

    def test_filters_visits_by_month(self, client, db_session):
        v_may = Visit(id="v-may", store_label="X", report_period="2026-05")
        v_apr = Visit(id="v-apr", store_label="X", report_period="2026-04")
        db_session.add_all([v_may, v_apr])
        db_session.commit()

        body = client.get("/api/inbox/dashboard?month=2026-05").json()
        ids = [v["id"] for v in body["visits"]]
        assert "v-may" in ids
        assert "v-apr" not in ids

    def test_lists_available_months(self, client, db_session):
        db_session.add_all(
            [
                Visit(id="v1", store_label="X", report_period="2026-05"),
                Visit(id="v2", store_label="Y", report_period="2026-04"),
                Visit(id="v3", store_label="Z", report_period="2026-04"),  # dup month
            ]
        )
        db_session.commit()

        body = client.get("/api/inbox/dashboard").json()
        assert "2026-05" in body["available_months"]
        assert "2026-04" in body["available_months"]

    def test_flags_visit_with_new_docs_after_review(self, client, db_session):
        reviewed_at = datetime.now(UTC) - timedelta(hours=1)
        v = Visit(
            id="v1",
            store_label="ร้าน A",
            store_key="ร้านA",
            report_period="2026-05",
            last_reviewed_at=reviewed_at,
        )
        db_session.add(v)
        # One doc uploaded BEFORE review, one AFTER → only the latter counts.
        _seed_doc(
            db_session,
            doc_id="d-old",
            merchant="ร้านA",
            visit_id="v1",
            uploaded_at=reviewed_at - timedelta(minutes=10),
        )
        _seed_doc(
            db_session,
            doc_id="d-new",
            merchant="ร้านA",
            visit_id="v1",
            uploaded_at=reviewed_at + timedelta(minutes=10),
        )
        db_session.commit()

        body = client.get("/api/inbox/dashboard").json()
        visit_row = next(v for v in body["visits"] if v["id"] == "v1")
        assert visit_row["new_doc_count"] == 1
        assert body["counts"]["attention"] == 1


class TestOrphanNaming:
    def test_name_orphan_attaches_visit(self, client, db_session):
        db_session.add(
            Store(
                id="store-somsak",
                name="ร้านสมศักดิ์",
                normalized_name="ร้านสมศักดิ์",
                active=True,
            )
        )
        _seed_doc(
            db_session,
            doc_id="orphan",
            merchant=None,
            document_date="2026-05-15",
        )
        db_session.commit()

        resp = client.post(
            "/api/inbox/documents/orphan/name",
            json={"merchant_name": "ร้านสมศักดิ์"},
        )
        assert resp.status_code == 200
        doc = db_session.query(Document).filter(Document.id == "orphan").first()
        assert doc.visit_id is not None
        visit = db_session.query(Visit).filter(Visit.id == doc.visit_id).first()
        assert visit.report_period == "2026-05"
        assert visit.store_label == "ร้านสมศักดิ์"

    def test_name_orphan_without_matching_store_holds_doc(self, client, db_session):
        """Naming an orphan with an unrecognised merchant leaves the doc
        unattached — it surfaces in the dashboard's unknown-stores section."""
        _seed_doc(
            db_session,
            doc_id="orphan",
            merchant=None,
            document_date="2026-05-15",
        )
        db_session.commit()

        resp = client.post(
            "/api/inbox/documents/orphan/name",
            json={"merchant_name": "ร้านที่ไม่อยู่ในระบบ"},
        )
        assert resp.status_code == 200
        doc = db_session.query(Document).filter(Document.id == "orphan").first()
        assert doc.merchant_name == "ร้านที่ไม่อยู่ในระบบ"
        assert doc.visit_id is None

    def test_name_orphan_rejects_attached(self, client, db_session):
        v = Visit(id="v1", store_label="X")
        db_session.add(v)
        _seed_doc(db_session, doc_id="d1", merchant="ร้านA", visit_id="v1")
        db_session.commit()

        resp = client.post(
            "/api/inbox/documents/d1/name",
            json={"merchant_name": "ร้านB"},
        )
        assert resp.status_code == 400

    def test_name_orphan_rejects_empty(self, client, db_session):
        _seed_doc(db_session, doc_id="orphan", merchant=None)
        db_session.commit()

        resp = client.post(
            "/api/inbox/documents/orphan/name",
            json={"merchant_name": "   "},
        )
        assert resp.status_code == 400


class TestMarkReviewed:
    def test_stamps_last_reviewed_at(self, client, db_session):
        v = Visit(id="v1", store_label="X", report_period="2026-05")
        db_session.add(v)
        db_session.commit()

        resp = client.post("/api/inbox/visits/v1/mark-reviewed")
        assert resp.status_code == 200
        db_session.expire_all()
        visit = db_session.query(Visit).filter(Visit.id == "v1").first()
        assert visit.last_reviewed_at is not None


class TestNonReceiptPurge:
    def test_purges_old_non_receipts(self, client, db_session):
        old = datetime.now(UTC) - timedelta(days=8)
        recent = datetime.now(UTC) - timedelta(days=2)
        _seed_doc(db_session, doc_id="old", status="not_receipt", uploaded_at=old)
        _seed_doc(db_session, doc_id="recent", status="not_receipt", uploaded_at=recent)
        db_session.commit()

        resp = client.post("/api/inbox/non-receipts/purge")
        assert resp.status_code == 200
        assert resp.json()["purged"] == 1
        old_doc = db_session.query(Document).filter(Document.id == "old").first()
        recent_doc = db_session.query(Document).filter(Document.id == "recent").first()
        assert old_doc.deleted_at is not None
        assert recent_doc.deleted_at is None


class TestVisitReassignOnEdit:
    def test_editing_merchant_moves_doc_to_different_visit(self, client, db_session):
        store_a = Store(id="sa", name="ร้าน A", normalized_name="ร้านA", active=True)
        store_b = Store(id="sb", name="ร้าน B", normalized_name="ร้านB", active=True)
        v_a = Visit(
            id="va",
            store_id="sa",
            store_key="ร้านA",
            store_label="ร้าน A",
            report_period="2026-05",
        )
        db_session.add_all([store_a, store_b, v_a])
        _seed_doc(
            db_session,
            doc_id="d1",
            merchant="ร้านA",
            document_date="2026-05-15",
            visit_id="va",
        )
        db_session.commit()

        # User corrects the merchant — doc should jump to (or create) Visit B.
        resp = client.put(
            "/api/documents/d1",
            json={"merchant_name": "ร้านB", "merchant_normalized": "ร้านB"},
        )
        assert resp.status_code == 200
        db_session.expire_all()
        doc = db_session.query(Document).filter(Document.id == "d1").first()
        assert doc.visit_id != "va"
        new_visit = db_session.query(Visit).filter(Visit.id == doc.visit_id).first()
        assert new_visit.store_key == "ร้านB"
        assert new_visit.report_period == "2026-05"

    def test_editing_date_moves_doc_to_different_month_visit(self, client, db_session):
        store_a = Store(id="sa", name="ร้าน A", normalized_name="ร้านA", active=True)
        v_may = Visit(
            id="v-may",
            store_id="sa",
            store_key="ร้านA",
            store_label="ร้าน A",
            report_period="2026-05",
        )
        db_session.add_all([store_a, v_may])
        _seed_doc(
            db_session,
            doc_id="d1",
            merchant="ร้านA",
            document_date="2026-05-15",
            visit_id="v-may",
        )
        db_session.commit()

        # Move the receipt to April.
        resp = client.put("/api/documents/d1", json={"document_date": "2026-04-20"})
        assert resp.status_code == 200
        db_session.expire_all()
        doc = db_session.query(Document).filter(Document.id == "d1").first()
        assert doc.visit_id != "v-may"
        new_visit = db_session.query(Visit).filter(Visit.id == doc.visit_id).first()
        assert new_visit.report_period == "2026-04"
