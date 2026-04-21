"""File upload handling: magic-byte validation, streaming hash, safe save.

Keeps the router thin and makes the logic unit-testable without spinning up
FastAPI. All functions raise ``HTTPException`` with Thai messages suitable for
the user-facing toast.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
from dataclasses import dataclass
from typing import BinaryIO

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()

logger = logging.getLogger(__name__)


ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".heic", ".heif"}

# HEIC/HEIF use the ISO base media container: bytes 4-8 are "ftyp", then a brand
# identifying HEIC/HEIF variants.
_HEIC_FTYP_BRANDS = (b"heic", b"heix", b"hevc", b"heim", b"heis", b"heim", b"mif1", b"msf1", b"heif")

# Extension → (expected file_type, list of accepted magic byte prefixes)
_MAGIC_BYTES: dict[str, tuple[str, tuple[bytes, ...]]] = {
    ".jpg": ("image", (b"\xff\xd8\xff",)),
    ".jpeg": ("image", (b"\xff\xd8\xff",)),
    ".png": ("image", (b"\x89PNG\r\n\x1a\n",)),
    ".webp": ("image", (b"RIFF",)),  # WebP: RIFF....WEBP
    ".heic": ("image", ()),  # validated via _verify_heic
    ".heif": ("image", ()),
    ".pdf": ("pdf", (b"%PDF-",)),
}

_CHUNK = 64 * 1024


@dataclass
class ValidatedUpload:
    """Result of :func:`validate_and_hash`."""

    file_hash: str
    file_type: str  # "image" | "pdf"
    size: int
    data: bytes  # full file content, already validated
    extension: str = ""  # effective extension to save under (post-conversion)


def _peek_magic(fp: BinaryIO, n: int) -> bytes:
    start = fp.tell()
    try:
        return fp.read(n)
    finally:
        fp.seek(start)


def _verify_webp(head: bytes) -> bool:
    """WebP files start with RIFF<size>WEBP."""
    return len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP"


def _verify_heic(head: bytes) -> bool:
    """HEIC/HEIF files have 'ftyp' at offset 4, followed by a brand."""
    if len(head) < 12 or head[4:8] != b"ftyp":
        return False
    brand = head[8:12]
    return brand in _HEIC_FTYP_BRANDS


def _convert_heic_to_jpeg(data: bytes) -> bytes:
    """Decode HEIC bytes and re-encode as JPEG so downstream Gemini/PDF viewers
    handle the file. Raises HTTPException on failure."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            rgb = img.convert("RGB")
            out = io.BytesIO()
            rgb.save(out, format="JPEG", quality=92)
            return out.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(400, "ไฟล์ HEIC/HEIF เสียหายหรือไม่รองรับ") from exc


def _verify_image_content(data: bytes) -> None:
    """Open the image with Pillow to confirm it's not a corrupted/malicious file."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(400, "ไฟล์รูปภาพเสียหายหรือไม่ใช่รูปจริง") from exc


def validate_and_hash(
    file: UploadFile,
    *,
    max_bytes: int,
) -> ValidatedUpload:
    """Validate extension, magic bytes, size, and compute SHA-256 while reading once.

    Raises ``HTTPException`` on any validation failure. On success, the returned
    ``data`` bytes can be written to disk with ``open(..., "wb").write(data)``.
    """
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"ไฟล์ไม่รองรับ: {ext or 'ไม่ทราบนามสกุล'}")

    expected_type, magic_prefixes = _MAGIC_BYTES[ext]

    head = _peek_magic(file.file, 16)
    if ext == ".webp":
        magic_ok = _verify_webp(head)
    elif ext in (".heic", ".heif"):
        magic_ok = _verify_heic(head)
    else:
        magic_ok = any(head.startswith(prefix) for prefix in magic_prefixes)

    if not magic_ok:
        raise HTTPException(
            400,
            f"ไฟล์ไม่ตรงกับนามสกุล {ext} (magic bytes ไม่ถูกต้อง)",
        )

    hasher = hashlib.sha256()
    buf = bytearray()
    size = 0
    while True:
        chunk = file.file.read(_CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(
                413,
                f"ไฟล์ใหญ่เกิน {max_bytes // 1024 // 1024} MB",
            )
        hasher.update(chunk)
        buf.extend(chunk)

    if size == 0:
        raise HTTPException(400, "ไฟล์ว่างเปล่า")

    data = bytes(buf)
    final_ext = ext

    if ext in (".heic", ".heif"):
        data = _convert_heic_to_jpeg(data)
        final_ext = ".jpg"
        # re-hash so duplicate detection works on the stored JPEG
        hasher = hashlib.sha256()
        hasher.update(data)
        size = len(data)

    if expected_type == "image":
        _verify_image_content(data)

    return ValidatedUpload(
        file_hash=hasher.hexdigest(),
        file_type=expected_type,
        size=size,
        data=data,
        extension=final_ext,
    )


def save_bytes(path: str, data: bytes) -> None:
    """Save bytes atomically (write to .tmp, then rename)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
