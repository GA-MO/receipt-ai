"""AI-powered fraud detection using Gemini."""

import json
import logging
from datetime import UTC, datetime

from google.genai import types
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Document

logger = logging.getLogger(__name__)

FRAUD_ANALYSIS_PROMPT = """\
คุณเป็น AI ผู้เชี่ยวชาญด้านการตรวจสอบเอกสารทางการเงินและป้องกันการทุจริต

วันที่วันนี้คือ {today}

วิเคราะห์เอกสารต่อไปนี้ว่ามีสิ่งผิดปกติหรือน่าสงสัยหรือไม่:

## เอกสารปัจจุบัน
{current_doc}

## ประวัติเอกสารจากร้านค้าเดียวกัน (ล่าสุด 10 รายการ)
{merchant_history}

## กรุณาวิเคราะห์และตอบเป็น JSON ตาม format นี้เท่านั้น:
{{
  "risk_score": 0.0,
  "risk_level": "low",
  "summary": "สรุปผลวิเคราะห์เป็นภาษาไทย 1-2 ประโยค",
  "flags": [
    {{
      "type": "ai_analysis",
      "label": "ชื่อประเด็นสั้นๆ",
      "severity": "high|medium|low",
      "detail": "อธิบายรายละเอียดเป็นภาษาไทย"
    }}
  ]
}}

กฎสำคัญ:
- risk_score: 0.0 (ปลอดภัย) ถึง 1.0 (น่าสงสัยมาก)
- risk_level: "low" (< 0.3), "medium" (0.3-0.6), "high" (> 0.6)
- ถ้าไม่พบสิ่งผิดปกติ ให้ flags เป็น [] และ summary อธิบายว่าปกติ
- วิเคราะห์จาก: เลขที่เอกสารซ้ำ, ใบเสร็จร้านเดียวกันวันเดียวกันยอดใกล้เคียง,
  ยอดเงินผิดปกติเทียบกับประวัติร้าน, ความถี่ซื้อ, ประเภทสินค้าไม่สอดคล้องกับร้าน,
  รายการซ้ำซ้อน, ยอดเงินกลมผิดธรรมชาติ, วันที่เป็นวันหยุด,
  confidence ต่ำ, pattern ที่ไม่สมเหตุสมผล
- ตอบเป็น JSON เท่านั้น ห้ามมี markdown code fence หรือข้อความอื่น
"""


def _format_doc_for_ai(doc: Document) -> str:
    """Format a document's data for the AI fraud prompt."""
    items_str = "ไม่มีรายการ"
    if doc.items:
        lines = []
        for it in doc.items:
            lines.append(
                f"  - {it.product_name_raw or '?'}: "
                f"{it.quantity or '?'} {it.unit or ''} × ฿{float(it.unit_price or 0):,.2f} = ฿{float(it.line_total or 0):,.2f}"
            )
        items_str = "\n".join(lines)

    return (
        f"ร้านค้า: {doc.merchant_name or 'ไม่ระบุ'}\n"
        f"เลขที่: {doc.document_number or 'ไม่ระบุ'}\n"
        f"วันที่: {doc.document_date or 'ไม่ระบุ'}\n"
        f"หมวดหมู่: {doc.category or 'ไม่ระบุ'}\n"
        f"ยอดก่อนภาษี: ฿{float(doc.subtotal or 0):,.2f}\n"
        f"ส่วนลด: ฿{float(doc.discount or 0):,.2f}\n"
        f"VAT: ฿{float(doc.vat or 0):,.2f}\n"
        f"ยอดรวมสุทธิ: ฿{float(doc.grand_total or 0):,.2f}\n"
        f"AI Confidence: {(doc.confidence or 0) * 100:.0f}%\n"
        f"จำนวนรายการสินค้า: {len(doc.items)}\n"
        f"รายการสินค้า:\n{items_str}"
    )


def _format_history(docs: list[Document]) -> str:
    """Format merchant history for the AI prompt."""
    if not docs:
        return "ไม่มีประวัติ (เอกสารแรกจากร้านนี้)"
    lines = []
    for d in docs:
        lines.append(
            f"- {d.document_date or '?'} | ฿{float(d.grand_total or 0):,.2f} | "
            f"{d.category or '?'} | {len(d.items)} รายการ"
        )
    return "\n".join(lines)


def run_fraud_detection(doc: Document, db: Session) -> str | None:
    """Run AI fraud detection and return JSON string."""
    if not doc.grand_total or float(doc.grand_total) <= 0:
        return None

    from .extraction import _get_client

    history = (
        db.query(Document)
        .filter(
            Document.merchant_name == doc.merchant_name,
            Document.id != doc.id,
            Document.status.in_(["extracted", "reviewed"]),
            Document.merchant_name.isnot(None),
        )
        .order_by(Document.document_date.desc())
        .limit(10)
        .all()
    )

    prompt = FRAUD_ANALYSIS_PROMPT.format(
        today=datetime.now(UTC).strftime("%Y-%m-%d"),
        current_doc=_format_doc_for_ai(doc),
        merchant_history=_format_history(history),
    )

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
        data = json.loads(response.text.strip())

        flags = [
            {
                "type": f.get("type", "ai_analysis"),
                "label": f.get("label", "AI วิเคราะห์"),
                "severity": f.get("severity", "low"),
                "detail": f.get("detail", ""),
            }
            for f in data.get("flags", [])
        ]

        ai_result = {
            "risk_score": data.get("risk_score", 0.0),
            "risk_level": data.get("risk_level", "low"),
            "summary": data.get("summary", ""),
        }

        logger.info(
            "AI fraud analysis for %s: risk=%.2f (%s), flags=%d",
            doc.id,
            ai_result["risk_score"],
            ai_result["risk_level"],
            len(flags),
        )

        output = {"flags": flags, "ai_analysis": ai_result}
        return json.dumps(output, ensure_ascii=False)

    except Exception as exc:
        logger.warning("AI fraud analysis failed for %s: %s", doc.id, exc)
        return None
