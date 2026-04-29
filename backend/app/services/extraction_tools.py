"""Tool implementations callable by Gemini during agentic extraction.

Design
------
We expose three tools to the model:

  * ``lookup_catalog(query, limit)`` — fuzzy-match a name against the Boonrawd
    product catalog and return the top N candidates. Moves the catalog out of
    the prompt (~600-800 tokens saved) and into an on-demand DB lookup.
  * ``check_merchant_history(merchant_name, limit)`` — return recent document
    summaries for the given merchant so Gemini can reason about duplicates or
    unusual amounts inline with extraction (no separate fraud call).
  * ``emit_extraction`` / ``emit_fraud_analysis`` — structured finalizer calls.
    Gemini invokes these as the last step to return the extracted receipt.

The tool declarations here are consumed by
:mod:`app.services.extraction_agentic`, which runs the multi-turn loop.
"""

from __future__ import annotations

import logging
from typing import Any

from google.genai import types
from rapidfuzz import fuzz, process
from sqlalchemy.orm import Session

from ..models import Document
from . import catalog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Catalog (DB-backed, lazily loaded)
# ---------------------------------------------------------------------------
#
# The catalog used to be a hardcoded list of dicts. It is now built from
# active rows in the ``products`` table via :func:`catalog.prompt_catalog_entries`,
# which merges seed aliases (``products.aliases``) and learned aliases
# (``product_aliases``). Cleared by :func:`catalog.invalidate_cache` whenever
# admin endpoints mutate ``products``.

CatalogEntry = dict[str, Any]


def _flat_index() -> tuple[list[tuple[str, CatalogEntry]], list[str]]:
    """Build the flat (candidate-string, entry) pairs for fuzzy matching.

    Rebuilt on every call but cheap because :func:`catalog.prompt_catalog_entries`
    is itself cached. We avoid module-level caching here so that
    ``invalidate_cache`` clearing the underlying entries flows through
    automatically without us tracking a second cache key.
    """
    flat: list[tuple[str, CatalogEntry]] = []
    for entry in catalog.prompt_catalog_entries():
        flat.append((entry["name"], entry))
        for alias in entry.get("aliases", []):
            flat.append((alias, entry))
    candidates = [s for s, _ in flat]
    return flat, candidates


# ---------------------------------------------------------------------------
# Tool: lookup_catalog
# ---------------------------------------------------------------------------


def lookup_catalog(query: str, limit: int = 5, **_ignored) -> dict:
    """Fuzzy-match ``query`` against the active products catalog.

    Returns the top ``limit`` matches sorted by similarity. Each match
    includes the SKU ``code`` so Gemini can emit it in ``product_code`` via
    :func:`emit_extraction` instead of relying on a downstream fuzzy fallback.
    """
    if not query:
        return {"matches": []}

    flat, candidates = _flat_index()
    if not candidates:
        return {"query": query, "matches": []}

    raw_matches = process.extract(
        query,
        candidates,
        scorer=fuzz.token_set_ratio,
        limit=limit * 2,  # oversample before de-duping to canonical entries
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


# ---------------------------------------------------------------------------
# Tool: check_merchant_history
# ---------------------------------------------------------------------------


def check_merchant_history(
    merchant_name: str,
    db: Session,
    limit: int = 10,
    **_ignored,
) -> dict:
    """Return recent docs from the same merchant (for fraud / duplicate checks)."""
    if not merchant_name:
        return {"history": [], "stats": None}

    # Exact match first; fall back to fuzzy over merchant_normalized.
    docs = (
        db.query(Document)
        .filter(
            Document.merchant_name == merchant_name,
            Document.grand_total.isnot(None),
            Document.status.in_(["extracted", "reviewed"]),
        )
        .order_by(Document.document_date.desc())
        .limit(limit)
        .all()
    )

    if len(docs) < 3:
        # Try fuzzy against merchant_normalized
        all_merchants = (
            db.query(Document.merchant_normalized)
            .filter(Document.merchant_normalized.isnot(None))
            .distinct()
            .all()
        )
        names = [m[0] for m in all_merchants if m[0]]
        match = process.extractOne(merchant_name, names, scorer=fuzz.token_set_ratio)
        if match and match[1] >= 85:
            docs = (
                db.query(Document)
                .filter(
                    Document.merchant_normalized == match[0],
                    Document.grand_total.isnot(None),
                    Document.status.in_(["extracted", "reviewed"]),
                )
                .order_by(Document.document_date.desc())
                .limit(limit)
                .all()
            )

    if not docs:
        return {
            "history": [],
            "stats": None,
            "note": "ไม่มีประวัติในระบบสำหรับร้านค้านี้",
        }

    totals = [float(d.grand_total) for d in docs if d.grand_total]
    stats = {
        "count": len(docs),
        "avg_total": round(sum(totals) / len(totals), 2) if totals else 0,
        "max_total": round(max(totals), 2) if totals else 0,
        "min_total": round(min(totals), 2) if totals else 0,
    }

    history = [
        {
            "date": d.document_date,
            "document_number": d.document_number,
            "grand_total": round(float(d.grand_total), 2) if d.grand_total else None,
            "items_count": len(d.items),
            "category": d.category,
        }
        for d in docs
    ]

    return {
        "history": history,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# Tool declarations for Gemini
# ---------------------------------------------------------------------------


def build_tool_declarations() -> list[types.Tool]:
    """Return the full set of function declarations to expose to Gemini."""
    lookup = types.FunctionDeclaration(
        name="lookup_catalog",
        description=(
            "ค้นหาสินค้าในตาราง PRODUCT_CATALOG ของเครือบุญรอด จากชื่อ/ตัวย่อ/"
            "ลายมือที่อ่านได้จากเอกสาร. ใช้ก่อน emit_extraction ทุกครั้งที่เจอ "
            "ชื่อสินค้าในใบเสร็จเพื่อ map เป็นชื่อทางการ. "
            "ตัวอย่าง query: 'สห์ใหญ่', 'ลีโอ 630', 'โซดาเปลี่ยน/ถาด'"
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

    history = types.FunctionDeclaration(
        name="check_merchant_history",
        description=(
            "ดึงประวัติเอกสารของร้านค้าที่ระบุเพื่อใช้วิเคราะห์ fraud "
            "(เอกสารซ้ำ, ยอดผิดปกติ). ใช้ตอนเจอ merchant_name ชัดเจนแล้ว "
            "ก่อน emit_extraction/emit_fraud_analysis"
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "merchant_name": {
                    "type": "STRING",
                    "description": "ชื่อร้านค้าที่ดึงมาจากเอกสาร",
                },
                "limit": {
                    "type": "INTEGER",
                    "description": "จำนวนเอกสารล่าสุดที่ดึง (default 10)",
                },
            },
            "required": ["merchant_name"],
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
                            "product_name_normalized": {
                                "type": "STRING",
                                "description": "ชื่อสินค้า (ชื่อทางการจาก catalog ถ้ามี)",
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
                            "unit_price": {"type": "NUMBER"},
                            "line_total": {"type": "NUMBER"},
                        },
                        "required": ["product_name_normalized"],
                    },
                },
                "subtotal": {"type": "NUMBER"},
                "discount": {"type": "NUMBER"},
                "vat": {"type": "NUMBER"},
                "grand_total": {"type": "NUMBER"},
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

    emit_fraud = types.FunctionDeclaration(
        name="emit_fraud_analysis",
        description=(
            "ส่งผลการวิเคราะห์ความผิดปกติของเอกสาร (self-contained + history-aware). "
            "เรียกหลัง emit_extraction เท่านั้น และครั้งเดียว"
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "risk_score": {"type": "NUMBER"},
                "risk_level": {"type": "STRING"},
                "summary": {"type": "STRING"},
                "flags": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "type": {"type": "STRING"},
                            "label": {"type": "STRING"},
                            "severity": {"type": "STRING"},
                            "detail": {"type": "STRING"},
                        },
                        "required": ["label", "severity", "detail"],
                    },
                },
            },
            "required": ["risk_score", "risk_level", "summary"],
        },
    )

    return [
        types.Tool(
            function_declarations=[lookup, history, emit_extraction, emit_fraud]
        )
    ]


# Dispatcher used by the agentic loop to invoke a tool by name.
TOOL_HANDLERS = {
    "lookup_catalog": lookup_catalog,
    "check_merchant_history": check_merchant_history,
}
