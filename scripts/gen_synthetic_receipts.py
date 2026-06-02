"""Generate synthetic test receipts via OpenRouter image-gen model.

Reads master prompt + 13 case variants (hardcoded below to mirror
dataTest/SYNTHETIC_PROMPT.md), calls OpenRouter with an image-capable model,
and saves outputs to dataTest/demo/<NN>_<slug>.jpeg.

Usage:
    cd backend && .venv/bin/python ../scripts/gen_synthetic_receipts.py
    cd backend && .venv/bin/python ../scripts/gen_synthetic_receipts.py --case 4
    cd backend && .venv/bin/python ../scripts/gen_synthetic_receipts.py --model openai/gpt-4o
"""

from __future__ import annotations

import argparse
import base64
import logging
import os
import sys
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(_BACKEND))
os.chdir(_BACKEND)  # so pydantic_settings finds backend/.env

from app.config import settings  # noqa: E402

logger = logging.getLogger("gen_synthetic")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

OUT_DIR = Path(__file__).resolve().parent.parent / "dataTest" / "demo"

DEFAULT_MODEL = "google/gemini-3.1-flash-image-preview"

MASTER_PROMPT = """\
สร้างภาพ "ใบเสร็จ/ใบกำกับภาษี/บิลเงินสด" ของร้านค้าส่งในไทย ที่ดูเหมือนถ่ายมาจาก
กล้องมือถือจริง — ใช้ทดสอบระบบ AI ที่อ่านใบเสร็จ

ข้อกำหนดทั่วไป:
- ภาษาไทยเป็นหลัก ตัวเลขอารบิค
- ขนาด ~1000x1500px มุมเอียงเล็กน้อย พื้นหลังโต๊ะไม้/พื้นกระเบื้อง
- รวมข้อมูล: ชื่อร้าน ที่อยู่/เบอร์โทร เลขที่บิล วันที่ รายการสินค้า ยอดรวม VAT 7% (ถ้าเป็นใบกำกับภาษี) ยอดสุทธิ

Catalog (ใส่ตามจริงให้ระบบ match):
- เบียร์: เบียร์สิงห์ขวดใหญ่/กระป๋อง, เบียร์ลีโอขวดใหญ่/ขวดเล็ก, เบียร์อาซาฮีกระป๋อง
- น้ำดื่ม: น้ำสิงห์เพ็ท 600ml/1.5L, น้ำแร่ฟิจิ
- โซดา: โซดาสิงห์, สิงห์เลมอนโซดา (ปกติ/แตงโม/ครีม)
- สุรา/วิสกี้: บรั่นดีรีเจนซี่, สุราหงส์ทอง, สุราเบลนด์ 285, จอห์นนี่ วอล์คเกอร์ เรด, วิสกี้ซิลเวอร์วูล์ฟ
- พรีเมียม: เสื้อยืดลีโอสุพรีม L, แก้วเก็บความเย็น Snowy Journey
"""

CASES: list[tuple[str, str]] = [
    (
        "16_happy_mixed",
        "ใบกำกับภาษี ร้าน 'รวยสุรา' 3-4 รายการ ผสมเบียร์+น้ำดื่ม+โซดา ยอดรวม ~฿8,000 "
        "VAT 7% คำนวณถูกต้อง พิมพ์คมชัด มุมเอียงเล็กน้อย",
    ),
    (
        "17_multi_category_large",
        "ใบกำกับภาษี ร้าน 'ลิ้มเฮงพัฒนา' 12-15 รายการ ผสม 5 หมวด: "
        "เบียร์+สุรา+วิสกี้+น้ำ+โซดา ยอดรวม ~฿450,000 ตารางยาว ตัวอักษรเล็ก",
    ),
    (
        "18_same_merchant_a",
        "ใบกำกับภาษี ร้าน 'รวยสุรา' เลขบิล A001 วันที่ 01/12/2025 ยอด ฿7,500 "
        "(เบียร์สิงห์ + ลีโอ)",
    ),
    (
        "19_same_merchant_b",
        "ใบกำกับภาษี ร้าน 'รวย-สุรา' (ชื่อร้านมีขีดกลาง) เลขบิล A042 "
        "วันที่ 15/12/2025 ยอด ฿47,245 — เบียร์ขวดใหญ่หลายลัง",
    ),
    (
        "20_same_merchant_c",
        "ใบกำกับภาษี ร้าน 'ร้าน รวยสุรา' (มีคำว่า 'ร้าน' นำหน้า) "
        "เลขบิล A089 วันที่ 08/01/2026 ยอด ฿7,895 — เบียร์ + โซดา",
    ),
    (
        "21_vat_mismatch",
        "ใบกำกับภาษี ร้าน 'จำปิสโตร์' subtotal ฿10,000 แต่ VAT พิมพ์ ฿850 "
        "(จริงต้อง ฿700) grand_total ฿10,850 — ตัวเลข VAT ผิดโดยเจตนา",
    ),
    (
        "22_items_total_mismatch",
        "ใบกำกับภาษี ร้าน 'ณ บวร เทรดดิ้ง' 8-10 รายการ ที่ผลรวมราคาจริง ~฿37,000 "
        "แต่ grand_total พิมพ์เป็น ฿203,210 (ห่างกันเยอะ) ดูเหมือนใบจริงแต่ตัวเลขรวมไม่ตรง",
    ),
    (
        "25a_sudaphanij_baseline_1",
        "ใบกำกับภาษี ร้าน 'สุดาพาณิชย์' วันที่ 12/12/2025 เลขบิล S2512-001 "
        "ยอด ~฿8,500 — เบียร์สิงห์ขวดใหญ่ 5 ลัง + โซดาสิงห์ 3 ถาด — ใบขนาดปกติ",
    ),
    (
        "25b_sudaphanij_baseline_2",
        "ใบกำกับภาษี ร้าน 'สุดาพาณิชย์' วันที่ 18/12/2025 เลขบิล S2512-007 "
        "ยอด ~฿14,300 — เบียร์ลีโอขวดใหญ่ 8 ลัง + น้ำสิงห์เพ็ท 6 แพ็ค — ใบขนาดปกติ",
    ),
    (
        "25c_sudaphanij_baseline_3",
        "ใบกำกับภาษี ร้าน 'สุดาพาณิชย์' วันที่ 03/01/2026 เลขบิล S2601-002 "
        "ยอด ~฿22,100 — เบียร์ + โซดา + น้ำดื่มผสม 4 รายการ — ใบขนาดปกติ",
    ),
    (
        "25_unusual_amount",
        "ใบกำกับภาษี ร้าน 'สุดาพาณิชย์' ยอด ฿850,000 (ยอดสูงผิดปกติเทียบใบก่อนหน้า) "
        "10 รายการ เน้นวิสกี้/บรั่นดีหลายลัง",
    ),
    (
        "27_handwritten_spirit",
        "บิลเงินสดเขียนมือ ลายมือไทยบนกระดาษเส้นบรรทัด ร้าน 'ป้าเนเจอร์' "
        "8-10 รายการ เน้นสุรา/วิสกี้: หงส์ทอง, เบลนด์ 285, JW Red, ลีโอ, สิงห์ "
        "ยอด ~฿30,000",
    ),
    (
        "28_low_quality_combo",
        "ใบเสร็จกระดาษความร้อน ที่ (1) สีจางเลือนรางบางส่วน (2) มีรอยพับ/ยับทับตัวเลข "
        "(3) ภาพเอียง 30-45° ร้านอะไรก็ได้ 5-6 รายการ ฿12,000 — ทดสอบ OCR robustness",
    ),
    (
        "29_sales_report",
        "เอกสาร 'รายงานสรุปยอดขายรายเดือน' รูปแบบตาราง ไม่ใช่ใบเสร็จ "
        "มีคอลัมน์: ลูกค้า, ยอดขาย, จำนวน, vol — รวมรายการ catalog บุญรอด "
        "เช่น เบียร์สิงห์/ลีโอ/น้ำสิงห์เพ็ท",
    ),
    (
        # Demo for the "alias IS learned" happy path. Prints a beer line as a
        # shop-style abbreviation ("บ.สิงห์ ใหญ่") so the AI captures the raw
        # text but does not confidently match a catalog SKU; in the demo the
        # rep corrects it to "เบียร์สิงห์ขวดใหญ่". fuzzy(raw, canonical) ≈ 75
        # (≥ the 50 semantic-jump floor and source is not a catalog canonical),
        # so upsert_product_alias learns it (product_alias_learned) — the badge
        # "เรียนรู้แล้ว" increments. Merchant "รวยสุรา" is an ACTIVE store, so
        # the doc attaches to a real Visit rather than the unknown-store bin.
        "30_alias_learn_beer",
        "ใบกำกับภาษี ร้าน 'หจก. รวยสุรา กรุ๊ป' วันที่ 02/06/2026 "
        "เลขบิล RS-2606-031 จำนวน 5 รายการ — สำคัญมาก: ต้องมี 1 บรรทัดที่พิมพ์ "
        "ชื่อสินค้าเป๊ะแบบย่อว่า 'บ.สิงห์ ใหญ่' จำนวน 3 ลัง (เลียนแบบลายมือ/ชื่อย่อ "
        "ที่ร้านชอบเขียน) ที่เหลือเป็นสินค้าบุญรอดชื่อเต็มชัดเจน: เบียร์ลีโอขวดใหญ่ "
        "2 ลัง, โซดาสิงห์ 2 ถาด, น้ำสิงห์เพ็ท 600ml 4 แพ็ค, สิงห์เลมอนโซดา 1 ถาด "
        "— ยอดรวม ~฿9,500 VAT 7% พิมพ์คมชัด อ่านชื่อสินค้าได้ชัดทุกบรรทัด "
        "มุมเอียงเล็กน้อย",
    ),
    (
        # Demo for AI READING STRENGTH (zero-shot shorthand decode). A
        # handwritten cash bill full of cryptic shop shorthands; Gemini matches
        # every line to the right catalog SKU with no aliases configured. The
        # punch line: the model decodes "บส.ญ", "อซฮ.ก" etc. purely from the
        # in-prompt catalog — no training, no learned aliases needed. Uses the
        # ACTIVE store "รวยสุรา" so it lands in a real Visit. (Confirmed: all 6
        # shorthands coded correctly on upload.)
        "31_ai_reads_shorthand",
        "บิลเงินสดเขียนด้วยลายมือ บนกระดาษเส้นบรรทัด ร้าน 'หจก. รวยสุรา กรุ๊ป' "
        "วันที่ 02/06/2026 จำนวน 6 รายการ เขียนชื่อสินค้าแบบย่อตามสไตล์ร้านโชห่วย "
        "ให้พิมพ์ชื่อสินค้าเป๊ะตามนี้ทีละบรรทัด: "
        "(1) 'B ลีโอ ญ' 2 ลัง  (2) 'บส.ญ' 3 ลัง  (3) 'ช.ลัง' 1 ลัง  "
        "(4) 'ลีโอ L' 2 ลัง  (5) 'สห ใหญ่' 1 ลัง  (6) 'อซฮ.ก' 4 แพ็ค "
        "— ลายมืออ่านออกแต่เป็นตัวย่อ ยอดรวมประมาณ ฿20,000",
    ),
]


def _client():
    if not settings.openrouter_api_key:
        sys.exit("ERROR: OPENROUTER_API_KEY ไม่ได้ตั้ง — เพิ่มใน backend/.env ก่อน")
    from openai import OpenAI

    headers: dict[str, str] = {}
    if settings.openrouter_app_url:
        headers["HTTP-Referer"] = settings.openrouter_app_url
    if settings.openrouter_app_title:
        headers["X-Title"] = settings.openrouter_app_title
    return OpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        default_headers=headers or None,
        timeout=120,
    )


def generate(client, model: str, slug: str, case_prompt: str) -> Path | None:
    full_prompt = f"{MASTER_PROMPT}\n\n---\n\nสร้างภาพตามรายละเอียดต่อไปนี้:\n\n{case_prompt}"
    logger.info("→ generating %s ...", slug)
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": full_prompt}],
            modalities=["image", "text"],
        )
    except Exception as e:
        logger.error("  failed: %s", e)
        return None

    msg = resp.choices[0].message
    images = getattr(msg, "images", None) or []
    if not images:
        for block in msg.content if isinstance(msg.content, list) else []:
            if isinstance(block, dict) and block.get("type") == "image_url":
                images.append(block)
    if not images:
        logger.error("  no image in response (content=%s)", str(msg.content)[:200])
        return None

    img = images[0]
    url = img.get("image_url", {}).get("url") if isinstance(img, dict) else None
    if not url:
        logger.error("  unexpected image shape: %s", str(img)[:200])
        return None

    if url.startswith("data:"):
        b64 = url.split(",", 1)[1]
        data = base64.b64decode(b64)
    else:
        import urllib.request
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()

    out = OUT_DIR / f"{slug}.jpeg"
    out.write_bytes(data)
    logger.info("  saved %s (%d KB, %.1fs)", out.name, len(data) // 1024, time.time() - t0)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--case", type=int, help="generate only this case (1-13)")
    p.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter model id")
    args = p.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = _client()

    targets = CASES if args.case is None else [CASES[args.case - 1]]
    logger.info("model=%s, generating %d case(s) → %s", args.model, len(targets), OUT_DIR)

    ok = 0
    for slug, case_prompt in targets:
        if generate(client, args.model, slug, case_prompt):
            ok += 1
        time.sleep(2)

    logger.info("done: %d/%d generated", ok, len(targets))


if __name__ == "__main__":
    main()
