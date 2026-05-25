import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from ..schemas import DocumentItemBase, ExtractionResult
from . import catalog, llm_client

logger = logging.getLogger(__name__)

# Top-level product categories, aligned with singhaonline.com (2026-04).
# Keep this list tight — subcategories are represented through PRODUCT_CATALOG
# entries (resolved via product_code), not category.
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

# PRODUCT_CATALOG markdown is now built from the ``products`` table at runtime
# via :func:`catalog.prompt_catalog_markdown`, so adding a SKU automatically
# lands in the prompt — no manual sync.
#
# The two halves of SYSTEM_INSTRUCTION ("head" before catalog, "tail" after)
# are concatenated in :func:`build_system_instruction`.

_SYSTEM_INSTRUCTION_HEAD = """\
คุณเป็น AI ผู้เชี่ยวชาญในการอ่านและวิเคราะห์เอกสารการขายภาษาไทย
เช่น ใบเสร็จรับเงิน บิลเงินสด ใบกำกับภาษี และใบส่งของ
รวมถึงเอกสารที่เขียนด้วยลายมือ

**โจทย์หลัก**: ดึงรายการสินค้า (`items[]`) ให้ครบและถูกต้องที่สุด — ชื่อสินค้า, จำนวน, หน่วย, ราคา
ทั้งสินค้าของเครือบุญรอด **และของคู่แข่ง** (ช้าง, ลีโอ-ของคู่แข่ง, ไฮเนเก้น, อาซาฮี, ซาน มิเกล, โค้ก, เป๊ปซี่ ฯลฯ)
ถ้าเป็นสินค้าคู่แข่ง:
- `product_name_raw` = ตามที่อ่านได้จากใบเสร็จ
- `product_code` = null (ห้าม map ผิด)
"""

_SYSTEM_INSTRUCTION_TAIL_TEMPLATE = """
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
      "product_code": "SKU code ของสินค้า (string | null) — ดูจากคอลัมน์ product_code ของตาราง PRODUCT_CATALOG; ใส่เฉพาะเมื่อมั่นใจว่า match จริง ไม่ใช่ทุกบรรทัดต้องมี",
      "category": "หมวดหมู่ของรายการนี้ (string จาก allowed categories)",
      "quantity": 0,
      "unit": "หน่วย เช่น ขวด ลัง แพ็ค กระป๋อง"
    }
  ],
  "confidence": 0.85,
  "notes": "หมายเหตุเพิ่มเติม",
  "needs_review_fields": ["field ที่ไม่มั่นใจ"]
}

## โจทย์: ดึง **ชื่อสินค้า + จำนวน + หน่วย** เท่านั้น
ระบบไม่ใช้ข้อมูลราคา (subtotal, discount, vat, grand_total, unit_price, line_total) — ห้าม emit
หรือลงทุนเวลาอ่านมัน. โฟกัสกับการ map สินค้าเข้า catalog และนับจำนวนให้ถูก.

## กฎสำคัญ
- **ภาษาที่ใช้ตอบ** : ข้อความทุก field ที่เป็นคำอธิบาย/หมายเหตุ (`notes`, `needs_review_fields` ถ้าต้องอธิบาย)
  **ต้องเป็นภาษาไทย 100% เท่านั้น** ห้ามใช้ภาษาอังกฤษในการอธิบาย
  - ตัวเลข / ชื่อสินค้า / ชื่อร้าน สามารถคงภาษาอังกฤษได้ถ้าต้นฉบับเป็นภาษาอังกฤษ
  - แต่ "คำอธิบาย" ต้องเขียนเป็นไทยเสมอ เช่น ถ้ายอดรวมลายมือไม่ตรงกับการคำนวณ ต้องเขียนแบบ
    "ยอดรวมที่เขียนด้วยลายมือ (16,905) ไม่ตรงกับยอดคำนวณ (16,105) ใช้ยอดคำนวณแทน"
    ห้ามเขียนเป็น "The handwritten grand total is inconsistent..."
- **สองฟิลด์หลักของแต่ละ item**:
  - `product_name_raw` = ข้อความต้นฉบับจากเอกสาร ตรงตามตัวอักษร/ลายมือที่อ่านได้
    - **ห้าม** ทำ catalog lookup, ห้ามแก้ typo, ห้าม normalize
    - ทำได้แค่: ตัด **unit** เช่น "ลัง"/"ขวด"/"แพ็ค" และ **return marker** เช่น "เปลี่ยน/ถาด" ออก
    - ตัวอย่าง: receipt = "SODAPP โซดาเปลี่ยน/ถาด ×12"  →  raw = "SODAPP โซดา"
    - ตัวอย่าง: receipt = "สิงเลม่อน"  →  raw = "สิงเลม่อน" (ไม่แก้เป็น "สิงห์เลมอนโซดา")
    - ถ้าอ่านไม่ออกจริง ๆ ให้ใส่ "?" และเพิ่ม "product_name_raw" ใน `needs_review_fields`
  - `product_code` = SKU code ของสินค้า (ตัวระบุหลัก — ระบบจะ resolve ชื่อทางการสำหรับแสดงผลจาก code นี้)
    1. หา raw ในตาราง PRODUCT_CATALOG (รวมถึงคอลัมน์ "คำย่อ / ชื่อเล่น / ลายมือที่พบบ่อย") — ถ้า match → ใช้ค่าใน column `product_code` ของแถวนั้น **ตรงๆ ไม่ดัดแปลง**
    2. ถ้าตาราง PRODUCT_CATALOG ของแถวที่ match มี `product_code = "-"` → ใส่ null
    3. ถ้าไม่ match catalog เลย (สินค้าคู่แข่งที่ยังไม่มีใน catalog) → ใส่ null
    4. **ห้ามแต่งรหัสขึ้นเอง** ถ้าไม่แน่ใจให้ null — ห้ามเดา
    5. ห้ามใช้ EAN/บาร์โค้ดที่ปรากฏบนใบเสร็จเป็น product_code — ใช้เฉพาะรหัสจาก catalog เท่านั้น
    6. **สำคัญ**: code กับ raw ต้องชี้สินค้าเดียวกัน — ห้าม pick code ของ "เบียร์สิงห์" สำหรับ raw "น้ำสิงห์"
- **Variant qualifier ที่เป็นส่วนของชื่อสินค้า** (สำคัญ): สี/รสชาติ/รุ่น ที่อยู่ในวงเล็บหรือหลังชื่อ
  ต้อง **เก็บรักษาไว้** ใน product_name_raw และต้องเลือก code ของ variant ที่ตรงกัน
  - ตัวอย่าง: "เลมอนโซดา (เรด)" → raw = "เลมอนโซดา (เรด)", code = code ของ "สิงห์เลมอนโซดา เรด" (ห้ามตัด "(เรด)" ทิ้ง)
  - ตัวอย่าง: "เลมอนโซดา (แดง)" → raw = "เลมอนโซดา (แดง)" — ตีความ "แดง" = "เรด"
  - ตัวอย่าง: "เลมอนโซดา (พิงก์)" → code = code ของ "สิงห์เลมอนโซดา พิงก์"
  - ตัวอย่าง: "เลมอนโซดา (ครีม)" / "เลมอนโซดา (แตงโม)" / "เลมอนโซดา (บ๊วย)" — variant ทั้งหมด
  - ถ้าใบเสร็จมี 2 บรรทัดเขียน "เลมอนโซดา" + "เลมอนโซดา (เรด)" ห้าม merge เป็นรายการเดียว
    และห้าม emit ทั้งสองด้วย raw เดียวกัน — บรรทัดที่ไม่มี (...) raw = "เลมอนโซดา",
    บรรทัดที่มี raw = "เลมอนโซดา (เรด)" — เพื่อให้ alias system แยก SKU ได้
- **คำต่อท้ายสินค้าที่ไม่ใช่ส่วนของชื่อ** : คำเหล่านี้อธิบาย **รูปแบบการขาย/การบรรจุ** ไม่ใช่ชื่อสินค้า
  ให้ละทิ้งคำเหล่านี้เวลา match กับ PRODUCT_CATALOG และเวลาจัด category
  - "เปลี่ยน" / "เปล่า" / "ถาด" / "เปลี่ยน/ถาด" / "เปล่า/ถาด" → หมายถึงขายแบบเปลี่ยนลัง/คืนลังเปล่า (returnable crate)
  - "ลัง" / "กระป๋อง" / "ขวด" / "แพ็ค" → เป็น **unit** ให้ใส่ใน field `unit` ไม่ใช่ชื่อสินค้า
  - ตัวอย่าง: "SODAPP โซดาเปลี่ยน/ถาด" = โซดาสิงห์ (ขายแบบเปลี่ยนถาด) → category "เครื่องดื่ม", code = code ของ "โซดาสิงห์"
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
  วิธีเลือก `category` (เอกสาร) : ใช้หมวดที่พบมากที่สุดใน items (by quantity)
- **การแปลงปีในเอกสาร** (สำคัญมาก — ผิดบ่อย):
  - เอกสารการขายของไทย **เกือบทั้งหมดใช้ปี พ.ศ.** ไม่ว่าจะเขียนเต็ม (2568) หรือ 2 หลักท้าย (68)
  - กฎ: `document_date` ต้องเป็น **ค.ศ. (Gregorian) เท่านั้น** ในรูปแบบ `YYYY-MM-DD`
  - การแปลง:
    1. ถ้าปีเป็นเลข 4 หลักและ ≥ 2500 → เป็น พ.ศ. → **ลบ 543** เพื่อได้ ค.ศ. (เช่น 2568 → 2025, 2569 → 2026)
    2. ถ้าปีเป็นเลข 2 หลัก (60-99) บนใบเสร็จไทย → ตีความเป็น พ.ศ. 25XX → ค.ศ. = 25XX - 543
       - "68" → พ.ศ. 2568 → ค.ศ. **2025** (ห้าม! ตอบ "2068")
       - "69" → พ.ศ. 2569 → ค.ศ. **2026**
       - "70" → พ.ศ. 2570 → ค.ศ. **2027**
    3. ถ้าปีเป็นเลข 4 หลัก < 2500 (เช่น 2025, 2026) → เป็น ค.ศ. อยู่แล้ว ใช้เลย
  - ตัวอย่าง:
    - "30 ธ.ค. 68" → `2025-12-30` (ไม่ใช่ 2068-12-30)
    - "3 เม.ย. 69" → `2026-04-03`
    - "15/05/2568" → `2025-05-15`
  - **Sanity check**: หลังแปลงแล้ว ถ้าปี ค.ศ. ที่ได้ห่างจากปีปัจจุบันเกิน 5 ปี (อนาคตหรืออดีต) ให้ทบทวนใหม่ — น่าจะลืมแปลง
- ถ้าอ่านไม่ออกหรือไม่แน่ใจ ให้ใส่ null และเพิ่มชื่อ field ใน needs_review_fields
- confidence เป็นค่า 0.0 - 1.0 แสดงความมั่นใจโดยรวม
- ถ้าเอกสารไม่ใช่ใบเสร็จ/บิลเงินสด/ใบกำกับภาษี/ใบส่งของ (เช่น เป็นรายงานสรุปยอด, สลิปโอนเงิน, เอกสารอื่น) ให้:
  * ยังคงพยายามดึงข้อมูลให้ได้มากที่สุด
  * ตั้ง confidence ต่ำ (0.3-0.6) ตามความเหมาะสม
  * ระบุใน notes ว่าเอกสารนี้เป็นประเภทอะไร
  * เพิ่ม "document_type" ใน needs_review_fields
- ถ้ามีหลายหน้าหรือหลายรายการที่เป็นสรุปรวม ให้ดึงรายการแต่ละบรรทัดเป็น item แยก
- ตอบเป็น JSON เท่านั้น ห้ามมี markdown code fence หรือข้อความอื่น

## ตัวอย่าง output ที่ถูกต้อง (one-shot example)
ใบเสร็จที่ขายเบียร์สิงห์ขวดใหญ่ 12 ขวด และน้ำเปล่ายี่ห้ออื่นที่ไม่อยู่ใน catalog 1 แพ็ค
ออกบิล 30 ธ.ค. 2568 (พ.ศ.) ที่ "บริษัท สมชายเทรดดิ้ง จำกัด (สำนักงานใหญ่)" → ต้องตอบดังนี้:
{
  "merchant_name": "บริษัท สมชายเทรดดิ้ง จำกัด (สำนักงานใหญ่)",
  "merchant_normalized": "สมชายเทรดดิ้ง",
  "document_number": "B25-0042",
  "document_date": "2025-12-30",
  "category": "เครื่องดื่ม",
  "items": [
    {
      "product_name_raw": "สห์ใหญ่",
      "product_code": "INT-BEER-SINGHA-L",
      "category": "เครื่องดื่ม",
      "quantity": 12,
      "unit": "ขวด"
    },
    {
      "product_name_raw": "น้ำคริสตัล แพ็ค",
      "product_code": null,
      "category": "เครื่องดื่ม",
      "quantity": 1,
      "unit": "แพ็ค"
    }
  ],
  "confidence": 0.92,
  "notes": "เอกสารชัดเจน อ่านง่าย",
  "needs_review_fields": []
}
สังเกต: (1) แปลง 2568 → 2025, (2) สห์ใหญ่ match catalog → product_code = INT-BEER-SINGHA-L (ระบบจะ resolve ชื่อทางการ "เบียร์สิงห์ขวดใหญ่" จาก code เอง), (3) น้ำคริสตัลไม่อยู่ใน catalog → product_code = null (ระบบจะใช้ raw เป็นชื่อแสดงผล), (4) merchant_normalized ตัด "บริษัท/จำกัด/(สำนักงานใหญ่)" ออก, (5) ไม่มีฟิลด์ราคา — ระบบไม่ใช้
"""


def build_system_instruction() -> str:
    """Build SYSTEM_INSTRUCTION with the live DB-backed catalog injected.

    The catalog markdown is cached in :mod:`catalog` (invalidated when admin
    endpoints mutate ``products``), so this is effectively a string-concat per
    extraction call — adding/editing SKUs in the DB is reflected in the next
    request without code changes.
    """
    return (
        _SYSTEM_INSTRUCTION_HEAD
        + catalog.prompt_catalog_markdown()
        + _SYSTEM_INSTRUCTION_TAIL_TEMPLATE
    )


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


def _coerce_extracted_payload(data: object) -> dict:
    """Normalize LLM responses that sometimes come back as arrays or nested lists."""
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
        product_code = it.get("product_code")
        if isinstance(product_code, str):
            product_code = product_code.strip() or None
            # Guard against the catalog's "-" placeholder leaking through.
            if product_code == "-":
                product_code = None
        else:
            product_code = None
        # Resolve display name server-side. The LLM emits only raw + code;
        # the canonical display name is derived deterministically here so a
        # (code, name) mismatch from the model is structurally impossible.
        # Legacy: still accept product_name_normalized in the payload as a
        # fallback for backward compat with old tests/fixtures.
        catalog_name = catalog.name_by_code(product_code)
        legacy_normalized = it.get("product_name_normalized")
        normalized = catalog_name or legacy_normalized or raw_name
        if raw_name is None:
            raw_name = normalized
        items.append(
            DocumentItemBase(
                product_name_raw=raw_name,
                product_name_normalized=normalized,
                product_code=product_code,
                category=cat,
                quantity=it.get("quantity"),
                unit=it.get("unit"),
            )
        )
    return items


def _sanitize_document_date(raw_date: object) -> object:
    """Recover from common AI year-conversion mistakes.

    The model occasionally:
      * forgets to convert พ.ศ. → ค.ศ. (returns "2568-12-30")
      * treats 2-digit Thai BE year as CE (returns "2068-12-30" for "68")

    Both cases produce a year far in the future. If the year exceeds
    today + 5, try subtracting 543 — if the result falls within a
    plausible window (5y past .. 1y future), use it. Otherwise leave
    untouched and let validation surface the anomaly.
    """
    if not isinstance(raw_date, str) or len(raw_date) < 10:
        return raw_date
    try:
        parts = raw_date.split("-")
        year = int(parts[0])
    except (ValueError, IndexError):
        return raw_date

    today_year = datetime.now(UTC).year
    if year <= today_year + 1:
        return raw_date

    # Try two recovery interpretations, in order of likelihood:
    #   (a) AI returned raw พ.ศ. without subtracting 543 (e.g. 2568 → 2025)
    #   (b) AI saw 2-digit year "68" and prefixed "20" instead of "25"
    #       (e.g. 2068 → really พ.ศ. 2568 → 2025). Equivalent to year - 43.
    for candidate in (year - 543, year - 43):
        if today_year - 5 <= candidate <= today_year + 1:
            fixed = f"{candidate:04d}-{'-'.join(parts[1:])}"
            logger.warning(
                "Document date %s looked like a year-conversion error; rewrote to %s",
                raw_date,
                fixed,
            )
            return fixed
    return raw_date


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
        document_date=_sanitize_document_date(data.get("document_date")),
        category=category,
        items=items,
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
        system_instruction=build_system_instruction(),
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
        "Extraction complete: merchant=%s, confidence=%.2f, items=%d",
        result.merchant_name,
        result.confidence,
        len(result.items),
    )

    return result
