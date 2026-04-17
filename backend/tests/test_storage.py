"""Tests for app.services.storage magic-byte validation + streaming hash."""

from __future__ import annotations

import io
import struct
import zlib

import pytest
from fastapi import HTTPException, UploadFile

from app.services.storage import validate_and_hash


def _make_tiny_png() -> bytes:
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


def _upload(data: bytes, filename: str) -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(data))


class TestValidateAndHash:
    def test_valid_png(self):
        png = _make_tiny_png()
        result = validate_and_hash(_upload(png, "r.png"), max_bytes=1024 * 1024)
        assert result.file_type == "image"
        assert len(result.file_hash) == 64  # SHA-256 hex
        assert result.size == len(png)
        assert result.data == png

    def test_valid_pdf(self):
        pdf = b"%PDF-1.4\n%EOF\n"
        result = validate_and_hash(_upload(pdf, "doc.pdf"), max_bytes=1024 * 1024)
        assert result.file_type == "pdf"
        assert result.size == len(pdf)

    def test_rejects_unknown_extension(self):
        with pytest.raises(HTTPException) as exc:
            validate_and_hash(_upload(b"hello", "file.txt"), max_bytes=1024)
        assert exc.value.status_code == 400

    def test_rejects_mismatched_magic_bytes(self):
        """A .png with text content should be rejected even with the right extension."""
        with pytest.raises(HTTPException) as exc:
            validate_and_hash(
                _upload(b"not a real png", "fake.png"),
                max_bytes=1024,
            )
        assert exc.value.status_code == 400
        assert "magic" in exc.value.detail.lower() or "ตรงกับนามสกุล" in exc.value.detail

    def test_rejects_pdf_without_magic(self):
        with pytest.raises(HTTPException) as exc:
            validate_and_hash(
                _upload(b"totally not pdf", "x.pdf"),
                max_bytes=1024,
            )
        assert exc.value.status_code == 400

    def test_rejects_oversize(self):
        png = _make_tiny_png() + b"\x00" * 2000
        # Valid magic but exceeds max_bytes
        with pytest.raises(HTTPException) as exc:
            validate_and_hash(_upload(png, "big.png"), max_bytes=100)
        assert exc.value.status_code == 413

    def test_rejects_empty_file(self):
        with pytest.raises(HTTPException) as exc:
            validate_and_hash(_upload(b"", "e.png"), max_bytes=1024)
        assert exc.value.status_code in (400,)

    def test_deterministic_hash(self):
        png = _make_tiny_png()
        r1 = validate_and_hash(_upload(png, "a.png"), max_bytes=1024 * 1024)
        r2 = validate_and_hash(_upload(png, "b.png"), max_bytes=1024 * 1024)
        assert r1.file_hash == r2.file_hash
