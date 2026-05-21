"""Agentic multi-turn extraction using Gemini function calling.

Flow
----
1. Send image + slim system prompt (no embedded catalog).
2. Gemini may call ``lookup_catalog(query)`` — we match + return top-N candidates.
3. Gemini calls ``emit_extraction`` with the final structured output.
4. Loop ends when emit_extraction is called, or iteration cap reached.

Compared to the prompt-only mode this:
* Keeps PRODUCT_CATALOG out of the prompt (cheaper per call)
* Costs more latency — 2-4 tool roundtrips per doc

Toggled via ``settings.extraction_mode == 'agentic'``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from google.genai import types
from sqlalchemy.orm import Session

from ..config import settings
from ..schemas import ExtractionResult
from .extraction import _MIME_MAP, parse_extraction_payload
from .extraction_tools import TOOL_HANDLERS, build_tool_declarations
from .llm_client import get_gemini_client

logger = logging.getLogger(__name__)


_AGENTIC_SYSTEM_INSTRUCTION = """\
คุณเป็น AI ผู้เชี่ยวชาญในการอ่านและวิเคราะห์เอกสารการขายภาษาไทย
เช่น ใบเสร็จรับเงิน บิลเงินสด ใบกำกับภาษี และใบส่งของ
รวมถึงเอกสารที่เขียนด้วยลายมือ

## Tools ที่ใช้ได้
- `lookup_catalog(query)` — ค้นหาสินค้าใน PRODUCT_CATALOG (เครือบุญรอด + คู่แข่งที่ระบบรู้จัก)
  เรียกสำหรับ **ทุกชื่อสินค้า** ที่อ่านได้จากเอกสาร เพื่อ map เป็นชื่อทางการ
  หรือยืนยันว่าไม่อยู่ใน catalog
- `emit_extraction(...)` — ส่งผลลัพธ์สุดท้ายเมื่อครบ

## ขั้นตอนที่ต้องทำตาม
1. อ่านเอกสาร ระบุ merchant_name + รายการสินค้าทั้งหมด
2. เรียก `lookup_catalog` สำหรับแต่ละรายการสินค้า รวมทั้งสินค้าคู่แข่ง (ช้าง, ไฮเนเก้น, โค้ก, เป๊ปซี่ ฯลฯ)
3. เรียก `emit_extraction` ด้วยข้อมูลที่ประมวลผลแล้ว

## กฎสำคัญ
- ข้อความคำอธิบายทั้งหมด (notes) ต้องเป็นภาษาไทย 100%
- `product_name_raw` = ชื่อตามที่อ่านได้จากเอกสาร (ก่อน catalog normalization)
- `product_name_normalized`:
  - ถ้ามี catalog match score ≥ 75 → ใช้ชื่อจาก match
  - ไม่งั้น (รวมสินค้าคู่แข่งที่ไม่อยู่ catalog) → ใช้ค่าเดียวกับ raw
- `product_code` = field `code` จาก `lookup_catalog` match — เฉพาะเมื่อ score ≥ 85
  ถ้าไม่มี match ที่มั่นใจ → ละไว้ null (ห้ามแต่งรหัสเอง, ห้ามใช้บาร์โค้ดบนใบเสร็จ)
- `category` ของแต่ละ item: ใช้ 1 ใน 4 หมวด Singha Online
  * "เครื่องดื่ม" — เบียร์, น้ำดื่ม, โซดา, สุรา, น้ำแร่, น้ำอัดลม, ชา, กาแฟ
  * "อาหาร และของว่าง" — อาหาร, ขนม, snack
  * "สินค้าพรีเมียมสิงห์" — merchandise, ของสะสม
  * "สินค้าอื่นๆ" — ไม่เข้าหมวดข้างบน (ไม่ใช่ default)
- `category` ของเอกสาร: ใช้หมวดที่พบมากที่สุดใน items (by line_total)
- ถ้าปี พ.ศ. ให้แปลงเป็น ค.ศ. (พ.ศ. - 543); วันที่รูปแบบ YYYY-MM-DD
- merchant_normalized: ตัด prefix "บริษัท/ร้าน/หจก.", suffix "จำกัด/(สำนักงานใหญ่)"

ห้ามตอบข้อความปกติ — ต้องเรียก tool ทุก turn
"""


@dataclass
class AgenticResult:
    extraction: ExtractionResult
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
        # Tools that don't need DB will ignore the kwarg.
        result = handler(db=db, **args) if "db" in handler.__code__.co_varnames else handler(**args)
        return result if isinstance(result, dict) else {"result": result}
    except Exception as exc:
        logger.warning("Tool %s raised: %s", name, exc)
        return {"error": str(exc)}


def extract_agentic(file_path: str, db: Session, max_iterations: int = 8) -> AgenticResult:
    """Run the multi-turn agentic extraction loop."""
    if settings.llm_provider != "gemini":
        raise RuntimeError(
            "extraction_mode='agentic' รองรับเฉพาะ LLM_PROVIDER=gemini "
            f"(ปัจจุบันเป็น {settings.llm_provider}). ใช้ extraction_mode='default' แทน"
        )

    path = Path(file_path)
    mime_type = _MIME_MAP.get(path.suffix.lower(), "image/jpeg")
    file_data = path.read_bytes()

    image_part = types.Part.from_bytes(data=file_data, mime_type=mime_type)

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
    tool_config = types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(mode="ANY")
    )
    config = types.GenerateContentConfig(
        system_instruction=_AGENTIC_SYSTEM_INSTRUCTION,
        tools=tools,
        tool_config=tool_config,
        temperature=0.1,
    )

    extraction_payload: dict | None = None
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
            logger.warning(
                "Agentic iter %d: no tool_call in response (text=%s)",
                i,
                (getattr(candidate.content, "parts", None) or [""])[0],
            )
            if extraction_payload:
                break
            raise RuntimeError("AI ไม่เรียก tool แต่ยังไม่มี extraction; ลอง rerun")

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

    return AgenticResult(
        extraction=extraction,
        tool_calls=tool_log,
        iterations=iterations_used,
    )
