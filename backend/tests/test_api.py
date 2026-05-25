"""Tests for the FastAPI REST endpoints."""

import io
import struct
import zlib
from unittest.mock import patch


def _make_tiny_png() -> bytes:
    """Create a minimal valid 1x1 pixel PNG in memory."""

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)
    raw_row = b"\x00" + b"\xff\x00\x00"
    idat = _chunk(b"IDAT", zlib.compress(raw_row))
    iend = _chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


def _upload_document(client, png_bytes: bytes | None = None, filename: str = "receipt.png"):
    """Helper to upload a document. Mocks background processing."""
    if png_bytes is None:
        png_bytes = _make_tiny_png()
    # Mock _enqueue_processing so background task is a no-op
    # (it creates its own DB session which won't share the test's in-memory DB)
    with patch("app.routers.documents._enqueue_processing"):
        return client.post(
            "/api/documents/upload",
            files={"file": (filename, io.BytesIO(png_bytes), "image/png")},
        )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


class TestUploadDocument:
    def test_upload_returns_processing(self, client):
        resp = _upload_document(client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processing"
        assert data["filename"] == "receipt.png"
        assert "id" in data

    def test_upload_rejects_unsupported_extension(self, client):
        with patch("app.routers.documents._enqueue_processing"):
            resp = client.post(
                "/api/documents/upload",
                files={"file": ("file.txt", io.BytesIO(b"hello"), "text/plain")},
            )
        assert resp.status_code == 400

    def test_upload_duplicate_file_rejected(self, client):
        png = _make_tiny_png()
        resp1 = _upload_document(client, png)
        assert resp1.status_code == 200
        resp2 = _upload_document(client, png)
        assert resp2.status_code == 409


# ---------------------------------------------------------------------------
# List documents
# ---------------------------------------------------------------------------


class TestListDocuments:
    def test_list_empty(self, client):
        resp = client.get("/api/documents")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_upload(self, client):
        _upload_document(client)
        resp = client.get("/api/documents")
        assert resp.status_code == 200
        docs = resp.json()
        assert len(docs) == 1
        assert docs[0]["filename"] == "receipt.png"

    def test_list_with_search(self, client):
        _upload_document(client)
        resp = client.get("/api/documents?search=receipt")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        resp = client.get("/api/documents?search=nonexistent")
        assert resp.status_code == 200
        assert len(resp.json()) == 0


# ---------------------------------------------------------------------------
# Count
# ---------------------------------------------------------------------------


class TestCountDocuments:
    def test_count_empty(self, client):
        resp = client.get("/api/documents/count")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_count_after_upload(self, client):
        _upload_document(client)
        resp = client.get("/api/documents/count")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1


# ---------------------------------------------------------------------------
# Get document by ID
# ---------------------------------------------------------------------------


class TestGetDocument:
    def test_get_existing_document(self, client):
        upload_resp = _upload_document(client)
        doc_id = upload_resp.json()["id"]
        resp = client.get(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == doc_id

    def test_get_nonexistent_document_404(self, client):
        resp = client.get("/api/documents/nonexistent-id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Update document
# ---------------------------------------------------------------------------


class TestUpdateDocument:
    def test_update_document(self, client):
        upload_resp = _upload_document(client)
        doc_id = upload_resp.json()["id"]

        resp = client.put(
            f"/api/documents/{doc_id}",
            json={"merchant_name": "Updated Store"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["merchant_name"] == "Updated Store"

    def test_update_nonexistent_document_404(self, client):
        resp = client.put(
            "/api/documents/nonexistent-id",
            json={"merchant_name": "x"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Approve document
# ---------------------------------------------------------------------------


class TestApproveDocument:
    def test_approve_document(self, client):
        upload_resp = _upload_document(client)
        doc_id = upload_resp.json()["id"]

        resp = client.post(f"/api/documents/{doc_id}/approve")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "reviewed"
        assert data["needs_review"] is False
        assert data["reviewed_at"] is not None

    def test_approve_nonexistent_document_404(self, client):
        resp = client.post("/api/documents/nonexistent-id/approve")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete document
# ---------------------------------------------------------------------------


class TestDeleteDocument:
    def test_delete_document(self, client):
        upload_resp = _upload_document(client)
        doc_id = upload_resp.json()["id"]

        resp = client.delete(f"/api/documents/{doc_id}")
        assert resp.status_code == 200

        resp = client.get(f"/api/documents/{doc_id}")
        assert resp.status_code == 404

    def test_delete_nonexistent_document_404(self, client):
        resp = client.delete("/api/documents/nonexistent-id")
        assert resp.status_code == 404



