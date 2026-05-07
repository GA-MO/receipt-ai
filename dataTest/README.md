# Test Data Catalog

ข้อมูลทดสอบสำหรับ Thai Receipt Intelligence
อัปเดตล่าสุด: 2026-05-07 (curated set 15 ไฟล์ + synthetic 11 ไฟล์ = 26 ไฟล์)

ทั้งหมดอยู่ใน `demo/` — ใช้สำหรับทั้ง pitching และ regression testing

**Model ปัจจุบัน:** `google/gemini-3.1-flash-lite-preview` ผ่าน OpenRouter

- Latency p50 ≈ 4.5s, p95 ≈ 6s (เร็วกว่า 2.5-flash ~45%)
- Avg confidence ≈ 0.93

**Filename convention:** ตั้งชื่อแบบ sequential `01.jpeg`–`11.jpeg` ตามลำดับเดโม — README นี้คือ source of truth สำหรับว่าแต่ละไฟล์โชว์อะไร

---

## demo/ — ไฟล์ทดสอบทั้งหมด (26 ไฟล์)

ไฟล์ `01-15` คือใบเสร็จจริง (curated) ส่วน `16-29` คือ synthetic ที่สร้างจาก AI image-gen (`google/gemini-3.1-flash-image-preview` ผ่าน OpenRouter, ดู `SYNTHETIC_PROMPT.md`) — ใบที่ image-gen ทำให้ story ไม่ trigger ตามตั้งใจ (duplicate pair, date edge case) ตัดออกแล้ว

### Pitching set — เรียงตามลำดับเดโม

| ไฟล์ | ร้านค้า | ยอดรวม | ใช้โชว์อะไร |
| --- | --- | --- | --- |
| `01.jpeg` | รวยสุรา | ฿7,010 | **AI ดึงข้อมูล + catalog match** — เครื่องดื่มบุญรอด, ~4-5s |
| `02.jpeg` | มิตรราชบุรีเทรดดิ้ง | ฿1,308 | **หมวดน้ำดื่ม** — single item |
| `03.jpeg` | รวยสุรา (ใบใหญ่) | ฿47,245 | **Merchant cluster** — ใบที่ 2 ของรวยสุรา |
| `04.jpeg` | รวยสุรา (ใบเล็ก) | ฿7,895 | **Merchant cluster** — ใบที่ 3, normalize เป็น "รวยสุรา" |
| `05.jpeg` | สุดาพาณิชย์ | ฿130,305 | **AI fraud detection** — risk 0.7 high "ปี พ.ศ. 68 ผิดปกติ" |
| `06.jpeg` | โจวบุ่งใช้ | ฿30,829 | **OCR challenge / Human-in-the-loop** — บิลลายมือ มีบรั่นดีรีเจนซี่ 2 ลัง × 4,080 (ราคาถูกต้อง) แต่ AI อ่านเป็น "ลีโอแบน" → demo Review page: พิมพ์ "บรั่นดี" → autocomplete suggest "บรั่นดีรีเจนซี่" จาก catalog (`INT-SPIRIT-REGENCY`) |

### Production-grade receipts (ใช้เพิ่มยอดให้ dashboard ดูสมจริง)

| ไฟล์ | ร้านค้า | ยอดรวม | Tags |
| --- | --- | --- | --- |
| `07.jpeg` | จำปิสโตร์ | ฿184,640 | high-value |
| `08.jpeg` | กวงเสิน | ฿16,905 | clean mid |
| `09.jpeg` | ประสงค์การค้าแพร่ | ฿29,452 | mid |
| `10.jpeg` | บ่อกุ้ง / 99999 | ฿4,200 | low-value clean |
| `11.jpeg` | CSB | ฿178,322 | high-conf high-value |

### Extras — เพิ่มเติม story ที่ครอบคลุมมากขึ้น

| ไฟล์ | ร้านค้า | ยอดรวม | Story |
| --- | --- | --- | --- |
| `12.pdf` | สิงห์ สามารถ เทรดดิ้ง | ฿56,445 | **PDF support** + AI ตรวจจับว่าเป็น "รายงานสรุปยอดขาย" ไม่ใช่ใบเสร็จ (low risk) — ยังดึง 4 catalog items ได้ |
| `13.jpeg` | ณ บวร เทรดดิ้ง | ฿203,210 | **Fraud: items_total_mismatch** — ยอดรวมรายการ ฿37,610 ต่างจากยอดบิล ฿203,210 ถึง 81.9% (risk 0.7 high) คนละแบบกับ 05 ที่เป็น fraud จากวันที่ |
| `14.jpeg` | ลิ้มเฮงพัฒนา | ฿485,031 | **Multi-category receipt** — 15 items: เบียร์ × สุรา × ไวน์ × วิสกี้ × น้ำ × โซดา รวมในใบเดียว, AI จัดหมวดและ match catalog ได้พร้อมกัน |
| `15.jpeg` | ป้าเนเจอร์ | ฿30,431 | **Handwritten + spirit catalog** — บิลเขียนมือ 10 รายการ match catalog ได้ครบ (หงส์ทอง, เบลนด์ 285, JW Red, ลีโอ, สิงห์) |

### Synthetic test cases (16-29) — สำหรับ regression/coverage

สร้างจาก `scripts/gen_synthetic_receipts.py` ครอบคลุม fraud types, OCR challenges, clustering, non-receipt detection ที่ curated set ยังไม่มี

| ไฟล์ | ร้านค้า | ยอดรวม | AI risk | Story |
| --- | --- | --- | --- | --- |
| `16_happy_mixed.jpeg` | รวยสุรา | ฿8,399 | low | **Happy path** — 3 items VAT คำนวณถูก, items=subtotal เป๊ะ (ทดสอบ false-positive guard) |
| `17_multi_category_large.jpeg` | ลิ้มเฮงพัฒนา | ฿553,590 | high | **Multi-category volume** — 12 items ผสมเบียร์/สุรา/วิสกี้/น้ำ/โซดา ฿500K+ |
| `18_same_merchant_a.jpeg` | รวยสุรา | ฿7,500 | high | **Merchant cluster ใบ A** — เลขบิล A001 |
| `19_same_merchant_b.jpeg` | รวยสุรา | ฿47,245 | medium | **Merchant cluster ใบ B** — ชื่อร้าน "รวย-สุรา" (มีขีด) ทดสอบ normalize |
| `20_same_merchant_c.jpeg` | รวยสุรา | ฿7,895 | high | **Merchant cluster ใบ C** — ชื่อร้าน "ร้าน รวยสุรา" — ทั้ง 3 ใบควร group เป็นร้านเดียวกัน |
| `21_vat_mismatch.jpeg` | จำปิสโตร์ | ฿10,850 | medium | **Fraud: VAT mismatch** — VAT พิมพ์ ฿850 (จริงต้อง ฿700 = 7%) |
| `22_items_total_mismatch.jpeg` | ณ บวร เทรดดิ้ง | ฿203,210 | high | **Fraud: items_total_mismatch** — ผลรวมรายการ ~฿37K ต่างจากยอดบิล ฿203K (~82%) |
| `25_unusual_amount.jpeg` | สุดาพาณิชย์ | ฿850,000 | high | **Fraud: unusual amount** — ยอดสูงผิดปกติ (ต้องมี baseline ของร้านก่อนถึง trigger) |
| `27_handwritten_spirit.jpeg` | ป้าเนเจอร์ | ฿57,140 | low | **OCR ลายมือ + spirit catalog** — บิลเขียนมือ 8 รายการ match catalog ครบ |
| `28_low_quality_combo.jpeg` | สมศักดิ์ ค้าส่ง | ฿12,000 | high | **OCR robustness** — กระดาษยับ + สีจาง + เอียง 30-45° |
| `29_sales_report.jpeg` | (ไม่ใช่ใบเสร็จ) | ฿196,970 | medium | **Non-receipt detection** — รายงานสรุปยอดขายรายเดือน, AI ควร flag "ไม่ใช่ใบเสร็จ" |

> ⚠️ Synthetic limitation: Gemini image-gen ไม่ได้คำนวณ math เป๊ะ — บางใบมี items_sum ≠ subtotal หรือ ≠ grand_total ทำให้ติด fraud flag เพิ่มจาก case ที่ตั้งใจ ใช้ดูเป็น signal coverage แทนการ assert ค่าตรงเป๊ะ

หมวดหมู่ทั้งหมดในชุดนี้: **เครื่องดื่ม**

---

## Demo Script

```text
1. Upload 01.jpeg → AI ดึงข้อมูลถูก, จัดหมวดสินค้าบุญรอด (~4-5s)
2. Upload 02.jpeg → หมวดน้ำดื่ม
3. Upload 03.jpeg + 04.jpeg → merchant_normalized = "รวยสุรา" ทั้งคู่ (cluster)
4. Upload 05.jpeg (สุดาพาณิชย์) → AI flag fraud "ปี พ.ศ. 68 ผิดปกติ" risk 0.7 high
5. Upload 06.jpeg → AI อ่านชื่อสินค้าเพี้ยน (ลีโอแบน — ที่จริงคือบรั่นดีรีเจนซี่)
   → เปิด Review page → พิมพ์ "บรั่นดี" → autocomplete จาก catalog → save → demo human-in-the-loop
6. Upload 07.jpeg–11.jpeg → เพิ่มยอดให้ dashboard ดูสมจริง
7. (เสริม) Upload 12.pdf → AI flag "ไม่ใช่ใบเสร็จ" (รายงานสรุป) — โชว์ PDF support + AI judgment
8. (เสริม) Upload 13.jpeg → fraud คนละแบบกับ 05: ยอดรวมรายการกับยอดบิลต่าง 81.9%
9. (เสริม) Upload 14.jpeg → 15 items mixed-category, ฿485K, catalog match พร้อมกันทั้ง เบียร์/สุรา/ไวน์/วิสกี้/น้ำ/โซดา
10. Approve เอกสารผ่าน Review page (จำเป็นเพื่อให้ Dashboard ติดข้อมูล)
11. Dashboard → ยอดรายวัน, top-merchants, top-products + catalog match, VAT รายเดือน, fraud summary, export CSV
```

**Pitching prep checklist:**

```bash
# 1. Reset clean state
backend/.venv/bin/python -c "import sqlite3; c=sqlite3.connect('backend/data/receipts.db').cursor(); [c.execute(f'DELETE FROM {t}') for t in ['document_items','documents','document_events','merchant_aliases']]; c.connection.commit()"
find backend/uploads -mindepth 1 -maxdepth 1 -delete

# 2. Run end-to-end + measure
backend/.venv/bin/python scripts/pitching_test.py

# 3. Approve all (so dashboard charts populate)
curl -s 'http://localhost:8000/api/documents?limit=20' | backend/.venv/bin/python -c "import sys,json,urllib.request; [urllib.request.urlopen(urllib.request.Request(f'http://localhost:8000/api/documents/{d[\"id\"]}/approve',method='POST')) for d in json.load(sys.stdin)]"
```

---

## วิธีใช้

```bash
# Upload ไฟล์เดียว
curl -X POST http://localhost:8000/api/documents/upload -F "file=@dataTest/demo/01.jpeg"

# Upload ทั้งหมดและเก็บผลลัพธ์
backend/.venv/bin/python scripts/pitching_test.py
```

## โฟลเดอร์อื่น

- `ground_truth/` — ground-truth JSON สำหรับ benchmark (`<doc_id>.json`)
- `benchmark_results/` — ผล benchmark ย้อนหลัง (`<doc_id>_<timestamp>.json`)
