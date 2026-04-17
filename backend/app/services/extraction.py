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

_CATEGORY_SET = set(PRODUCT_CATEGORIES)

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
| โซดาสิงห์ | โซดาสห์, SINGHA SODA, SODAPP, โซดา, โซคา, โซดาขวด, โซดาเปลี่ยน, โซดาถาด, โซดาเปลี่ยน/ถาด, โซดาเปล่า/ถาด | โซดาและน้ำอัดลม |
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

SYSTEM_INSTRUCTION = """\
คุณเป็น AI ผู้เชี่ยวชาญในการอ่านและวิเคราะห์เอกสารการขายภาษาไทย
เช่น ใบเสร็จรับเงิน บิลเงินสด ใบกำกับภาษี และใบส่งของ
รวมถึงเอกสารที่เขียนด้วยลายมือ

""" + PRODUCT_CATALOG + """

## JSON Schema ที่ต้องตอบกลับ (เท่านั้น ห้ามเพิ่ม markdown/fence)
{
  "merchant_name": "ชื่อร้านค้าหรือบริษัท (string | null)",
  "merchant_normalized": "ชื่อร้านแบบสะอาด ตัด prefix/suffix เช่น 'ร้าน', 'บริษัท', 'จำกัด', 'หจก.' ออก (string | null)",
  "document_number": "เลขที่เอกสาร (string | null)",
  "document_date": "วันที่เอกสาร YYYY-MM-DD (string | null)",
  "category": "หมวดหมู่สินค้ารวมของเอกสาร (string)",
  "items": [
    {
      "product_name_normalized": "ชื่อสินค้า — ถ้า match กับตาราง PRODUCT_CATALOG ให้ใช้ 'ชื่อทางการ' จากตาราง; ถ้าไม่ match ให้ใช้ชื่อที่อ่านได้จากเอกสาร (ตัด unit/suffix อย่าง 'ลัง'/'เปลี่ยน/ถาด' ออก)",
      "category": "หมวดหมู่ของรายการนี้ (string จาก allowed categories)",
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

## กฎสำคัญ
- **ภาษาที่ใช้ตอบ** : ข้อความทุก field ที่เป็นคำอธิบาย/หมายเหตุ (`notes`, `needs_review_fields` ถ้าต้องอธิบาย)
  **ต้องเป็นภาษาไทย 100% เท่านั้น** ห้ามใช้ภาษาอังกฤษในการอธิบาย
  - ตัวเลข / ชื่อสินค้า / ชื่อร้าน สามารถคงภาษาอังกฤษได้ถ้าต้นฉบับเป็นภาษาอังกฤษ
  - แต่ "คำอธิบาย" ต้องเขียนเป็นไทยเสมอ เช่น ถ้ายอดรวมลายมือไม่ตรงกับการคำนวณ ต้องเขียนแบบ
    "ยอดรวมที่เขียนด้วยลายมือ (16,905) ไม่ตรงกับยอดคำนวณ (16,105) ใช้ยอดคำนวณแทน"
    ห้ามเขียนเป็น "The handwritten grand total is inconsistent..."
- `product_name_normalized` : ชื่อสินค้าที่จะแสดง **(field เดียวสำหรับชื่อ — ไม่มี raw แล้ว)**
  - ลำดับความสำคัญ:
    1. ถ้า match กับตาราง PRODUCT_CATALOG (หรือเพียงพอที่จะเดา) → ใช้ **ชื่อทางการ** จากตาราง เช่น "เบียร์สิงห์ขวดใหญ่", "โซดาสิงห์"
    2. ถ้าไม่ match catalog → ใช้ชื่อที่อ่านได้จากเอกสาร แต่ **ตัด suffix/unit ที่ไม่ใช่ชื่อสินค้า** ออก (เช่น "เปลี่ยน/ถาด", "เปล่า", "/ลัง")
    3. ห้าม null ตราบใดที่อ่านเอกสารออก — ถ้าอ่านไม่ออกจริง ๆ ให้ใส่ "?" และเพิ่ม `product_name_normalized` ใน `needs_review_fields`
- **คำต่อท้ายสินค้าที่ไม่ใช่ส่วนของชื่อ** : คำเหล่านี้อธิบาย **รูปแบบการขาย/การบรรจุ** ไม่ใช่ชื่อสินค้า
  ให้ละทิ้งคำเหล่านี้เวลา map ไป product_name_normalized และเวลาจัด category
  - "เปลี่ยน" / "เปล่า" / "ถาด" / "เปลี่ยน/ถาด" / "เปล่า/ถาด" → หมายถึงขายแบบเปลี่ยนลัง/คืนลังเปล่า (returnable crate)
  - "ลัง" / "กระป๋อง" / "ขวด" / "แพ็ค" → เป็น **unit** ให้ใส่ใน field `unit` ไม่ใช่ชื่อสินค้า
  - ตัวอย่าง: "SODAPP โซดาเปลี่ยน/ถาด" = โซดาสิงห์ (ขายแบบเปลี่ยนถาด) → category "โซดาและน้ำอัดลม", normalized = "โซดาสิงห์"
  - ตัวอย่าง: "เบียร์สิงห์เปลี่ยนขวด" = เบียร์สิงห์ (คืนขวดเปล่า) → category "เบียร์"
- **Typo ที่พบบ่อย** (OCR/ลายมืออ่านผิด) — ให้ตีความเป็นคำที่ถูกต้อง:
  - "โซคา" → "โซดา"
  - "ลิโอ" → "ลีโอ"
  - "สห์" → "สิงห์"
  - "ดัง" (ในบริบทของหน่วยสินค้า) → "ลัง"
- `merchant_normalized` : ชื่อร้านที่ตัด noise ออกแล้ว ต้องตัดคำต่อไปนี้ออก **ทั้งหมด**:
  - prefix: "ร้าน", "บริษัท", "หจก.", "บจก.", "ห้างหุ้นส่วนจำกัด"
  - suffix: "จำกัด", "จก.", "(มหาชน)", "Co., Ltd.", "Inc.", "LLC"
  - ข้อมูลสาขา/สำนักงาน: "(สำนักงานใหญ่)", "(สนญ.)", "(HQ)", "สาขา..."
  - เว้นวรรคส่วนเกิน
  ตัวอย่าง:
  - "บริษัท ก.เจริญ พาณิชย์ จำกัด" → "ก.เจริญ พาณิชย์"
  - "บริษัท มิตรราชบุรีเทรดดิ้ง จำกัด (สำนักงานใหญ่)" → "มิตรราชบุรีเทรดดิ้ง"
  - "ห้างหุ้นส่วนจำกัด รวยสุรา สาขาบางนา" → "รวยสุรา"
- `items[].category` และ `category` (เอกสาร) ต้องเป็นหนึ่งใน: """ + ", ".join(PRODUCT_CATEGORIES) + """
  วิธีเลือก category ของแต่ละรายการ (items[].category):
    1. ดูจาก product_name_normalized ที่ match กับ PRODUCT_CATALOG → ใช้หมวดจากตาราง
    2. ถ้าเป็นเบียร์/ลีโอ/ช้าง/สิงห์/U-Beer → "เบียร์"
    3. ถ้าเป็นสุรา/แสงโสม/หงส์ทอง/เบลนด์/เหล้า → "สุรา"
    4. ถ้าเป็นน้ำดื่ม/น้ำเปล่า → "น้ำดื่ม"
    5. ถ้าเป็นโซดา/น้ำอัดลม → "โซดาและน้ำอัดลม"
    6. ถ้าเป็นน้ำแร่/Perrier/Aura → "น้ำแร่"
    7. ถ้าเป็นอาหาร → "อาหาร"
    8. ใช้ "อื่นๆ" เฉพาะเมื่อไม่เข้าหมวดใดเลยจริงๆ (ไม่ใช่ default)
  วิธีเลือก `category` (เอกสาร) : ใช้หมวดที่พบมากที่สุดใน items (by quantity หรือ line_total)
- ถ้าเอกสารใช้ปี พ.ศ. ให้แปลงเป็น ค.ศ. (พ.ศ. - 543 = ค.ศ.)
- ถ้าเจอวันที่เช่น 3 เม.ย. 69 ให้แปลงเป็น 2026-04-03
- ถ้าอ่านไม่ออกหรือไม่แน่ใจ ให้ใส่ null และเพิ่มชื่อ field ใน needs_review_fields
- ตัวเลขเงินให้เป็นทศนิยม 2 ตำแหน่ง
- confidence เป็นค่า 0.0 - 1.0 แสดงความมั่นใจโดยรวม
- ถ้าเอกสารไม่ใช่ใบเสร็จ/บิลเงินสด/ใบกำกับภาษี/ใบส่งของ (เช่น เป็นรายงานสรุปยอด, สลิปโอนเงิน, เอกสารอื่น) ให้:
  * ยังคงพยายามดึงข้อมูลให้ได้มากที่สุด
  * ตั้ง confidence ต่ำ (0.3-0.6) ตามความเหมาะสม
  * ระบุใน notes ว่าเอกสารนี้เป็นประเภทอะไร
  * เพิ่ม "document_type" ใน needs_review_fields
- ถ้ามีหลายหน้าหรือหลายรายการที่เป็นสรุปรวม ให้ดึงรายการแต่ละบรรทัดเป็น item แยก
- ตอบเป็น JSON เท่านั้น ห้ามมี markdown code fence หรือข้อความอื่น
"""

EXTRACTION_PROMPT = (
    "ดึงข้อมูลจากเอกสารในรูปนี้ตาม JSON schema และกฎที่กำหนดไว้ใน system instruction "
    "แล้วตอบกลับเป็น JSON object เดียวเท่านั้น"
)


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


def _coerce_extracted_payload(data: object) -> dict:
    """Normalize Gemini responses that sometimes come back as arrays or nested lists."""
    if isinstance(data, list):
        logger.warning("Gemini returned array instead of object, using first element")
        data = data[0] if data and isinstance(data[0], dict) else {}
    if not isinstance(data, dict):
        return {}
    return data


def _parse_items(raw_items: object, default_category: str | None) -> list[DocumentItemBase]:
    if not isinstance(raw_items, list):
        return []
    # Handle nested list e.g. [[item1, item2]]
    if raw_items and isinstance(raw_items[0], list):
        raw_items = raw_items[0]

    items: list[DocumentItemBase] = []
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        raw_cat = it.get("category")
        cat = raw_cat if raw_cat in _CATEGORY_SET else default_category
        # Backwards compatibility: some older prompts/fixtures return
        # ``product_name_raw`` instead of / alongside ``product_name_normalized``.
        name = it.get("product_name_normalized") or it.get("product_name_raw")
        items.append(
            DocumentItemBase(
                product_name_normalized=name,
                category=cat,
                quantity=it.get("quantity"),
                unit=it.get("unit"),
                unit_price=it.get("unit_price"),
                line_total=it.get("line_total"),
            )
        )
    return items


def parse_extraction_payload(data: object) -> ExtractionResult:
    """Parse a raw JSON payload (already decoded) into an ExtractionResult.

    Isolated from the Gemini call so unit tests can feed in fixture payloads
    without mocking the SDK.
    """
    data = _coerce_extracted_payload(data)

    raw_category = data.get("category")
    category = raw_category if raw_category in _CATEGORY_SET else "อื่นๆ"
    items = _parse_items(data.get("items", []), default_category=category)

    return ExtractionResult(
        merchant_name=data.get("merchant_name"),
        merchant_normalized=data.get("merchant_normalized"),
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


def extract_receipt(file_path: str) -> ExtractionResult:
    """Extract structured data from a receipt image/PDF using Gemini Vision."""
    path = Path(file_path)
    mime_type = _MIME_MAP.get(path.suffix.lower(), "image/jpeg")
    file_data = path.read_bytes()

    image_part = types.Part.from_bytes(data=file_data, mime_type=mime_type)
    contents = [EXTRACTION_PROMPT, image_part]

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
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

    result = parse_extraction_payload(data)

    logger.info(
        "Extraction complete: merchant=%s, total=%s, confidence=%.2f, items=%d",
        result.merchant_name,
        result.grand_total,
        result.confidence,
        len(result.items),
    )

    return result
