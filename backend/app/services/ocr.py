"""PaddleOCR service for Thai-English receipt text extraction."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)

_ocr_engine = None

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
_NEEDS_CONVERT = {".webp"}


def _get_ocr():
    """Lazy-load PaddleOCR engine (heavy model, load once)."""
    global _ocr_engine
    if _ocr_engine is None:
        from paddleocr import PaddleOCR

        _ocr_engine = PaddleOCR(
            lang=settings.ocr_lang,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        logger.info("PaddleOCR v3 initialized (PP-OCRv5, lang=%s)", settings.ocr_lang)
    return _ocr_engine


_MAX_OCR_PIXELS = 2000


def _resize_if_needed(img):
    """Resize image so the longest side is at most _MAX_OCR_PIXELS."""
    w, h = img.size
    if max(w, h) <= _MAX_OCR_PIXELS:
        return img
    scale = _MAX_OCR_PIXELS / max(w, h)
    new_w, new_h = int(w * scale), int(h * scale)
    logger.info("Resizing image from %dx%d to %dx%d for OCR", w, h, new_w, new_h)
    return img.resize((new_w, new_h))


def _convert_to_png(file_path: str) -> str:
    """Convert unsupported image formats (e.g. webp) to PNG for OCR."""
    from PIL import Image

    path = Path(file_path)
    out_path = path.parent / f"_ocr_{uuid.uuid4().hex[:8]}_{path.stem}.png"
    img = _resize_if_needed(Image.open(file_path))
    img.save(str(out_path), "PNG")
    return str(out_path)


def _prepare_image(file_path: str) -> str | None:
    """Resize a jpg/png/bmp if too large. Returns temp path if resized, None if unchanged."""
    from PIL import Image

    img = Image.open(file_path)
    w, h = img.size
    if max(w, h) <= _MAX_OCR_PIXELS:
        return None
    resized = _resize_if_needed(img)
    path = Path(file_path)
    out_path = path.parent / f"_ocr_{uuid.uuid4().hex[:8]}_{path.stem}.png"
    resized.save(str(out_path), "PNG")
    return str(out_path)


_MIN_PDF_TEXT_CHARS = 50


def _extract_pdf_text(file_path: str) -> str | None:
    """Extract embedded text from a PDF. Returns text if sufficient, else None."""
    import fitz

    doc = fitz.open(file_path)
    pages_text = []
    for page in doc:
        pages_text.append(page.get_text())
    doc.close()

    full = "\n".join(pages_text).strip()
    if len(full) >= _MIN_PDF_TEXT_CHARS:
        logger.info(
            "PDF has embedded text (%d chars), skipping OCR", len(full)
        )
        return full
    return None


def _pdf_to_images(file_path: str) -> list[str]:
    """Convert PDF pages to temporary PNG images using PyMuPDF."""
    import fitz
    from PIL import Image
    import io

    doc = fitz.open(file_path)
    image_paths: list[str] = []
    parent = Path(file_path).parent

    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=200)
        img_path = parent / f"_ocr_{uuid.uuid4().hex[:8]}_page_{i}.png"
        # Resize if needed
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        img = _resize_if_needed(img)
        img.save(str(img_path), "PNG")
        image_paths.append(str(img_path))

    doc.close()
    return image_paths


def _ocr_single_image(file_path: str) -> list[dict]:
    """Run OCR on a single image file, return list of detected text blocks."""
    ocr = _get_ocr()
    result = ocr.predict(file_path)

    blocks = []
    if not result:
        return blocks

    for page_result in result:
        texts = page_result.get("rec_texts", [])
        scores = page_result.get("rec_scores", [])
        boxes = page_result.get("dt_polys", [])

        for i, text in enumerate(texts):
            confidence = scores[i] if i < len(scores) else 0.0
            bbox = boxes[i].tolist() if i < len(boxes) else []
            blocks.append({
                "text": text,
                "confidence": float(confidence),
                "bbox": bbox,
            })

    return blocks


def run_ocr(file_path: str) -> dict:
    """
    Run PaddleOCR on an image or PDF file.

    Returns:
        {
            "full_text": "all text concatenated with newlines",
            "blocks": [{"text": str, "confidence": float, "bbox": list}],
            "avg_confidence": float,
        }
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    logger.info("Running OCR on: %s", path.name)

    all_blocks: list[dict] = []
    temp_files: list[str] = []

    try:
        if ext == ".pdf":
            # Text-based PDF → extract embedded text (fast, accurate)
            # Scanned PDF → skip OCR, let Gemini read PDF directly (faster & better than OCR)
            pdf_text = _extract_pdf_text(file_path)
            if pdf_text:
                return {
                    "full_text": pdf_text,
                    "blocks": [{"text": line, "confidence": 1.0, "bbox": []}
                               for line in pdf_text.splitlines() if line.strip()],
                    "avg_confidence": 1.0,
                }
            logger.info("Scanned PDF detected, skipping OCR — Gemini will read PDF directly")
            return {"full_text": "", "blocks": [], "avg_confidence": 0.0}
        elif ext in _NEEDS_CONVERT:
            converted = _convert_to_png(file_path)
            temp_files.append(converted)
            all_blocks = _ocr_single_image(converted)
        elif ext in _IMAGE_EXTS:
            resized = _prepare_image(file_path)
            if resized:
                temp_files.append(resized)
            all_blocks = _ocr_single_image(resized or file_path)
        else:
            logger.warning("Unsupported file type for OCR: %s", ext)
            return {"full_text": "", "blocks": [], "avg_confidence": 0.0}
    finally:
        for tmp in temp_files:
            try:
                Path(tmp).unlink(missing_ok=True)
            except OSError:
                pass

    full_text = "\n".join(b["text"] for b in all_blocks)
    avg_conf = (
        sum(b["confidence"] for b in all_blocks) / len(all_blocks)
        if all_blocks
        else 0.0
    )

    logger.info(
        "OCR complete: %d text blocks, avg confidence %.2f",
        len(all_blocks),
        avg_conf,
    )

    return {
        "full_text": full_text,
        "blocks": all_blocks,
        "avg_confidence": avg_conf,
    }
