import json
import logging
from pathlib import Path

from ..schemas import DocumentItemBase, ExtractionResult
from . import llm_client

logger = logging.getLogger(__name__)

# Top-level product categories, aligned with singhaonline.com (2026-04).
# Keep this list tight — subcategories are represented through
# ``product_name_normalized`` plus PRODUCT_CATALOG entries, not category.
PRODUCT_CATEGORIES = [
    "เครื่องดื่ม",
    "อาหาร และของว่าง",
    "สินค้าพรีเมียมสิงห์",
    "สินค้าอื่นๆ",
]

_CATEGORY_SET = set(PRODUCT_CATEGORIES)

# Mapping from the old 8-category taxonomy (pre-2026-04) to the new 4-category
# taxonomy, used by the alembic migration that remaps existing rows.
LEGACY_CATEGORY_MAP = {
    "เบียร์": "เครื่องดื่ม",
    "น้ำดื่ม": "เครื่องดื่ม",
    "โซดาและน้ำอัดลม": "เครื่องดื่ม",
    "น้ำแร่": "เครื่องดื่ม",
    "สุรา": "เครื่องดื่ม",
    "เครื่องดื่มอื่นๆ": "เครื่องดื่ม",
    "อาหาร": "อาหาร และของว่าง",
    "อื่นๆ": "สินค้าอื่นๆ",
}

# Boonrawd product catalog with aliases for matching handwritten/abbreviated names
def _parse_catalog_canonicals(catalog_markdown: str) -> frozenset[str]:
    """Extract the first column ("ชื่อทางการ") from the catalog markdown table.

    Returned as a lowercase-normalized frozenset for O(1) membership checks.
    Used by ``services.product_aliases`` to refuse poisoning aliases where the
    source text is itself a catalog canonical.
    """
    out: set[str] = set()
    for line in catalog_markdown.splitlines():
        line = line.strip()
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        # Skip the header row explicitly
        if "ชื่อทางการ" in cells[0]:
            continue
        name = cells[0]
        if name:
            out.add(" ".join(name.strip().split()).lower())
    return frozenset(out)


PRODUCT_CATALOG = """
## สินค้าเครือบุญรอด — ใช้ตารางนี้ map ชื่อย่อ/ลายมือ → ชื่อทางการ

| ชื่อทางการ (product_name_normalized) | คำย่อ / ชื่อเล่น / ลายมือที่พบบ่อย | หมวด |
|--------------------------------------|--------------------------------------|------|
| เบียร์สิงห์ขวดใหญ่ | สห์ใหญ่, สิงห์ใหญ่, SINGHA L, สห.ญ, สิงห์ 630, สิงห์แดง | เครื่องดื่ม |
| เบียร์สิงห์ขวดเล็ก | สห์เล็ก, สิงห์เล็ก, SINGHA S, สห.ล, สิงห์ 330 | เครื่องดื่ม |
| เบียร์สิงห์กระป๋อง | สห์กป, สิงห์กระป๋อง, SINGHA CAN | เครื่องดื่ม |
| เบียร์ลีโอขวดใหญ่ | ลีโอใหญ่, LEO L, ลีโอ 630, ล.ญ | เครื่องดื่ม |
| เบียร์ลีโอขวดเล็ก | ลีโอเล็ก, LEO S, ลีโอ 330, ล.ล | เครื่องดื่ม |
| เบียร์ลีโอกระป๋อง | ลีโอกป, LEO CAN | เครื่องดื่ม |
| เบียร์ช้าง | ช้าง, CHANG, ช. | เครื่องดื่ม |
| เบียร์ช้างเอสเปรสโซ่ | ช้างเอส, CHANG ESP | เครื่องดื่ม |
| เบียร์ยูเบียร์ | U BEER, ยู, UBEER | เครื่องดื่ม |
| น้ำดื่มสิงห์ | น้ำสิงห์, นส, SINGHA WATER, สห์น้ำ, น้ำเปล่าสิงห์ | เครื่องดื่ม |
| น้ำดื่มสิงห์ 600ml | น้ำสิงห์ 600, สห์600 | เครื่องดื่ม |
| น้ำดื่มสิงห์ 1.5L | น้ำสิงห์ 1500, สห์1500 | เครื่องดื่ม |
| โซดาสิงห์ | โซดาสห์, SINGHA SODA, SODAPP, โซดา, โซคา, โซดาขวด, โซดาเปลี่ยน, โซดาถาด, โซดาเปลี่ยน/ถาด, โซดาเปล่า/ถาด | เครื่องดื่ม |
| น้ำแร่เพอริเอ้ | เพอริเอ้, PERRIER, Perrier | เครื่องดื่ม |
| น้ำแร่ออร่า | ออร่า, AURA | เครื่องดื่ม |
| สุราแสงโสม | แสงโสม, SS, Saeng Som, แสง | เครื่องดื่ม |
| สุราหงส์ทอง | หงส์ทอง, หงส์, HT, Hong Thong | เครื่องดื่ม |
| สุราเบลนด์ 285 | เบลนด์, BLEND, 285 | เครื่องดื่ม |
| สุรามิสเตอร์ซี | มิสเตอร์ซี, MR.C, Mr.C | เครื่องดื่ม |
| บี-อิ้ง | B-ing, บีอิ้ง, Bing | เครื่องดื่ม |
| เฮลซ์บลูบอย | เฮลซ์, HELZ, บลูบอย | เครื่องดื่ม |
| สิงห์เลมอนโซดา | เลมอนโซดา, LEMON SODA | เครื่องดื่ม |
"""

# Normalized lowercase set of canonical product names, used by the alias
# service to refuse learning aliases where the *source* (what the user is
# overriding) is already a catalog canonical — accepting those would poison
# future documents that genuinely match the canonical.
CATALOG_CANONICAL_NAMES: frozenset[str] = _parse_catalog_canonicals(PRODUCT_CATALOG)

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
      "product_name_raw": "ชื่อสินค้าที่อ่านได้จากเอกสาร **ตรงตามลายมือ/ตัวอักษรจริง** (ยังไม่ผ่าน catalog normalization, ไม่ทำ typo fix — แต่อาจตัด unit เช่น 'ลัง'/'ขวด' ออก)",
      "product_name_normalized": "ชื่อสินค้าที่แสดงในระบบ — ถ้า match กับตาราง PRODUCT_CATALOG ให้ใช้ 'ชื่อทางการ' จากตาราง; ถ้าไม่ match ให้ใช้ค่าเดียวกับ product_name_raw",
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
- **สองฟิลด์ชื่อสินค้า** (ต้องใส่ทั้งคู่):
  - `product_name_raw` = ข้อความต้นฉบับจากเอกสาร ตรงตามตัวอักษร/ลายมือที่อ่านได้
    - **ห้าม** ทำ catalog lookup, ห้ามแก้ typo, ห้าม normalize
    - ทำได้แค่: ตัด **unit** เช่น "ลัง"/"ขวด"/"แพ็ค" และ **return marker** เช่น "เปลี่ยน/ถาด" ออก
    - ตัวอย่าง: receipt = "SODAPP โซดาเปลี่ยน/ถาด ×12"  →  raw = "SODAPP โซดา"
    - ตัวอย่าง: receipt = "สิงเลม่อน"  →  raw = "สิงเลม่อน" (ไม่แก้เป็น "สิงห์เลมอนโซดา")
  - `product_name_normalized` = ชื่อที่จะแสดง
    1. ถ้า raw match กับ PRODUCT_CATALOG (อ้อม typo/alias ก็นับ) → ใช้ **ชื่อทางการ** จากตาราง
    2. ถ้าไม่ match → ใช้ **ค่าเดียวกับ raw**
    3. ห้ามทั้งคู่เป็น null ตราบใดที่อ่านเอกสารออก — ถ้าอ่านไม่ออกจริง ๆ ให้ใส่ "?" และเพิ่มใน `needs_review_fields`
- **คำต่อท้ายสินค้าที่ไม่ใช่ส่วนของชื่อ** : คำเหล่านี้อธิบาย **รูปแบบการขาย/การบรรจุ** ไม่ใช่ชื่อสินค้า
  ให้ละทิ้งคำเหล่านี้เวลา map ไป product_name_normalized และเวลาจัด category
  - "เปลี่ยน" / "เปล่า" / "ถาด" / "เปลี่ยน/ถาด" / "เปล่า/ถาด" → หมายถึงขายแบบเปลี่ยนลัง/คืนลังเปล่า (returnable crate)
  - "ลัง" / "กระป๋อง" / "ขวด" / "แพ็ค" → เป็น **unit** ให้ใส่ใน field `unit` ไม่ใช่ชื่อสินค้า
  - ตัวอย่าง: "SODAPP โซดาเปลี่ยน/ถาด" = โซดาสิงห์ (ขายแบบเปลี่ยนถาด) → category "เครื่องดื่ม", normalized = "โซดาสิงห์"
  - ตัวอย่าง: "เบียร์สิงห์เปลี่ยนขวด" = เบียร์สิงห์ (คืนขวดเปล่า) → category "เครื่องดื่ม"
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
  (อิง Singha Online 4 หมวดหลัก)
  วิธีเลือก category ของแต่ละรายการ (items[].category):
    1. ถ้าเป็นเบียร์ / สุรา / น้ำดื่ม / โซดา / น้ำแร่ / น้ำอัดลม / ชา / กาแฟ / เครื่องดื่มชูกำลัง → "เครื่องดื่ม"
    2. ถ้าเป็นอาหาร / ของว่าง / ขนม / snack / ของกิน → "อาหาร และของว่าง"
    3. ถ้าเป็นของที่ระลึก / เสื้อผ้า / แก้ว / ของสะสม / merchandise ของสิงห์ → "สินค้าพรีเมียมสิงห์"
    4. ใช้ "สินค้าอื่นๆ" เฉพาะเมื่อไม่เข้าหมวด 1-3 เลยจริงๆ (ไม่ใช่ default)
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


# Backward-compat shim: agentic extraction still imports ``_get_client``.
# Forward to the shared client cache in ``llm_client``.
_get_client = llm_client.get_gemini_client


def _coerce_extracted_payload(data: object) -> dict:
    """Normalize Gemini responses that sometimes come back as arrays or nested lists."""
    if isinstance(data, list):
        logger.warning("Gemini returned array instead of object, using first element")
        data = data[0] if data and isinstance(data[0], dict) else {}
    if not isinstance(data, dict):
        return {}
    return data


def _coerce_category(raw: object, default: str | None = None) -> str | None:
    """Validate ``raw`` against the current taxonomy, remapping legacy values.

    Accepts strings only; everything else returns ``default``. A legacy value
    (pre-2026-04 8-category taxonomy) is transparently converted to its new
    bucket so cached Gemini responses and test fixtures keep working.
    """
    if not isinstance(raw, str):
        return default
    if raw in _CATEGORY_SET:
        return raw
    remapped = LEGACY_CATEGORY_MAP.get(raw)
    if remapped:
        return remapped
    return default


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
        cat = _coerce_category(it.get("category"), default_category)
        raw_name = it.get("product_name_raw")
        normalized = it.get("product_name_normalized") or raw_name
        # If raw missing but normalized present, we can't recover raw — fall
        # back to normalized so alias source is non-null downstream.
        if raw_name is None:
            raw_name = normalized
        items.append(
            DocumentItemBase(
                product_name_raw=raw_name,
                product_name_normalized=normalized,
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

    category = _coerce_category(data.get("category"), "สินค้าอื่นๆ") or "สินค้าอื่นๆ"
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
    """Extract structured data from a receipt image/PDF using the configured LLM."""
    path = Path(file_path)
    mime_type = _MIME_MAP.get(path.suffix.lower(), "image/jpeg")
    file_data = path.read_bytes()

    logger.info("Extracting receipt: %s (%s, %d bytes)", path.name, mime_type, len(file_data))

    raw_text = llm_client.generate_json(
        system_instruction=SYSTEM_INSTRUCTION,
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

    result = parse_extraction_payload(data)

    logger.info(
        "Extraction complete: merchant=%s, total=%s, confidence=%.2f, items=%d",
        result.merchant_name,
        result.grand_total,
        result.confidence,
        len(result.items),
    )

    return result
