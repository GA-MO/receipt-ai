"""Combined extraction + self-contained fraud in a single Gemini call.

Motivation: the legacy flow makes two sequential Gemini calls per document
(extraction then fraud). This module collapses them into one call, cutting
~40-50% of processing time.

Gemini handles:
  * Receipt field extraction (same as legacy).
  * Self-contained fraud analysis — signals that only need the document
    itself (future dates, VAT math, confidence, handwriting quality).

History-based fraud signals (duplicate receipts, unusual amount vs merchant
average) are handled by :func:`compute_history_fraud_checks` in pure Python —
deterministic SQL queries, no additional LLM cost.

The flow is switched on via ``settings.use_combined_extraction`` (default off)
so we can A/B test quality against the legacy 2-call flow.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Document
from ..schemas import ExtractionResult
from . import llm_client
from .extraction import (
    _MIME_MAP,
    EXTRACTION_PROMPT,
    build_system_instruction,
    parse_extraction_payload,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_FRAUD_SCHEMA_ADDITION = """

## หลังจาก extract ข้อมูลเสร็จ ต้องเพิ่ม field `fraud_analysis` ด้วย
`fraud_analysis` ทำหน้าที่ตรวจสอบความผิดปกติที่ **มองเห็นจากเอกสารเองเท่านั้น** (ไม่ต้องใช้ประวัติร้านค้า)
เพิ่มเข้าไปใน JSON response แบบนี้:

"fraud_analysis": {
  "risk_score": 0.0,
  "risk_level": "low",
  "summary": "สรุปผลวิเคราะห์เป็นภาษาไทย 1-2 ประโยค",
  "flags": [
    {
      "type": "ai_analysis",
      "label": "ชื่อประเด็นสั้นๆ เป็นภาษาไทย",
      "severity": "high|medium|low",
      "detail": "อธิบายรายละเอียดเป็นภาษาไทย"
    }
  ]
}

## กฎการวิเคราะห์ fraud
- risk_score: 0.0 (ปลอดภัย) ถึง 1.0 (น่าสงสัยมาก)
- risk_level: "low" (< 0.3), "medium" (0.3-0.6), "high" (> 0.6)
- ถ้าไม่พบสิ่งผิดปกติ ให้ flags=[] และ summary อธิบายว่าปกติ
- **Consistency rule (สำคัญมาก):** ถ้าใส่ข้อสังเกต/คำเตือนใน `notes` ของ extraction
  (เช่น "VAT อาจไม่ตรง", "ยอดรวมไม่ตรง", "ลายมือไม่ชัด") ต้อง **flag ใน fraud_analysis ด้วย**
  ห้ามให้ notes ขัดแย้งกับ fraud_analysis.summary
  - ถ้า notes บอกว่าปกติ → fraud_analysis.summary ควรบอกว่าปกติ
  - ถ้า notes มี ⚠️ หรือคำว่า "อาจ", "ไม่ตรง", "ไม่ชัด" → ต้องเพิ่ม flag ใน fraud_analysis.flags
- **วันที่วันนี้คือ __TODAY__ (ค.ศ. __TODAY_CE__ / พ.ศ. __TODAY_BE__)**
  - ใช้เทียบเฉพาะ `document_date` (รูปแบบ ค.ศ. YYYY-MM-DD ที่ extract แล้ว) เท่านั้น
  - **ห้ามคำนวณ พ.ศ. เอง** เพื่อเทียบ — ใช้ ค.ศ. ที่ extract แล้วเทียบกับ ค.ศ. ของวันนี้เท่านั้น
  - ตัวอย่าง: ปี พ.ศ. 2568 = ค.ศ. 2025 = **อดีต** (ไม่ใช่อนาคต) เพราะตอนนี้คือ พ.ศ. __TODAY_BE__ / ค.ศ. __TODAY_CE__
  - flag "วันที่ในอนาคต" เฉพาะเมื่อ `document_date` (ค.ศ.) > วันนี้ (ค.ศ.) จริงๆ เท่านั้น

บริบทธุรกิจ:
- ใบเสร็จ/บิลเงินสดร้านค้าปลีกไทย ส่วนมากไม่มีเลขที่เอกสาร → ปกติ ไม่ flag
- ยอดเงินกลม (฿5,000 ฿10,000) สำหรับสั่งเป็นลัง → ปกติ ไม่ flag
- ใบเสร็จเขียนมือที่ชื่อย่อ/อ่านยาก → ปกติ ไม่ flag
- confidence ≥70% → ปกติ ไม่ flag

flag เฉพาะเคสจริงๆ เช่น:
- HIGH:
  * วันที่ในอนาคต (หลัง {today})
  * วันที่เก่าเกิน 5 ปี (เอกสารปลอม?)
  * confidence < 40% (อ่านไม่ออกจริง)
  * **ไม่พบยอดรวม (grand_total)** — เอกสารชำรุด หรืออาจไม่ใช่ใบเสร็จ
- MEDIUM:
  * VAT คำนวณผิดเกิน 5%
  * ยอดรวมรายการไม่ตรงกับ grand_total เกิน 10%
  * รายการสินค้าราคาต่อหน่วยผิดปกติชัดเจน (เช่น เบียร์ขวดละ ฿10,000)
  * **ไม่พบชื่อร้านค้า (merchant_name)** — กระทบการทำ ภ.พ.30 / audit ต้องตรวจมือ
- LOW:
  * confidence 40-60%
  * ข้อสังเกตเล็กน้อย

**สิ่งที่ห้าม flag** (จะถูกตรวจโดยระบบ Python ภายหลังเอง):
- ยอดสูงผิดปกติเทียบกับประวัติร้าน (ไม่มีข้อมูลใน prompt นี้)
- เอกสารซ้ำ (ไม่มีข้อมูลใน prompt นี้)

ตอบ JSON เท่านั้น — extraction fields + fraud_analysis ใน object เดียวกัน
"""


def _build_system_instruction() -> str:
    """Build the combined system instruction with today's date injected.

    Uses a plain ``str.replace`` (not ``str.format``) because the fraud schema
    contains literal ``{``/``}`` from the JSON example which ``format()``
    would treat as placeholders.
    """
    now = datetime.now(UTC)
    today = now.strftime("%Y-%m-%d")
    today_ce = str(now.year)
    today_be = str(now.year + 543)
    return (
        build_system_instruction()
        + _FRAUD_SCHEMA_ADDITION.replace("__TODAY__", today)
        .replace("__TODAY_CE__", today_ce)
        .replace("__TODAY_BE__", today_be)
    )


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class CombinedResult:
    """Return type for :func:`extract_with_fraud`."""

    def __init__(
        self,
        extraction: ExtractionResult,
        fraud_payload: dict | None,
    ) -> None:
        self.extraction = extraction
        self.fraud_payload = fraud_payload  # {"flags": [...], "ai_analysis": {...}}


# ---------------------------------------------------------------------------
# Single-call extraction with fraud
# ---------------------------------------------------------------------------


def extract_with_fraud(file_path: str) -> CombinedResult:
    """Run extraction + self-contained fraud check in one LLM call."""
    path = Path(file_path)
    mime_type = _MIME_MAP.get(path.suffix.lower(), "image/jpeg")
    file_data = path.read_bytes()

    logger.info(
        "Combined extract+fraud: %s (%s, %d bytes)", path.name, mime_type, len(file_data)
    )
    raw_text = llm_client.generate_json(
        system_instruction=_build_system_instruction(),
        prompt=EXTRACTION_PROMPT,
        file_bytes=file_data,
        mime_type=mime_type,
        temperature=0.1,
    )

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.error("LLM returned invalid JSON: %s", raw_text[:500])
        raise RuntimeError(f"AI ตอบ JSON ไม่ถูกต้อง: {exc}") from exc

    if isinstance(data, list):
        data = data[0] if data and isinstance(data[0], dict) else {}

    extraction = parse_extraction_payload(data)
    fraud_payload = _parse_fraud_block(data.get("fraud_analysis"))

    logger.info(
        "Combined extract complete: merchant=%s, total=%s, conf=%.2f, items=%d, risk=%.2f",
        extraction.merchant_name,
        extraction.grand_total,
        extraction.confidence,
        len(extraction.items),
        (fraud_payload.get("ai_analysis") or {}).get("risk_score", 0.0)
        if fraud_payload
        else 0.0,
    )

    return CombinedResult(extraction=extraction, fraud_payload=fraud_payload)


def _parse_fraud_block(block: object) -> dict | None:
    """Normalize a ``fraud_analysis`` block returned by Gemini."""
    if not isinstance(block, dict):
        return None
    flags = block.get("flags") or []
    if not isinstance(flags, list):
        flags = []
    normalized_flags = [
        {
            "type": f.get("type", "ai_analysis"),
            "label": f.get("label", ""),
            "severity": f.get("severity", "low"),
            "detail": f.get("detail", ""),
        }
        for f in flags
        if isinstance(f, dict)
    ]
    return {
        "flags": normalized_flags,
        "ai_analysis": {
            "risk_score": float(block.get("risk_score") or 0.0),
            "risk_level": block.get("risk_level") or "low",
            "summary": block.get("summary") or "",
        },
    }


# ---------------------------------------------------------------------------
# History-based fraud checks (pure Python, no LLM)
# ---------------------------------------------------------------------------


def compute_history_fraud_checks(doc: Document, db: Session) -> list[dict]:
    """Run deterministic SQL-based fraud checks (duplicate, unusual amount).

    Complements :func:`extract_with_fraud` which only handles document-internal
    signals. Returns a list of fraud flags that can be appended to the
    Gemini-produced ``fraud_analysis`` block.
    """
    flags: list[dict] = []

    # Data quality flags — independent of merchant history
    if not doc.merchant_name:
        flags.append(
            {
                "type": "missing_merchant",
                "label": "ไม่พบชื่อร้านค้า",
                "severity": "medium",
                "detail": "AI อ่านชื่อร้านไม่ได้ — กระทบการทำ ภ.พ.30 / audit ต้องตรวจสอบด้วยมือ",
            }
        )
    if not doc.grand_total:
        flags.append(
            {
                "type": "missing_total",
                "label": "ไม่พบยอดรวม",
                "severity": "high",
                "detail": "เอกสารไม่มียอดรวม — อาจชำรุดหรือไม่ใช่ใบเสร็จที่สมบูรณ์",
            }
        )

    if not doc.merchant_name or not doc.grand_total:
        return flags

    grand_total = float(doc.grand_total)

    # ---- VAT calculation check ----
    # Thai VAT = 7%. If subtotal + vat ≠ grand_total (within tolerance), or
    # vat ≠ 7% of subtotal (within tolerance), flag it.
    if doc.subtotal is not None and doc.vat is not None and doc.vat > 0:
        subtotal = float(doc.subtotal)
        vat = float(doc.vat)
        # Check 1: subtotal + vat = grand_total ?
        sum_check_diff = abs((subtotal + vat) - grand_total)
        sum_check_pct = sum_check_diff / max(grand_total, 0.01)
        # Check 2: vat ≈ 7% of subtotal ?
        expected_vat = subtotal * 0.07
        vat_pct_diff = abs(expected_vat - vat) / max(expected_vat, 0.01)
        if sum_check_pct > 0.01 or vat_pct_diff > 0.05:
            flags.append(
                {
                    "type": "vat_mismatch",
                    "label": "VAT คำนวณไม่ตรง 7%",
                    "severity": "medium",
                    "detail": (
                        f"ยอดก่อน VAT ฿{subtotal:,.2f} + VAT ฿{vat:,.2f} = ฿{subtotal + vat:,.2f} "
                        f"ไม่ตรงกับยอดรวม ฿{grand_total:,.2f} (ต่างกัน {sum_check_pct * 100:.1f}%) "
                        f"หรือ VAT ที่ควรเป็น (7% ของ ฿{subtotal:,.2f}) = ฿{expected_vat:,.2f}"
                    ),
                }
            )

    # ---- Items-vs-grand_total mismatch check ----
    # Thai receipts: line totals are typically VAT-inclusive, so sum(line_total)
    # should match grand_total (not subtotal). Tolerance: 1% (handles rounding).
    items = list(doc.items or [])
    if items:
        items_sum = sum(float(it.line_total or 0) for it in items)
        if items_sum > 0:
            diff_pct = abs(items_sum - grand_total) / max(grand_total, 0.01)
            if diff_pct > 0.10:
                flags.append(
                    {
                        "type": "items_total_mismatch",
                        "label": "ยอดรวมรายการต่างจากยอดรวมมาก",
                        "severity": "high",
                        "detail": (
                            f"ผลรวมราคาสินค้า ฿{items_sum:,.2f} "
                            f"ต่างจากยอดรวมในเอกสาร ฿{grand_total:,.2f} "
                            f"ถึง {diff_pct * 100:.1f}% — อาจมีรายการตกหล่น/อ่านผิด หรือเอกสารถูกแก้ไข"
                        ),
                    }
                )
            elif diff_pct > 0.01:
                flags.append(
                    {
                        "type": "items_total_mismatch",
                        "label": "ยอดรวมรายการต่างจากยอดรวมเล็กน้อย",
                        "severity": "medium",
                        "detail": (
                            f"ผลรวมราคาสินค้า ฿{items_sum:,.2f} "
                            f"ต่างจากยอดรวมในเอกสาร ฿{grand_total:,.2f} "
                            f"({diff_pct * 100:.1f}%) — อาจมี discount หรือ rounding ที่ไม่ได้ extract"
                        ),
                    }
                )

    # ---- Duplicate detection: same merchant + date + total (± 1 baht) ----
    if doc.document_date:
        duplicate_query = (
            db.query(Document)
            .filter(
                Document.id != doc.id,
                Document.merchant_name == doc.merchant_name,
                Document.document_date == doc.document_date,
                Document.grand_total.isnot(None),
            )
            .all()
        )
        for other in duplicate_query:
            if abs(float(other.grand_total or 0) - grand_total) <= 1.0:
                flags.append(
                    {
                        "type": "duplicate",
                        "label": "เอกสารซ้ำซ้อน",
                        "severity": "high",
                        "detail": (
                            f"มีเอกสารในระบบที่ร้านเดียวกัน วันเดียวกัน "
                            f"({doc.document_date}) และยอดเท่ากัน "
                            f"(฿{grand_total:,.2f}) — เอกสารเลขที่ {other.document_number or other.id[:8]}"
                        ),
                    }
                )
                break

    # ---- Unusual amount: >5x the merchant's historical average ----
    history = (
        db.query(Document)
        .filter(
            Document.id != doc.id,
            Document.merchant_name == doc.merchant_name,
            Document.grand_total.isnot(None),
            Document.status.in_(["extracted", "reviewed"]),
        )
        .all()
    )
    if len(history) >= 3:
        totals = [float(h.grand_total) for h in history if h.grand_total]
        avg = sum(totals) / len(totals)
        if avg > 0 and grand_total > avg * 5:
            flags.append(
                {
                    "type": "unusual_amount",
                    "label": "ยอดรวมสุทธิสูงผิดปกติ",
                    "severity": "high",
                    "detail": (
                        f"ยอดรวม ฿{grand_total:,.2f} สูงกว่าค่าเฉลี่ยของร้านนี้ "
                        f"(฿{avg:,.2f} จาก {len(history)} เอกสาร) มากกว่า 5 เท่า"
                    ),
                }
            )
        elif avg > 0 and grand_total > avg * 2:
            flags.append(
                {
                    "type": "unusual_amount",
                    "label": "ยอดรวมสุทธิค่อนข้างสูง",
                    "severity": "medium",
                    "detail": (
                        f"ยอดรวม ฿{grand_total:,.2f} สูงกว่าค่าเฉลี่ยของร้านนี้ "
                        f"(฿{avg:,.2f}) ประมาณ {grand_total/avg:.1f} เท่า"
                    ),
                }
            )

    # ---- Date-in-future check (backup — Gemini also catches it) ----
    if doc.document_date:
        try:
            doc_date = datetime.strptime(doc.document_date, "%Y-%m-%d").date()
            today = date.today()
            if doc_date > today:
                flags.append(
                    {
                        "type": "future_date",
                        "label": "วันที่ในอนาคต",
                        "severity": "high",
                        "detail": f"วันที่ในเอกสาร ({doc.document_date}) อยู่หลังวันนี้ ({today.isoformat()})",
                    }
                )
        except ValueError:
            pass

    return flags


def merge_fraud_results(
    gemini_block: dict | None,
    history_flags: list[dict],
) -> str | None:
    """Combine Gemini's self-contained analysis with Python-computed flags.

    Recomputes the overall risk_level so history-based high/medium flags lift
    the final level appropriately.
    """
    flags: list[dict] = []
    ai_analysis = {"risk_score": 0.0, "risk_level": "low", "summary": ""}

    if gemini_block:
        flags.extend(gemini_block.get("flags", []))
        ai_analysis = gemini_block.get("ai_analysis", ai_analysis)

    seen_labels = {f.get("label") for f in flags if f.get("label")}
    for f in history_flags:
        if f.get("label") not in seen_labels:
            flags.append(f)
            seen_labels.add(f.get("label"))

    severities = [f.get("severity") for f in flags]
    if "high" in severities:
        new_level = "high"
        risk_floor = 0.7
    elif "medium" in severities:
        new_level = "medium"
        risk_floor = 0.4
    else:
        new_level = ai_analysis.get("risk_level", "low")
        risk_floor = ai_analysis.get("risk_score", 0.0)

    ai_analysis["risk_score"] = max(float(ai_analysis.get("risk_score", 0.0)), risk_floor)
    ai_analysis["risk_level"] = new_level

    if not flags and not ai_analysis.get("summary"):
        return None

    return json.dumps(
        {"flags": flags, "ai_analysis": ai_analysis},
        ensure_ascii=False,
    )
