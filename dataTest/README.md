# Test Data Catalog

ข้อมูลทดสอบสำหรับ Thai Receipt Intelligence
อัปเดตล่าสุด: 2026-05-06 (curated set, 11 ไฟล์ + โมเดล `gemini-3.1-flash-lite-preview`)

ทั้งหมดอยู่ใน `demo/` — ใช้สำหรับทั้ง pitching และ regression testing

**Model ปัจจุบัน:** `google/gemini-3.1-flash-lite-preview` ผ่าน OpenRouter

- Latency p50 ≈ 4.5s, p95 ≈ 6s (เร็วกว่า 2.5-flash ~45%)
- Avg confidence ≈ 0.93

**Filename convention:** ตั้งชื่อแบบ sequential `01.jpeg`–`11.jpeg` ตามลำดับเดโม — README นี้คือ source of truth สำหรับว่าแต่ละไฟล์โชว์อะไร

---

## demo/ — ไฟล์ทดสอบทั้งหมด (11 ไฟล์)

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
7. Approve เอกสารผ่าน Review page (จำเป็นเพื่อให้ Dashboard ติดข้อมูล)
8. Dashboard → ยอดรายวัน, top-merchants, top-products + catalog match, VAT รายเดือน, fraud summary, export CSV
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
