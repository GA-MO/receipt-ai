"""Agentic multi-turn extraction using Gemini function calling.

Flow
----
1. Send image + slim system prompt (no embedded catalog, no fraud rules).
2. Gemini may call any of:
   * ``lookup_catalog(query)`` — we match + return top-N candidates
   * ``check_merchant_history(merchant_name)`` — we return DB summary
3. Eventually Gemini calls ``emit_extraction`` with the final structured
   output, then optionally ``emit_fraud_analysis``.
4. Loop ends when both finalizers are called, or iteration cap reached.

Compared to the prompt-only "combined" mode this:
* Keeps PRODUCT_CATALOG out of the prompt (cheaper per call)
* Lets Gemini pull merchant history inline (better fraud signals)
* Costs more latency — 2-4 tool roundtrips per doc

Toggled via ``settings.extraction_mode == 'agentic'``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from google.genai import types
from sqlalchemy.orm import Session

from ..config import settings
from ..schemas import ExtractionResult
from .extraction import _MIME_MAP, parse_extraction_payload
from .extraction_tools import TOOL_HANDLERS, build_tool_declarations
from .llm_client import get_gemini_client

logger = logging.getLogger(__name__)


_AGENTIC_SYSTEM_INSTRUCTION_TEMPLATE = """\
คุณเป็น AI ผู้เชี่ยวชาญในการอ่านและวิเคราะห์เอกสารการขายภาษาไทย
เช่น ใบเสร็จรับเงิน บิลเงินสด ใบกำกับภาษี และใบส่งของ
รวมถึงเอกสารที่เขียนด้วยลายมือ

## Tools ที่ใช้ได้
- `lookup_catalog(query)` — ค้นหาสินค้าในตาราง PRODUCT_CATALOG เครือบุญรอด
  เรียกสำหรับ **ทุกชื่อสินค้า** ที่อ่านได้จากเอกสาร (batch ได้ 1 ครั้งต่อ item)
  เพื่อ map เป็นชื่อทางการ หรือยืนยันว่าไม่อยู่ใน catalog
- `check_merchant_history(merchant_name)` — ดึงประวัติเอกสารของร้านค้า
  เรียก **1 ครั้ง** หลังจาก identify merchant ได้เพื่อใช้วิเคราะห์ fraud
  (เอกสารซ้ำ, ยอดผิดปกติ vs ค่าเฉลี่ย)
- `emit_extraction(...)` — ส่งผลลัพธ์สุดท้ายเมื่อครบ
- `emit_fraud_analysis(...)` — ส่งการวิเคราะห์ fraud เป็นสิ่งสุดท้าย

## ขั้นตอนที่ต้องทำตาม
1. อ่านเอกสาร ระบุ merchant_name + รายการสินค้าทั้งหมด
2. เรียก `lookup_catalog` สำหรับแต่ละรายการสินค้า (ข้ามได้ถ้ามั่นใจว่าไม่ใช่สินค้าเครือบุญรอด)
3. เรียก `check_merchant_history` ถ้ารู้ merchant_name
4. เรียก `emit_extraction` ด้วยข้อมูลที่ประมวลผลแล้ว
5. เรียก `emit_fraud_analysis` วิเคราะห์จากข้อมูลเอกสาร + ประวัติ (ถ้ามี)

## กฎสำคัญ
- ข้อความคำอธิบายทั้งหมด (notes, summary, flags) ต้องเป็นภาษาไทย 100%
- `product_name_normalized` ใช้ชื่อจาก `lookup_catalog` match ที่ดีที่สุด
  ถ้า score < 75 ใช้ชื่อจากเอกสาร (ตัด unit/suffix ออก)
- `product_code` ใช้ field `code` จาก `lookup_catalog` match เดียวกัน — เฉพาะเมื่อ score ≥ 85
  ถ้าไม่มี match ที่มั่นใจ → ละไว้ null (ห้ามแต่งรหัสเอง, ห้ามใช้บาร์โค้ดบนใบเสร็จ)
- `category` ของแต่ละ item: ใช้ 1 ใน 4 หมวด Singha Online
  * "เครื่องดื่ม" — เบียร์, น้ำดื่ม, โซดา, สุรา, น้ำแร่, น้ำอัดลม, ชา, กาแฟ
  * "อาหาร และของว่าง" — อาหาร, ขนม, snack
  * "สินค้าพรีเมียมสิงห์" — merchandise, ของสะสม
  * "สินค้าอื่นๆ" — ไม่เข้าหมวดข้างบน (ไม่ใช่ default)
- `category` ของเอกสาร: ใช้หมวดที่พบมากที่สุดใน items (by line_total)
- ถ้าปี พ.ศ. ให้แปลงเป็น ค.ศ. (พ.ศ. - 543)
- วันที่รูปแบบ YYYY-MM-DD
- merchant_normalized: ตัด prefix "บริษัท/ร้าน/หจก.", suffix "จำกัด/(สำนักงานใหญ่)"

## กฎการวิเคราะห์ fraud
**วันที่วันนี้คือ __TODAY__** — ใช้เป็นฐานเปรียบเทียบสำหรับวันที่ในเอกสาร

- risk_score: 0-1; level: low (<0.3), medium (0.3-0.6), high (>0.6)

### flag เฉพาะเคสที่ผิดปกติ "จริง ๆ" เท่านั้น
- HIGH:
  * วันที่เอกสาร **หลัง** __TODAY__ (อนาคต)
  * วันที่เอกสารเก่ากว่า __TODAY__ มากกว่า 5 ปี
  * เอกสารซ้ำ (ร้าน+วัน+ยอด ตรงกับประวัติที่ได้จาก check_merchant_history)
  * ยอดสูงกว่าค่าเฉลี่ย history > 5 เท่า
  * confidence < 0.4
- MEDIUM:
  * VAT คำนวณผิดเกิน 5%
  * ยอดสูงกว่า avg history 2-5 เท่า
  * ยอดรายการสินค้ารวมไม่ตรงกับ grand_total เกิน 10%
- LOW: confidence 0.4-0.6, ข้อสังเกตเล็กน้อย

### 🚫 ห้าม flag (เป็นเรื่องปกติของธุรกิจ)
- ไม่มีเลขที่เอกสาร (ร้านเล็กไม่ค่อยออก)
- ยอดเงินกลม (฿5,000 ฿10,000) — ปกติสำหรับสั่งเป็นลัง
- ชื่อย่อ/ลายมือ/OCR variance — เราคาดหมายอยู่แล้ว
- confidence ≥ 0.7
- เอกสารที่ดูปกติทุกอย่าง

### ⚠️ กฎสำคัญที่สุด
**ถ้าเอกสารดูปกติทุกอย่าง ต้องตอบ `emit_fraud_analysis(risk_score=0.0, risk_level="low", summary="ไม่พบความผิดปกติ", flags=[])`**
**อย่าคิดหา flag มาใส่เพื่อดูขยัน** — ใบเสร็จส่วนใหญ่ในระบบเป็นเอกสารปกติ ไม่มี fraud
ถ้าไม่แน่ใจว่าจะ flag ดีหรือไม่ — **อย่า flag**

ห้ามตอบข้อความปกติ — ต้องเรียก tool ทุก turn
"""


def _build_system_instruction() -> str:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return _AGENTIC_SYSTEM_INSTRUCTION_TEMPLATE.replace("__TODAY__", today)


@dataclass
class AgenticResult:
    extraction: ExtractionResult
    fraud_payload: dict | None
    tool_calls: list[str] = field(default_factory=list)
    iterations: int = 0


def _extract_tool_calls(candidate) -> list[types.FunctionCall]:
    content = getattr(candidate, "content", None)
    parts = getattr(content, "parts", None) or []
    return [p.function_call for p in parts if getattr(p, "function_call", None)]


def _call_handler(name: str, args: dict, db: Session) -> dict:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return {"error": f"unknown tool {name}"}
    try:
        result = handler(db=db, **args)
        return result if isinstance(result, dict) else {"result": result}
    except Exception as exc:
        logger.warning("Tool %s raised: %s", name, exc)
        return {"error": str(exc)}


def extract_agentic(file_path: str, db: Session, max_iterations: int = 8) -> AgenticResult:
    """Run the multi-turn agentic extraction loop.

    NOTE: this path uses Gemini-native function calling and is not yet ported
    to OpenRouter. If ``LLM_PROVIDER=openrouter`` is set, choose another
    ``EXTRACTION_MODE`` (combined/legacy) instead.
    """
    if settings.llm_provider != "gemini":
        raise RuntimeError(
            "extraction_mode='agentic' รองรับเฉพาะ LLM_PROVIDER=gemini "
            f"(ปัจจุบันเป็น {settings.llm_provider}). ใช้ extraction_mode='combined' แทน"
        )

    path = Path(file_path)
    mime_type = _MIME_MAP.get(path.suffix.lower(), "image/jpeg")
    file_data = path.read_bytes()

    image_part = types.Part.from_bytes(data=file_data, mime_type=mime_type)

    # Initial user turn: image + task
    contents: list[types.Content] = [
        types.Content(
            role="user",
            parts=[
                types.Part(text="ดึงข้อมูลใบเสร็จรับเงินในรูปนี้ตามขั้นตอนที่กำหนด"),
                image_part,
            ],
        )
    ]

    client = get_gemini_client()
    tools = build_tool_declarations()
    # Force Gemini to always make a tool call — this prevents it from emitting
    # plain text mid-flow and derailing the loop.
    tool_config = types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(mode="ANY")
    )
    config = types.GenerateContentConfig(
        system_instruction=_build_system_instruction(),
        tools=tools,
        tool_config=tool_config,
        temperature=0.1,
    )

    extraction_payload: dict | None = None
    fraud_payload: dict | None = None
    tool_log: list[str] = []

    for i in range(max_iterations):
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=contents,
            config=config,
        )
        if not response.candidates:
            raise RuntimeError("Gemini returned no candidates")

        candidate = response.candidates[0]
        calls = _extract_tool_calls(candidate)
        if not calls:
            # No tool call — Gemini may have responded with plain text. If we already
            # have emit_extraction data, we're done; otherwise force a retry.
            logger.warning(
                "Agentic iter %d: no tool_call in response (text=%s)",
                i,
                (getattr(candidate.content, "parts", None) or [""])[0],
            )
            if extraction_payload:
                break
            raise RuntimeError("AI ไม่เรียก tool แต่ยังไม่มี extraction; ลอง rerun")

        # Append Gemini's turn to history (must be a single Content).
        contents.append(candidate.content)

        tool_response_parts: list[types.Part] = []
        should_break = False
        for call in calls:
            name = call.name
            args = dict(call.args or {})
            tool_log.append(name)
            logger.info("Agentic iter %d: Gemini called %s(%s)", i, name, list(args.keys()))

            if name == "emit_extraction":
                extraction_payload = args
                tool_response_parts.append(
                    types.Part.from_function_response(
                        name=name,
                        response={"status": "received"},
                    )
                )
            elif name == "emit_fraud_analysis":
                fraud_payload = args
                tool_response_parts.append(
                    types.Part.from_function_response(
                        name=name,
                        response={"status": "received"},
                    )
                )
                # Once fraud is emitted (and extraction already is), we're done.
                if extraction_payload is not None:
                    should_break = True
            else:
                result = _call_handler(name, args, db)
                tool_response_parts.append(
                    types.Part.from_function_response(
                        name=name,
                        response=result,
                    )
                )

        contents.append(types.Content(role="user", parts=tool_response_parts))

        if should_break:
            break

        # Safety: if only emit_extraction has been called and Gemini isn't continuing,
        # nudge it explicitly on the next turn.
        if (
            extraction_payload is not None
            and not fraud_payload
            and i >= max_iterations - 2
        ):
            break

    iterations_used = i + 1

    if extraction_payload is None:
        raise RuntimeError("Agentic loop ended without emit_extraction")

    extraction = parse_extraction_payload(extraction_payload)
    logger.info(
        "Agentic extract complete in %d iterations (tools=%s): merchant=%s, conf=%.2f",
        iterations_used,
        tool_log,
        extraction.merchant_name,
        extraction.confidence,
    )

    # Normalize fraud payload shape to match other modes.
    normalized_fraud: dict | None = None
    if fraud_payload:
        flags = fraud_payload.get("flags") or []
        normalized_fraud = {
            "flags": [
                {
                    "type": f.get("type", "ai_analysis"),
                    "label": f.get("label", ""),
                    "severity": f.get("severity", "low"),
                    "detail": f.get("detail", ""),
                }
                for f in flags
                if isinstance(f, dict)
            ],
            "ai_analysis": {
                "risk_score": float(fraud_payload.get("risk_score") or 0.0),
                "risk_level": fraud_payload.get("risk_level") or "low",
                "summary": fraud_payload.get("summary") or "",
            },
        }

    return AgenticResult(
        extraction=extraction,
        fraud_payload=normalized_fraud,
        tool_calls=tool_log,
        iterations=iterations_used,
    )
