import json
import logging
import time
from pathlib import Path

from google import genai
from google.genai import types

from ..config import settings
from ..schemas import DocumentItemBase, ExtractionResult

logger = logging.getLogger(__name__)

_client: genai.Client | None = None

PRODUCT_CATEGORIES = [
    "เบียร์",
    "น้ำดื่ม",
    "โซดาและน้ำอัดลม",
    "น้ำแร่",
    "สุรา",
    "เครื่องดื่มอื่นๆ",
    "อาหาร",
    "อื่นๆ",
]

# Boonrawd product catalog with aliases for matching handwritten/abbreviated names
PRODUCT_CATALOG = """
## สินค้าเครือบุญรอด — ใช้ตารางนี้ map ชื่อย่อ/ลายมือ → ชื่อทางการ

| ชื่อทางการ (product_name_normalized) | คำย่อ / ชื่อเล่น / ลายมือที่พบบ่อย | หมวด |
|--------------------------------------|--------------------------------------|------|
| เบียร์สิงห์ขวดใหญ่ | สห์ใหญ่, สิงห์ใหญ่, SINGHA L, สห.ญ, สิงห์ 630, สิงห์แดง | เบียร์ |
| เบียร์สิงห์ขวดเล็ก | สห์เล็ก, สิงห์เล็ก, SINGHA S, สห.ล, สิงห์ 330 | เบียร์ |
| เบียร์สิงห์กระป๋อง | สห์กป, สิงห์กระป๋อง, SINGHA CAN | เบียร์ |
| เบียร์ลีโอขวดใหญ่ | ลีโอใหญ่, LEO L, ลีโอ 630, ล.ญ | เบียร์ |
| เบียร์ลีโอขวดเล็ก | ลีโอเล็ก, LEO S, ลีโอ 330, ล.ล | เบียร์ |
| เบียร์ลีโอกระป๋อง | ลีโอกป, LEO CAN | เบียร์ |
| เบียร์ช้าง | ช้าง, CHANG, ช. | เบียร์ |
| เบียร์ช้างเอสเปรสโซ่ | ช้างเอส, CHANG ESP | เบียร์ |
| เบียร์ยูเบียร์ | U BEER, ยู, UBEER | เบียร์ |
| น้ำดื่มสิงห์ | น้ำสิงห์, นส, SINGHA WATER, สห์น้ำ, น้ำเปล่าสิงห์ | น้ำดื่ม |
| น้ำดื่มสิงห์ 600ml | น้ำสิงห์ 600, สห์600 | น้ำดื่ม |
| น้ำดื่มสิงห์ 1.5L | น้ำสิงห์ 1500, สห์1500 | น้ำดื่ม |
| โซดาสิงห์ | โซดาสห์, SINGHA SODA, โซดา, โซดาขวด | โซดาและน้ำอัดลม |
| น้ำแร่เพอริเอ้ | เพอริเอ้, PERRIER, Perrier | น้ำแร่ |
| น้ำแร่ออร่า | ออร่า, AURA | น้ำแร่ |
| สุราแสงโสม | แสงโสม, SS, Saeng Som, แสง | สุรา |
| สุราหงส์ทอง | หงส์ทอง, หงส์, HT, Hong Thong | สุรา |
| สุราเบลนด์ 285 | เบลนด์, BLEND, 285 | สุรา |
| สุรามิสเตอร์ซี | มิสเตอร์ซี, MR.C, Mr.C | สุรา |
| บี-อิ้ง | B-ing, บีอิ้ง, Bing | เครื่องดื่มอื่นๆ |
| เฮลซ์บลูบอย | เฮลซ์, HELZ, บลูบอย | เครื่องดื่มอื่นๆ |
| สิงห์เลมอนโซดา | เลมอนโซดา, LEMON SODA | โซดาและน้ำอัดลม |
"""

EXTRACTION_PROMPT = """\
คุณเป็น AI ผู้เชี่ยวชาญในการอ่านและวิเคราะห์เอกสารการขายภาษาไทย
เช่น ใบเสร็จรับเงิน บิลเงินสด ใบกำกับภาษี และใบส่งของ
รวมถึงเอกสารที่เขียนด้วยลายมือ

""" + PRODUCT_CATALOG + """

จากรูปเอกสารที่ให้มา กรุณาดึงข้อมูลและตอบเป็น JSON ตาม schema นี้เท่านั้น:

{
  "merchant_name": "ชื่อร้านค้าหรือบริษัท (string | null)",
  "document_number": "เลขที่เอกสาร (string | null)",
  "document_date": "วันที่เอกสาร YYYY-MM-DD (string | null)",
  "category": "หมวดหมู่สินค้า (string)",
  "items": [
    {
      "product_name_raw": "ชื่อสินค้าตามที่ปรากฏในเอกสาร (ลายมือ/ตัวย่อเดิม)",
      "product_name_normalized": "ชื่อทางการจากตาราง PRODUCT_CATALOG (ถ้า match ได้) หรือ null",
      "quantity": 0,
      "unit": "หน่วย เช่น ขวด ลัง แพ็ค กระป๋อง",
      "unit_price": 0.00,
      "line_total": 0.00
    }
  ],
  "subtotal": 0.00,
  "discount": 0.00,
  "vat": 0.00,
  "grand_total": 0.00,
  "confidence": 0.85,
  "notes": "หมายเหตุเพิ่มเติม",
  "needs_review_fields": ["field ที่ไม่มั่นใจ"]
}

กฎสำคัญ:
- product_name_raw: เก็บชื่อตามที่เห็นในเอกสาร (ลายมือ/ตัวย่อ/คำย่อ ตามต้นฉบับ)
- product_name_normalized: map เข้ากับ "ชื่อทางการ" จากตาราง PRODUCT_CATALOG ข้างบน
  ถ้าไม่ตรงกับสินค้าในตาราง ให้ใส่ null
  ถ้าไม่แน่ใจ ให้ใส่ชื่อที่คิดว่าใกล้เคียงที่สุดและเพิ่ม field ใน needs_review_fields
- category ต้องเป็นหนึ่งใน: """ + ", ".join(PRODUCT_CATEGORIES) + """
  วิธีเลือก category:
  1. ดูจาก product_name_normalized ที่ match กับ PRODUCT_CATALOG → ใช้หมวดจากตาราง
  2. ดูจากรายการสินค้าทั้งหมด → ถ้าส่วนใหญ่เป็นเครื่องดื่มแอลกอฮอล์ ให้ใช้ "เบียร์" หรือ "สุรา"
  3. ดูจากชื่อร้านค้า → ถ้ามีคำว่า สุรา, เหล้า, เบียร์, พาณิชย์, เบเวอเรจ, Beverage → น่าจะเป็น เบียร์/สุรา
  4. ถ้าเป็นน้ำดื่ม, น้ำเปล่า, น้ำแร่ → ใช้หมวด น้ำดื่ม/น้ำแร่
  5. ใช้ "อื่นๆ" เฉพาะเมื่อไม่เข้าหมวดใดเลยจริงๆ (ไม่ใช่ default)
- ถ้าเอกสารใช้ปี พ.ศ. ให้แปลงเป็น ค.ศ. (พ.ศ. - 543 = ค.ศ.)
- ถ้าเจอวันที่เช่น 3 เม.ย. 69 ให้แปลงเป็น 2026-04-03
- ถ้าอ่านไม่ออกหรือไม่แน่ใจ ให้ใส่ null และเพิ่มชื่อ field ใน needs_review_fields
- ตัวเลขเงินให้เป็นทศนิยม 2 ตำแหน่ง
- confidence เป็นค่า 0.0 - 1.0 แสดงความมั่นใจโดยรวม
- ถ้าเอกสารไม่ใช่ใบเสร็จ/บิลเงินสด/ใบกำกับภาษี/ใบส่งของ (เช่น เป็นรายงานสรุปยอด, สลิปโอนเงิน, เอกสารอื่น) ให้:
  * ยังคงพยายามดึงข้อมูลให้ได้มากที่สุด
  * ตั้ง confidence ต่ำ (0.3-0.6) ตามความเหมาะสม
  * ระบุใน notes ว่าเอกสารนี้เป็นประเภทอะไร เช่น "เอกสารนี้เป็นรายงานสรุปยอดขาย ไม่ใช่ใบเสร็จรับเงิน"
  * เพิ่ม "document_type" ใน needs_review_fields
- ถ้ามีหลายหน้าหรือหลายรายการที่เป็นสรุปรวม ให้ดึงรายการแต่ละบรรทัดเป็น item แยก
- ตอบเป็น JSON เท่านั้น ห้ามมี markdown code fence หรือข้อความอื่น
"""


_MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}


def _get_client() -> genai.Client:
    """Get or create the Gemini client (lazy init, auto-refresh on auth error)."""
    global _client
    if _client is not None:
        return _client

    if settings.gemini_api_key:
        _client = genai.Client(api_key=settings.gemini_api_key)
        logger.info("Gemini client configured via API key")
    elif settings.gcp_credentials_path:
        _client = _create_vertex_client()
    else:
        raise RuntimeError(
            "ต้องตั้งค่า GEMINI_API_KEY หรือ GCP_CREDENTIALS_PATH อย่างน้อย 1 อย่าง"
        )
    return _client


def _create_vertex_client() -> genai.Client:
    """Create a Vertex AI client with fresh credentials."""
    import os

    os.environ.setdefault(
        "GOOGLE_APPLICATION_CREDENTIALS", settings.gcp_credentials_path
    )
    import google.auth
    from google.auth.transport.requests import Request

    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    credentials, project = google.auth.default(scopes=scopes)
    credentials.refresh(Request())
    project = settings.gcp_project_id or project

    client = genai.Client(
        vertexai=True,
        project=project,
        location=settings.gcp_location,
        credentials=credentials,
    )
    logger.info("Gemini client configured via Vertex AI (project=%s)", project)
    return client


def _reset_client() -> None:
    """Reset the client so the next call creates a fresh one (e.g. on auth error)."""
    global _client
    _client = None
    logger.info("Gemini client reset — will re-create on next call")


def _call_gemini_with_retry(contents: list, config: types.GenerateContentConfig) -> str:
    """Call Gemini API with retry logic for transient failures."""
    last_error: Exception | None = None

    for attempt in range(1, settings.gemini_max_retries + 1):
        client = _get_client()
        try:
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=contents,
                config=config,
            )
            return response.text.strip()
        except Exception as exc:
            last_error = exc
            is_auth_error = "401" in str(exc) or "403" in str(exc) or "credentials" in str(exc).lower()
            logger.warning(
                "Gemini API attempt %d/%d failed: %s",
                attempt,
                settings.gemini_max_retries,
                exc,
            )
            if is_auth_error:
                _reset_client()
            if attempt < settings.gemini_max_retries:
                delay = settings.gemini_retry_delay * (2 ** (attempt - 1))
                time.sleep(delay)

    raise RuntimeError(
        f"Gemini API failed after {settings.gemini_max_retries} attempts: {last_error}"
    )


def extract_receipt(file_path: str) -> ExtractionResult:
    """Extract structured data from a receipt image/PDF using Gemini Vision."""
    path = Path(file_path)
    mime_type = _MIME_MAP.get(path.suffix.lower(), "image/jpeg")
    file_data = path.read_bytes()

    image_part = types.Part.from_bytes(data=file_data, mime_type=mime_type)
    contents = [EXTRACTION_PROMPT, image_part]

    config = types.GenerateContentConfig(
        temperature=0.1,
        response_mime_type="application/json",
    )

    logger.info("Extracting receipt: %s (%s, %d bytes)", path.name, mime_type, len(file_data))

    raw_text = _call_gemini_with_retry(contents, config)

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.error("Gemini returned invalid JSON: %s", raw_text[:500])
        raise RuntimeError(f"AI ตอบ JSON ไม่ถูกต้อง: {exc}") from exc

    # Handle Gemini returning an array instead of an object
    if isinstance(data, list):
        data = data[0] if data and isinstance(data[0], dict) else {}
        logger.warning("Gemini returned array instead of object, using first element")

    raw_items = data.get("items", [])
    # Handle nested list e.g. [[item1, item2]]
    if raw_items and isinstance(raw_items[0], list):
        raw_items = raw_items[0]

    items = [
        DocumentItemBase(
            product_name_raw=it.get("product_name_raw"),
            product_name_normalized=it.get("product_name_normalized"),
            quantity=it.get("quantity"),
            unit=it.get("unit"),
            unit_price=it.get("unit_price"),
            line_total=it.get("line_total"),
        )
        for it in raw_items
        if isinstance(it, dict)
    ]

    # Validate category is one of the allowed values
    raw_category = data.get("category")
    category = raw_category if raw_category in PRODUCT_CATEGORIES else "อื่นๆ"

    result = ExtractionResult(
        merchant_name=data.get("merchant_name"),
        document_number=data.get("document_number"),
        document_date=data.get("document_date"),
        category=category,
        items=items,
        subtotal=data.get("subtotal"),
        discount=data.get("discount"),
        vat=data.get("vat"),
        grand_total=data.get("grand_total"),
        confidence=data.get("confidence", 0.0),
        notes=data.get("notes"),
        needs_review_fields=data.get("needs_review_fields", []),
    )

    logger.info(
        "Extraction complete: merchant=%s, total=%s, confidence=%.2f, items=%d",
        result.merchant_name,
        result.grand_total,
        result.confidence,
        len(result.items),
    )

    return result
