"""Tool implementations callable by Gemini during agentic extraction.

Design
------
We expose two tools to the model:

  * ``lookup_catalog(query, limit)`` — fuzzy-match a name against the active
    products catalog (Boonrawd + any competitor SKUs admins have approved) and
    return the top N candidates. Moves the catalog out of the prompt
    (~600-800 tokens saved) and into an on-demand DB lookup.
  * ``emit_extraction`` — structured finalizer. Gemini invokes this as the
    last step to return the extracted receipt.

The tool declarations here are consumed by
:mod:`app.services.extraction_agentic`, which runs the multi-turn loop.
"""

from __future__ import annotations

import logging
from typing import Any

from google.genai import types
from rapidfuzz import fuzz, process

from . import catalog

logger = logging.getLogger(__name__)


CatalogEntry = dict[str, Any]


def _flat_index() -> tuple[list[tuple[str, CatalogEntry]], list[str]]:
    """Build the flat (candidate-string, entry) pairs for fuzzy matching.

    Rebuilt on every call but cheap because :func:`catalog.prompt_catalog_entries`
    is itself cached.
    """
    flat: list[tuple[str, CatalogEntry]] = []
    for entry in catalog.prompt_catalog_entries():
        flat.append((entry["name"], entry))
        for alias in entry.get("aliases", []):
            flat.append((alias, entry))
    candidates = [s for s, _ in flat]
    return flat, candidates


def lookup_catalog(query: str, limit: int = 5, **_ignored) -> dict:
    """Fuzzy-match ``query`` against the active products catalog."""
    if not query:
        return {"matches": []}

    flat, candidates = _flat_index()
    if not candidates:
        return {"query": query, "matches": []}

    raw_matches = process.extract(
        query,
        candidates,
        scorer=fuzz.token_set_ratio,
        limit=limit * 2,
    )

    seen_names: set[str] = set()
    results: list[dict] = []
    for candidate_str, score, idx in raw_matches:
        entry = flat[idx][1]
        if entry["name"] in seen_names:
            continue
        seen_names.add(entry["name"])
        results.append(
            {
                "code": entry.get("code"),
                "name": entry["name"],
                "category": entry["category"],
                "matched_alias": candidate_str,
                "score": int(score),
            }
        )
        if len(results) >= limit:
            break

    return {"query": query, "matches": results}


def build_tool_declarations() -> list[types.Tool]:
    """Return the full set of function declarations to expose to Gemini."""
    lookup = types.FunctionDeclaration(
        name="lookup_catalog",
        description=(
            "ค้นหาสินค้าใน PRODUCT_CATALOG (ทั้งเครือบุญรอดและคู่แข่งที่ระบบเรียนรู้ไว้) "
            "จากชื่อ/ตัวย่อ/ลายมือที่อ่านได้จากเอกสาร. ใช้ก่อน emit_extraction ทุกครั้ง "
            "ที่เจอชื่อสินค้าในใบเสร็จเพื่อ map เป็นชื่อทางการ. "
            "ตัวอย่าง query: 'สห์ใหญ่', 'ลีโอ 630', 'ช้างขวด', 'โค้ก 1.25 ลิตร'"
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "ชื่อสินค้าที่อ่านได้จากเอกสาร",
                },
                "limit": {
                    "type": "INTEGER",
                    "description": "จำนวน match สูงสุดที่ต้องการ (default 5)",
                },
            },
            "required": ["query"],
        },
    )

    emit_extraction = types.FunctionDeclaration(
        name="emit_extraction",
        description=(
            "ส่งผลลัพธ์การดึงข้อมูลใบเสร็จเป็นโครงสร้างสุดท้าย. "
            "เรียกครั้งเดียวเมื่อเก็บข้อมูลครบและพร้อมจบการทำงาน"
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "merchant_name": {"type": "STRING"},
                "merchant_normalized": {"type": "STRING"},
                "document_number": {"type": "STRING"},
                "document_date": {
                    "type": "STRING",
                    "description": "YYYY-MM-DD (ค.ศ.)",
                },
                "category": {
                    "type": "STRING",
                    "description": "หมวดหมู่รวมของเอกสาร",
                },
                "items": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "product_name_raw": {
                                "type": "STRING",
                                "description": "ชื่อตามที่อ่านได้จากใบเสร็จ (ก่อน catalog normalization)",
                            },
                            "product_name_normalized": {
                                "type": "STRING",
                                "description": "ชื่อสินค้า (ชื่อทางการจาก catalog ถ้ามี ไม่งั้นใช้ raw)",
                            },
                            "product_code": {
                                "type": "STRING",
                                "description": (
                                    "SKU code จาก lookup_catalog match ที่ตรงที่สุด — "
                                    "ใส่เฉพาะเมื่อ score ≥ 85 และมั่นใจว่าเป็น SKU เดียวกันจริง; "
                                    "ถ้าไม่ match catalog ให้ละไว้ null"
                                ),
                            },
                            "category": {"type": "STRING"},
                            "quantity": {"type": "NUMBER"},
                            "unit": {"type": "STRING"},
                        },
                        "required": ["product_name_normalized"],
                    },
                },
                "confidence": {"type": "NUMBER"},
                "notes": {"type": "STRING"},
                "needs_review_fields": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                },
            },
            "required": ["items", "confidence"],
        },
    )

    return [types.Tool(function_declarations=[lookup, emit_extraction])]


TOOL_HANDLERS = {
    "lookup_catalog": lookup_catalog,
}
