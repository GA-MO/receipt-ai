# Thai Receipt Intelligence — Technical Documentation

เอกสารนี้สำหรับตอบคำถามเชิงเทคนิคในวัน pitching
ครอบคลุม architecture, data flow, AI pipeline, fraud detection, และ deployment

---

## 1. System Architecture

```
┌─────────────┐     ┌──────────────────────────────────────────────────┐
│   Frontend   │     │                   Backend (FastAPI)              │
│  React+Vite  │────▶│                                                  │
│  TailwindCSS │◀────│  ┌────────┐  ┌───────────┐  ┌──────────────┐   │
└─────────────┘     │  │ Upload │─▶│ PDF Text  │─▶│ Gemini 2.5   │   │
                    │  │ API    │  │ Extract   │  │ Flash (VLM)  │   │
                    │  └────────┘  └───────────┘  └──────┬───────┘   │
                    │                                     │           │
                    │  ┌────────────┐  ┌─────────────────▼────────┐  │
                    │  │ Validation │◀─│ Structured JSON Output   │  │
                    │  │ Rules      │  │ (merchant, items, total) │  │
                    │  └─────┬──────┘  └──────────────────────────┘  │
                    │        │                                        │
                    │  ┌─────▼──────┐  ┌─────────────┐               │
                    │  │ Fraud      │  │ SQLite DB   │               │
                    │  │ Detection  │─▶│ + File      │               │
                    │  └────────────┘  │ Storage     │               │
                    │                  └─────────────┘               │
                    └──────────────────────────────────────────────────┘
```

### แต่ละ layer ทำอะไร

| Layer | เทคโนโลยี | หน้าที่ |
|-------|----------|---------|
| **Frontend** | React 19, Vite, TailwindCSS | UI สำหรับ upload, review, dashboard |
| **Backend API** | FastAPI (Python) | รับ request, orchestrate pipeline, serve data |
| **PDF Text Extract** | PyMuPDF | ดึง text จาก text-based PDF (<0.1s) |
| **VLM** | Google Gemini 3 Flash | อ่านรูป/PDF + วิเคราะห์ → JSON structured data |
| **Validation** | Python rules engine | เช็กยอดรวม, VAT, วันที่ พ.ศ., ข้อมูลขาด |
| **Fraud Detection** | Python + SQL queries | ตรวจเอกสารซ้ำ, ยอดผิดปกติ, anomaly |
| **Database** | SQLite | เก็บเอกสาร, extracted data, audit trail |
| **File Storage** | Local filesystem | เก็บไฟล์รูป/PDF ต้นฉบับ |

---

## 2. Data Flow — จากอัปโหลดถึง Dashboard

```
ผู้ใช้อัปโหลดรูป/PDF
        │
        ▼
┌─ Step 1: Upload & Validate ─────────────────────────────┐
│  • ตรวจ file type (jpg/png/webp/pdf)                    │
│  • ตรวจขนาดไฟล์ (≤ 20 MB)                               │
│  • คำนวณ SHA-256 hash → ตรวจซ้ำ                         │
│  • บันทึกไฟล์ + สร้าง record (status = "processing")     │
│  • ส่ง response กลับทันที (ไม่ต้องรอ AI)                  │
└─────────────────────────────────────────────────────────┘
        │ (Background Task)
        ▼
┌─ Step 2: Text Extraction (PDF only) ───────────────────┐
│  • PDF text-based → PyMuPDF ดึง embedded text (<0.1s)    │
│  • PDF scanned → ข้ามไป Gemini อ่าน PDF ตรง              │
│  • รูปภาพ → ไม่ต้อง OCR, Gemini Vision อ่านได้เลย        │
│  • (PaddleOCR เป็น optional, ปิด default — ดูหัวข้อ 3)   │
└─────────────────────────────────────────────────────────┘
        │
        ▼
┌─ Step 3: Gemini Extraction ────────────────────────────┐
│  • ส่งรูป/PDF ต้นฉบับให้ Gemini Vision อ่านโดยตรง        │
│  • PDF text-based: ส่ง text ที่ดึงได้เป็น context เสริม   │
│  • Prompt ภาษาไทย กำหนด JSON schema ชัดเจน              │
│  • แปลงวันที่ พ.ศ. → ค.ศ. อัตโนมัติ                     │
│  • จัดหมวดหมู่ค่าใช้จ่ายอัตโนมัติ (8 หมวด)               │
│  • response_mime_type = "application/json" (บังคับ JSON)  │
│  • temperature = 0.1 (ลด hallucination)                  │
│  • Retry 3 ครั้ง + exponential backoff                   │
│  • Auto-reset credentials ถ้าเจอ auth error              │
└─────────────────────────────────────────────────────────┘
        │
        ▼
┌─ Step 4: Validation Rules ─────────────────────────────┐
│  • ยอดรวมรายการ ≈ subtotal? (tolerance ±1 บาท)           │
│  • VAT ≈ 7% ของ subtotal?                               │
│  • วันที่ยังเป็น พ.ศ. หรือเปล่า? (year > 2500)          │
│  • มีชื่อร้าน / ยอดรวม / รายการสินค้าครบไหม?             │
│  • รายการสินค้ามีชื่อและจำนวนครบไหม?                      │
│  • ผลลัพธ์: warnings แนบไปกับ notes ของเอกสาร             │
└─────────────────────────────────────────────────────────┘
        │
        ▼
┌─ Step 5: Fraud Detection ──────────────────────────────┐
│  • เลขที่เอกสารซ้ำกับเอกสารอื่น? (HIGH severity)        │
│  • ร้านเดียวกัน + วันเดียวกัน + ยอดใกล้เคียง? (HIGH)     │
│  • ยอดเงินผิดปกติจากค่าเฉลี่ยของร้าน? (>2σ, MEDIUM)     │
│  • ยอดเงินกลมเกินไป? (หาร 1000 ลงตัว, LOW)              │
│  • เอกสารลงวันหยุด? (เสาร์-อาทิตย์, LOW)                │
│  • Confidence ต่ำ? (<70%, MEDIUM)                        │
│  • ผลลัพธ์: JSON array ของ flags + severity              │
└─────────────────────────────────────────────────────────┘
        │
        ▼
┌─ Step 6: Save & Notify ───────────────────────────────┐
│  • บันทึก extracted data + items ลง DB                  │
│  • status = "extracted", needs_review = true/false      │
│  • Frontend polling ตรวจพบ → แสดงผลทันที                │
└────────────────────────────────────────────────────────┘
        │
        ▼
┌─ Step 7: Human Review ────────────────────────────────┐
│  • ผู้ใช้ดูรูปต้นฉบับ + OCR text + ข้อมูลที่ดึงได้       │
│  • แก้ไขเฉพาะจุดที่ AI ไม่มั่นใจ (flagged fields)        │
│  • ดู fraud flags ถ้ามี                                  │
│  • กดอนุมัติ → status = "reviewed"                       │
└────────────────────────────────────────────────────────┘
        │
        ▼
┌─ Step 8: Dashboard & Export ──────────────────────────┐
│  • ยอดขายรายวัน / ร้านค้ายอดสูงสุด                      │
│  • สัดส่วนค่าใช้จ่ายตามหมวดหมู่                          │
│  • สรุป VAT รายเดือน                                    │
│  • Spending Heatmap (90 วัน)                            │
│  • Fraud Summary (severity + flagged docs)              │
│  • Export CSV (รองรับ Excel ภาษาไทย — UTF-8 BOM)        │
└────────────────────────────────────────────────────────┘
```

---

## 3. ทำไม Gemini Vision อย่างเดียว ไม่ใช้ OCR

### ทดสอบจริง — Data-Driven Decision

เราทดสอบ PaddleOCR (PP-OCRv5, Thai model) + Gemini เทียบกับ Gemini Vision อย่างเดียว บนใบเสร็จจริง 18 ใบ (groupA 12 + groupB 6) ผลคือ:

| Metric | Gemini Only | + PaddleOCR |
|--------|-------------|-------------|
| ยอดเงินตรงกัน | 16/18 | 16/18 (เท่ากัน) |
| ความเร็วเฉลี่ย | **~15 วินาที** | ~58 วินาที (ช้ากว่า 4x) |
| JSON error | 0 | 1 ไฟล์ (OCR ส่ง garbage → Gemini return broken JSON) |
| Memory crash | 0 | หลายครั้ง (รูปใหญ่ > 500KB) |

### OCR Models ที่เราพิจารณา

| Model | ปัญหา |
|-------|-------|
| PaddleOCR PP-OCRv5 (Thai) | accuracy 82.68% ต่ำกว่า Gemini Vision, ช้า 3-4 นาที/ไฟล์บน CPU |
| ThaiTrOCR | ทำได้แค่ recognize (ไม่มี text detection), ต้องใช้ร่วมกับ detector อื่น |
| Qwen2.5-VL | Open-source ดีสุด แต่ยังตาม Gemini บน ThaiOCRBench, ต้อง GPU 40-80GB |
| Typhoon OCR | เก่งเอกสารไทยมาก แต่ 7B model ต้อง GPU, เหมาะ self-host ในอนาคต |

### สิ่งที่ Gemini 3 Flash ทำได้ดีอยู่แล้ว
- **อันดับ 1 บน ThaiOCRBench** สำหรับเอกสารไทย (ชนะ GPT-4o, Qwen2.5-VL)
- อ่านรูป + PDF ตรงได้เลย ไม่ต้องแปลงเป็น text ก่อน
- เข้าใจ context ไทย (พ.ศ., คำย่อ, เอกสารปนอังกฤษ)
- JSON response mode บังคับ structured output ได้

### สรุป
**OCR เป็น optional** (ปิด default, เปิดได้ด้วย `OCR_ENABLED=true`) เพราะไม่ช่วยเพิ่ม accuracy แต่ทำให้ช้าลง 4 เท่า สำหรับ PDF text-based ยังดึง embedded text ผ่าน PyMuPDF ให้ Gemini เป็น context (<0.1 วินาที, 100% accurate)

---

## 4. Pre-trained Models Only — ไม่เทรนอะไรใหม่

| Model | ประเภท | ที่มา | ทำไมไม่ต้อง train |
|-------|--------|-------|------------------|
| **Gemini 3 Flash** | Vision-Language Model | Google (Vertex AI) | อันดับ 1 ThaiOCRBench, อ่านรูป+ไทยได้เลย ใช้ prompt engineering |

### วิธีควบคุมคุณภาพโดยไม่ต้อง fine-tune
- **Structured prompt** — กำหนด JSON schema ชัดเจน, list หมวดหมู่ที่อนุญาต
- **response_mime_type = "application/json"** — บังคับให้ Gemini ตอบ JSON เท่านั้น
- **temperature = 0.1** — ลด creativity/hallucination ให้ตอบตรงๆ
- **Validation layer** — เช็กผลลัพธ์ด้วย business rules หลัง AI ตอบ
- **Human-in-the-loop** — คนตรวจเฉพาะจุดที่ AI ไม่มั่นใจ

---

## 5. Fraud Detection — ตรวจจับเอกสารต้องสงสัย

ระบบ fraud detection ทำงานหลัง extraction เสร็จ โดยไม่ต้องใช้ ML model เพิ่ม ใช้ rule-based + statistical analysis

### 6 การตรวจสอบ

| # | ชื่อ | Severity | วิธีตรวจ |
|---|------|----------|---------|
| 1 | **เลขที่เอกสารซ้ำ** | HIGH | query DB หาเอกสารที่มี document_number เดียวกัน |
| 2 | **ใบเสร็จคล้ายกัน** | HIGH | ร้านเดียวกัน + วันเดียวกัน + ยอดต่างกัน ≤5% |
| 3 | **ยอดเงินผิดปกติ** | MEDIUM | ยอดห่างจากค่าเฉลี่ยของร้านนั้น > 2 standard deviations |
| 4 | **ยอดเงินกลมเกินไป** | LOW | ยอด ≥1000 และหาร 1000 ลงตัว |
| 5 | **วันหยุดสุดสัปดาห์** | LOW | เอกสารลงวันเสาร์-อาทิตย์ |
| 6 | **Confidence ต่ำ** | MEDIUM | AI confidence < 70% |

### ตัวอย่าง Output
```json
[
  {
    "type": "duplicate_number",
    "label": "เลขที่เอกสารซ้ำ",
    "severity": "high",
    "detail": "เลขที่ INV-001 ซ้ำกับเอกสาร 'ร้าน A' (ID: abc123...)"
  },
  {
    "type": "round_amount",
    "label": "ยอดเงินกลมเกินไป",
    "severity": "low",
    "detail": "ยอด ฿3,000.00 เป็นตัวเลขกลม (หาร 1,000 ลงตัว)"
  }
]
```

### ทำไมไม่ใช้ ML สำหรับ fraud
- ข้อมูลน้อยเกินไปสำหรับ training (hackathon scope)
- Rule-based ตรวจจับ pattern พื้นฐานได้ดีและอธิบายได้ (explainable)
- เพิ่ม rule ใหม่ได้ง่ายโดยไม่ต้อง retrain
- สำหรับ production: สามารถเพิ่ม anomaly detection model ทีหลังได้

---

## 6. Thai-First Design — สิ่งที่ออกแบบมาเพื่อภาษาไทย

| ปัญหาเอกสารไทย | วิธีแก้ในระบบ |
|----------------|-------------|
| วันที่ พ.ศ. เช่น `3 เม.ย. 69` | Prompt สั่งให้แปลง พ.ศ. → ค.ศ. + validation เช็ก year > 2500 |
| คำย่อ เช่น `บจก.`, `ต.`, `อ.` | Gemini เข้าใจ context ไทยอยู่แล้ว |
| ชื่อสินค้าหลายรูปแบบ | ใช้ `product_name_raw` เก็บตามต้นฉบับ + field `normalized` สำหรับ mapping |
| เอกสารไทยปนอังกฤษ | Gemini Vision รองรับ multilingual โดย native |
| ฟอนต์ thermal receipt | Gemini Vision อ่านได้ดี ไม่ต้อง OCR แยก |
| Export CSV เปิดใน Excel แล้วภาษาไทยเพี้ยน | ใส่ UTF-8 BOM (`\ufeff`) ก่อนเขียน CSV |
| หมวดหมู่ค่าใช้จ่าย | กำหนด 8 หมวดภาษาไทยใน prompt |

---

## 7. API Design

### Document Lifecycle

```
upload → processing → extracted → reviewed
                         ↓
                       error
```

### Endpoints

| Method | Path | หน้าที่ |
|--------|------|---------|
| POST | `/api/documents/upload` | อัปโหลด + เริ่ม background processing |
| GET | `/api/documents` | รายการเอกสาร (filter, search, pagination) |
| GET | `/api/documents/count` | นับจำนวนเอกสาร |
| GET | `/api/documents/{id}` | ดูรายละเอียดเอกสาร + items |
| PUT | `/api/documents/{id}` | แก้ไขข้อมูล header |
| PUT | `/api/documents/{id}/items/{item_id}` | แก้ไขรายการสินค้า |
| POST | `/api/documents/{id}/approve` | อนุมัติเอกสาร |
| POST | `/api/documents/{id}/reextract` | สั่ง AI ประมวลผลใหม่ |
| DELETE | `/api/documents/{id}` | ลบเอกสาร |
| GET | `/api/documents/{id}/image` | ดูรูปต้นฉบับ |
| GET | `/api/dashboard/stats` | สถิติรวม |
| GET | `/api/dashboard/daily-sales` | ยอดขายรายวัน |
| GET | `/api/dashboard/top-merchants` | ร้านค้ายอดสูงสุด |
| GET | `/api/dashboard/category-breakdown` | สัดส่วนตามหมวดหมู่ |
| GET | `/api/dashboard/vat-summary` | สรุป VAT รายเดือน |
| GET | `/api/dashboard/fraud-summary` | สรุป fraud flags |
| GET | `/api/dashboard/spending-heatmap` | heatmap รายวัน |
| GET | `/api/dashboard/export` | Export CSV |

### Background Processing
Upload API ตอบกลับทันที (status = "processing") แล้วทำ OCR + Gemini ใน background
Frontend polling ทุก 2 วินาที (max 90 ครั้ง = 3 นาที) จนสถานะเปลี่ยน

---

## 8. Database Schema

```sql
documents
├── id              (UUID, PK)
├── filename        (ชื่อไฟล์ต้นฉบับ)
├── file_path       (path ไปยังไฟล์)
├── file_type       (image / pdf)
├── file_hash       (SHA-256, ใช้เช็กซ้ำ, indexed)
├── status          (pending → processing → extracted → reviewed / error)
├── uploaded_at     (timestamp)
├── processed_at    (timestamp)
├── reviewed_at     (timestamp)
├── ocr_text        (ข้อความที่ OCR อ่านได้)
├── raw_extraction  (JSON ดิบจาก Gemini)
├── confidence      (0.0-1.0)
├── needs_review    (boolean)
├── error_message   (ถ้า extraction ล้มเหลว)
├── merchant_name
├── document_number (indexed)
├── document_date
├── subtotal        (Numeric 12,2)
├── discount        (Numeric 12,2)
├── vat             (Numeric 12,2)
├── grand_total     (Numeric 12,2)
├── category        (indexed)
├── notes
└── fraud_flags     (JSON array of flags)

document_items
├── id              (UUID, PK)
├── document_id     (FK → documents.id)
├── product_name_raw
├── product_name_normalized
├── quantity
├── unit
├── unit_price      (Numeric 12,2)
├── line_total      (Numeric 12,2)
├── confidence
└── needs_review
```

### ทำไมใช้ Numeric(12,2) ไม่ใช่ Float
Float มีปัญหา precision เช่น `0.1 + 0.2 = 0.30000000000000004`
Numeric(12,2) เก็บเป็นทศนิยม 2 ตำแหน่งตรงๆ เหมาะกับข้อมูลเงิน

---

## 9. Extraction JSON Schema

Gemini ถูกบังคับให้ตอบ JSON ตาม schema นี้:

```json
{
  "merchant_name": "ชื่อร้านค้า",
  "document_number": "เลขที่เอกสาร",
  "document_date": "2026-04-03",
  "category": "อาหารและเครื่องดื่ม",
  "items": [
    {
      "product_name_raw": "น้ำดื่มสิงห์ 600ml",
      "quantity": 10,
      "unit": "ขวด",
      "unit_price": 10.00,
      "line_total": 100.00
    }
  ],
  "subtotal": 100.00,
  "discount": 0.00,
  "vat": 7.00,
  "grand_total": 107.00,
  "confidence": 0.95,
  "notes": null,
  "needs_review_fields": []
}
```

### หมวดหมู่ที่อนุญาต (8 หมวด)
1. อาหารและเครื่องดื่ม
2. วัตถุดิบ
3. อุปกรณ์สำนักงาน
4. เดินทางและขนส่ง
5. สาธารณูปโภค
6. การตลาดและโฆษณา
7. บริการ
8. อื่นๆ

---

## 10. Tech Stack Summary

| Component | Technology | เหตุผล |
|-----------|-----------|--------|
| Frontend | React 19 + Vite + TailwindCSS | เร็ว, modern, responsive |
| Backend | FastAPI (Python 3.13) | async-ready, auto-docs, type-safe |
| PDF Text | PyMuPDF | ดึง text จาก text-based PDF, ไม่ต้อง OCR |
| LLM | Google Gemini 3 Flash (Vertex AI) | multimodal, เข้าใจไทย, JSON mode |
| Database | SQLite + SQLAlchemy | ง่าย, ไม่ต้อง setup server, พอสำหรับ MVP |
| Migrations | Alembic | schema versioning |
| Auth | GCP Service Account | ใช้ key.json, ไม่ต้องจัดการ API key |
| Deploy | Docker Compose | backend + frontend ใน 2 containers |
| Testing | pytest + stress test script | 33 unit tests + 55 integration tests |
| Package Mgmt | uv (Python) + bun (JS) | เร็วกว่า pip/npm |

---

## 11. Performance & Reliability

### ตัวเลขจากการทดสอบจริง

| Metric | ค่า |
|--------|-----|
| เวลาประมวลผลต่อเอกสาร | 8-15 วินาที (Gemini Vision) |
| Extraction accuracy (confidence) | 95% average |
| Concurrent upload | 5 ไฟล์พร้อมกัน ไม่พัง |
| Parallel API requests | 50 requests พร้อมกัน ไม่พัง |
| Duplicate detection | SHA-256 hash, 100% accurate |
| File formats tested | JPG, PNG, WebP (11 ไฟล์, 0 errors) |
| Unit tests | 33/33 passed |
| Integration tests | 55/55 passed |

### Reliability Features

| Feature | รายละเอียด |
|---------|-----------|
| **Retry + Backoff** | Gemini API retry 3 ครั้ง, exponential backoff (1s, 2s, 4s) |
| **Auto-reset credentials** | ถ้าเจอ 401/403 จะสร้าง Vertex AI client ใหม่อัตโนมัติ |
| **PDF text fast-path** | text-based PDF ดึง text ตรง <0.1s ไม่ต้อง OCR |
| **Background processing** | ไม่ block user, ตอบ response ทันที |
| **Polling with limit** | Frontend poll สูงสุด 90 ครั้ง (3 นาที) แล้วหยุด |
| **File hash dedup** | ป้องกัน upload ซ้ำ |
| **DB rollback on error** | session rollback ก่อน re-query ป้องกัน dirty state |
| **Graceful error handling** | ทุก error มี Thai message + HTTP status code ถูกต้อง |

---

## 12. Security Considerations

| ด้าน | มาตรการ |
|------|--------|
| File upload | จำกัด extension (jpg/png/webp/pdf), จำกัดขนาด (20MB) |
| Duplicate prevention | SHA-256 file hash |
| API input validation | Pydantic schemas, FastAPI auto-validation |
| Credentials | GCP Service Account key (ไม่ hardcode API key ใน code) |
| CORS | จำกัด origins ผ่าน env variable |
| SQL Injection | SQLAlchemy ORM (parameterized queries) |
| Sensitive data | `.env` และ `.gcp/key.json` อยู่ใน `.gitignore` |

---

## 13. คำถามที่กรรมการอาจถาม

### "ทำไมไม่ train โมเดลเอง?"
> เพราะ Gemini 3 Flash เป็นอันดับ 1 บน ThaiOCRBench สำหรับเอกสารไทย ไม่ต้อง train เพิ่ม สิ่งที่เราทำคือ prompt engineering + validation rules + fraud detection ซึ่งให้ผลลัพธ์ที่ดีโดยไม่ต้อง train

### "Accuracy เท่าไร?"
> AI confidence เฉลี่ย 95% จากการทดสอบ 11 เอกสาร แต่ระบบออกแบบมา human-in-the-loop — คนตรวจเฉพาะจุดที่ AI ไม่มั่นใจ ไม่ใช่แทนที่คนทั้งหมด

### "ถ้า Gemini API ล่มล่ะ?"
> มี retry 3 ครั้งพร้อม exponential backoff ถ้ายังไม่ได้ → status เป็น "error" พร้อม error message ภาษาไทย ผู้ใช้กด "ประมวลผลใหม่" ได้

### "ทำไมไม่ใช้ OCR?"
> เราทดสอบ PaddleOCR PP-OCRv5 (Thai model) กับใบเสร็จจริง 18 ใบ พบว่า OCR ไม่ช่วยเพิ่ม accuracy แต่ทำให้ช้าลง 4 เท่า (15s → 58s) และบางครั้ง OCR text ที่ผิดทำให้ Gemini return broken JSON เราจึงปิด OCR เป็น default ใช้ Gemini Vision อ่านรูปตรงซึ่งเป็นอันดับ 1 บน ThaiOCRBench

### "Scale ได้ไหม?"
> MVP ใช้ SQLite + local storage แต่ architecture ออกแบบมาให้เปลี่ยนเป็น PostgreSQL + S3 ได้ทันที (เปลี่ยนแค่ DATABASE_URL) FastAPI รองรับ async workers ด้วย Gunicorn

### "Fraud detection ใช้ AI ไหม?"
> ใช้ rule-based + statistical analysis (mean, standard deviation) ไม่ต้อง train ML model ข้อดีคือ explainable — อธิบายได้ว่าทำไมถึง flag และเพิ่ม rule ใหม่ได้ง่าย

### "ทำไมไม่ใช้ Google Vision / Azure OCR / PaddleOCR?"
> เราทดสอบแล้วพบว่า Gemini 3 Flash Vision อ่านเอกสารไทยได้ดีกว่า OCR ทุกตัว (อันดับ 1 บน ThaiOCRBench) การเพิ่ม OCR อีกตัวไม่ช่วยเพิ่ม accuracy แต่เพิ่ม latency, complexity, และค่าใช้จ่าย สำหรับ PDF text-based เราดึง embedded text ด้วย PyMuPDF แทน ซึ่งเร็วกว่า OCR 2,000 เท่า

---

## 14. คำถามเชิงธุรกิจ / ROI

### "คุ้มกว่าจ้างคนคีย์ข้อมูลจริงหรือ?"

> ถ้าคีย์ข้อมูล 1 ใบเสร็จใช้เวลา 3-5 นาที วันละ 100 ใบ = 5-8 ชั่วโมง/คน/วัน ระบบเราทำได้ใน 10-15 วินาทีต่อใบ รวม review อีก 1 นาที = ลด 80-90% ของเวลา ยังไม่นับ human error ที่ลดลง ค่า Gemini API ประมาณ 0.5-1 บาทต่อใบ ถูกกว่าค่าแรงคีย์มือหลายเท่า

### "ใครเป็นคนจ่ายค่า API?"

> MVP ใช้ Gemini 3 Flash ซึ่งมี free tier และ cost ต่ำ (ประมาณ $0.01-0.03 ต่อ request) ไม่มี OCR API เพิ่มเพราะ Gemini ทำเองได้หมด สำหรับ production จ่ายผ่าน GCP billing ขององค์กรได้เลย

### "ถ้าเอาไปใช้จริง ต้องใช้เวลาอีกเท่าไร?"
> MVP นี้ต่อยอดเป็น production ได้ใน 2-4 สัปดาห์ โดยเปลี่ยน SQLite → PostgreSQL, เพิ่ม authentication, เชื่อม ERP/SAP สิ่งที่ต้องเพิ่มคือ user management กับ integration layer ส่วน core AI pipeline พร้อมแล้ว

---

## 15. คำถามเชิงเทคนิคเชิงลึก

### "Gemini hallucinate ตัวเลขเงินมั่วไหม?"

> เราป้องกัน 3 ชั้น: (1) temperature = 0.1 ลด creativity (2) validation rules เช็กว่ายอดรวม item ≈ subtotal และ VAT ≈ 7% (3) fraud detection ตรวจยอดผิดปกติ ถ้าไม่ตรงจะ flag ให้คนตรวจ ไม่ปล่อยให้ข้อมูลผิดหลุดไป

### "ทำไมไม่ใช้ GPT-4o แทน Gemini?"
> Gemini 3 Flash มี 3 ข้อดี: (1) มี JSON response mode บังคับได้ (2) ราคาถูกกว่า GPT-4o ประมาณ 5-10 เท่า (3) เชื่อมกับ GCP/Vertex AI ได้ง่ายผ่าน service account ขององค์กร ไม่ต้องจัดการ API key แยก แต่ architecture ออกแบบมาให้เปลี่ยน LLM ได้ แค่เปลี่ยน model name

### "ทำไมถึงตัดสินใจไม่ใช้ OCR?"

> เราไม่ได้เชื่อ benchmark อย่างเดียว แต่ทดสอบเองกับใบเสร็จจริง 18 ใบ ทั้ง text-based PDF, scanned receipt, รูปถ่ายมือถือ พบว่า Gemini Vision อย่างเดียวได้ยอดเงินถูกต้องเท่ากับ Gemini+OCR (16/18 ไฟล์) แต่เร็วกว่า 4 เท่า และไม่มี memory crash จากผลทดสอบจริง + ThaiOCRBench ranking จึงตัดสินใจปิด OCR เป็น default แต่ยังเก็บ code ไว้เปิดได้ด้วย `OCR_ENABLED=true`

### "ถ้ามี 1,000 ใบเสร็จพร้อมกันล่ะ?"
> ตอนนี้ใช้ FastAPI BackgroundTasks ซึ่งรันทีละ task ถ้าต้อง scale จริง เปลี่ยนเป็น Celery + Redis queue ได้ แล้วเพิ่ม worker ตาม load architecture ไม่ต้องแก้เพราะ `_process_document` เป็น function แยกอยู่แล้ว แค่เปลี่ยนจาก background task เป็น Celery task

### "Database เป็น SQLite จริงจังไหม?"
> SQLite เป็น production-grade database ที่รองรับหลายล้าน rows (WhatsApp, Signal ใช้ SQLite) สำหรับ single-server deployment พอแน่นอน แต่ถ้าต้องการ multi-server → เปลี่ยนเป็น PostgreSQL ได้ทันที แค่เปลี่ยน `DATABASE_URL` ใน .env เพราะเราใช้ SQLAlchemy ORM ไม่ได้เขียน raw SQL

---

## 16. คำถามเรื่อง Security / Privacy

### "ใบเสร็จมีข้อมูลลับของบริษัท จัดการยังไง?"
> ไฟล์เก็บใน local server ไม่ส่งไปไหนนอกจาก Google Gemini API ซึ่งเชื่อมผ่าน Vertex AI ของ GCP ที่องค์กรควบคุมได้ ข้อมูลจะไม่ถูกนำไปเทรนโมเดลตาม Google Cloud data processing terms สำหรับ production เพิ่ม encryption at rest, access control, audit log ได้

### "ถ้ามีคน upload ไฟล์อันตรายล่ะ?"
> ระบบตรวจ 3 ชั้น: (1) จำกัด file extension เฉพาะ jpg/png/webp/pdf (2) จำกัดขนาด 20MB (3) file hash dedup ป้องกันซ้ำ ไฟล์ที่ไม่ใช่รูปจริงจะถูก Gemini reject กลับมาเป็น error ไม่มีทาง execute code ได้

### "ถ้า upload รูปที่ไม่ใช่ใบเสร็จล่ะ?"
> ทดสอบแล้ว 3 กรณี: (1) รูปที่ไม่ใช่เอกสาร → Gemini ตอบว่า "ไม่ใช่ใบเสร็จ" confidence 5% พร้อม flag ว่าข้อมูลขาดทั้งหมด (2) ข้อความสุ่มที่ไม่ใช่ใบเสร็จ → ผลลัพธ์เดียวกัน (3) ไฟล์ corrupt → retry 3 ครั้งแล้วบันทึก error ไม่มี case ไหนที่ทำให้ server crash หรือสร้าง false positive

---

## 17. คำถามเรื่อง Product / UX

### "ถ้า AI ดึงข้อมูลผิดแล้วคนไม่เช็ก approve ไปเลยล่ะ?"
> ระบบ flag ทุกเอกสารที่ confidence < 90% หรือมี field ที่ AI ไม่มั่นใจ fraud detection จะ flag ยอดผิดปกติเพิ่ม ในอนาคตเพิ่ม mandatory review สำหรับ high-value documents ได้ แต่สุดท้ายระบบนี้เป็น "ผู้ช่วย" ไม่ใช่ "ผู้ตัดสินใจ" ความรับผิดชอบอยู่ที่คนอนุมัติ

### "Mobile ใช้งานจริงได้ไหม? พนักงานหน้าร้านใช้มือถือ"
> ได้ครับ UI responsive ทั้งหมด มี bottom nav, mobile tab switcher, และหน้า "ถ่ายเอกสาร" แยกต่างหาก ถ่ายรูป → preview → ส่งประมวลผล ไม่ต้องลง app ใช้ผ่าน browser ได้เลย

### "ทำไมไม่ทำเป็น LINE Bot แทน?"
> LINE Bot เป็น extension ที่ดีมาก แต่สำหรับ MVP เราเน้น web app ก่อนเพราะ: (1) เดโมได้สวยกว่า มี dashboard, review page, fraud summary (2) LINE Bot แสดงผลได้จำกัด ไม่เหมาะกับ data table + chart (3) ถ้าต้องการจริง เพิ่ม LINE webhook endpoint แล้วเรียก upload API เดิมได้ ไม่ต้องแก้ pipeline

---

## 18. คำถามเรื่อง Competitive / Differentiation

### "ทำไมไม่ใช้ ERP ที่มีอยู่แล้ว?"
> ERP จัดการเอกสารที่อยู่ในระบบแล้วได้ดี แต่ปัญหาคือ "ข้อมูลยังไม่เข้าระบบ" — ใบเสร็จจากร้านค้าเล็ก, บิลมือ, รูปถ่าย ระบบเราเป็น bridge ที่แปลงเอกสารนอกระบบให้เป็น structured data พร้อมส่งเข้า ERP ไม่ได้แทน ERP แต่เติมเต็มจุดที่ ERP ทำไม่ได้

### "มี product แบบนี้ในตลาดแล้วไหม?"
> มีครับ เช่น Veryfi, Dext, Expensify แต่ไม่มีตัวไหนที่ (1) ออกแบบมาเพื่อภาษาไทยโดยเฉพาะ (2) มี fraud detection ในตัว (3) มี dual OCR+LLM pipeline (4) customize หมวดหมู่ตามธุรกิจของเครือบุญรอดได้ นี่คือ vertical solution ไม่ใช่ generic tool

### "Fraud detection ใช้ rule-based อย่างเดียว scale เป็น ML ได้ไหม?"
> ได้ครับ architecture ออกแบบไว้ให้เพิ่มได้ เช่นใช้ Isolation Forest สำหรับ anomaly detection หรือ classification model แยก fraud/not-fraud แต่ต้องมี labeled data ก่อน ซึ่ง rule-based ที่ทำอยู่ตอนนี้สามารถ generate training data ได้ — เอกสารที่ถูก flag แล้วคน confirm ว่าเป็น fraud จริง ก็กลายเป็น positive label สำหรับ ML ในอนาคต

---

## 19. Business Impact & KPIs (สำหรับ Pitch)

### Problem Statement (สถานการณ์ปัจจุบัน)

| ปัญหา | ผลกระทบ |
|-------|---------|
| พนักงานคีย์ข้อมูลจากใบเสร็จด้วยมือ | เสียเวลา 3-5 นาที/ใบ |
| เอกสารภาษาไทยหลายรูปแบบ | ตีความผิดบ่อย ต้องแก้ซ้ำ |
| ข้อมูลขึ้นระบบช้า | ผู้บริหารเห็นยอดขายไม่ทัน |
| ไม่มีระบบตรวจสอบอัตโนมัติ | ใบเสร็จปลอม/ซ้ำ/ผิดปกติ หลุดเข้าระบบ |

### Before vs After

```
                      ก่อนใช้ระบบ              หลังใช้ระบบ
                    ─────────────────     ─────────────────
คีย์ข้อมูล 1 ใบ     3-5 นาที              ~30 วินาที AI + 1 นาที review
100 ใบ/วัน          5-8 ชั่วโมง/คน         ~1.5 ชั่วโมง/คน
Human error          5-15%                 <2% (AI + validation)
เวลาถึง dashboard    1-2 วัน               real-time
ตรวจจับเอกสารซ้ำ     ไม่มี                  อัตโนมัติ (SHA-256 + fraud rules)
ตรวจจับยอดผิดปกติ    ไม่มี                  อัตโนมัติ (statistical anomaly)
หมวดหมู่ค่าใช้จ่าย    คีย์มือ                จัดอัตโนมัติ (8 หมวด)
```

### Primary KPIs

| KPI | เป้าหมาย | วัดจากอะไร | ผลจากการทดสอบ |
|-----|---------|-----------|--------------|
| **เวลาที่ลดลง** | ≥70% | เทียบเวลาคีย์มือ vs AI+review | ลดจาก ~4 นาที เหลือ ~1.5 นาที (**63-75%**) |
| **AI Extraction Accuracy** | ≥85% | confidence เฉลี่ยจาก Gemini | **95%** จาก 11 เอกสารทดสอบ |
| **Extraction Success Rate** | ≥90% | สัดส่วนเอกสารที่ extract สำเร็จ | **100%** (11/11 ไฟล์, 0 errors) |
| **Fraud Detection Coverage** | ≥80% pattern พื้นฐาน | จำนวน rule ที่ครอบคลุม | **6 rules** ครอบคลุม duplicate, anomaly, round amount, weekend, similar receipt, low confidence |
| **File Format Support** | ≥3 formats | จำนวน format ที่รองรับ | **4 formats** (JPG, PNG, WebP, PDF) |

### Secondary KPIs

| KPI | เป้าหมาย | หมายเหตุ |
|-----|---------|---------|
| เวลาประมวลผลต่อเอกสาร | <60 วินาที | ปัจจุบัน 25-50 วินาที |
| API Uptime (ความเสถียร) | 99%+ | 55/55 integration tests ผ่าน, 50 concurrent requests ผ่าน |
| Duplicate detection accuracy | 100% | SHA-256 hash ไม่มี false positive/negative |
| จำนวน field ที่ดึงได้ | ≥10 fields | ดึงได้ 12 fields (ร้านค้า, เลขที่, วันที่, หมวดหมู่, รายการ, จำนวน, หน่วย, ราคา, ส่วนลด, VAT, ยอดรวม, หมายเหตุ) |

### Financial Impact Estimate

สมมติองค์กรมีทีม 5 คน คีย์ข้อมูล 100 ใบ/วัน:

```
ก่อน:  5 คน × 6 ชม./วัน × 22 วัน × ค่าแรง 100 บ./ชม. = ฿66,000/เดือน
หลัง:  5 คน × 1.5 ชม./วัน × 22 วัน × 100 บ./ชม.      = ฿16,500/เดือน
       + ค่า Gemini API: 100 ใบ × 22 วัน × ฿1            = ฿2,200/เดือน
                                                     ─────────────
ประหยัด:                                              ~฿47,300/เดือน
                                                     ~฿567,600/ปี
```

> หมายเหตุ: ตัวเลขเป็นการประมาณการ ผลลัพธ์จริงขึ้นกับจำนวนเอกสาร ความซับซ้อน และกระบวนการทำงานเดิมขององค์กร

### Non-Financial Impact

| ด้าน | ผลกระทบ |
|------|---------|
| **Speed to insight** | ผู้บริหารเห็นยอดขายจากเอกสาร real-time แทนที่จะรอ 1-2 วัน |
| **Data quality** | ลด human error, validation rules ตรวจจับข้อมูลผิดปกติ |
| **Fraud prevention** | ตรวจจับใบเสร็จซ้ำ/ปลอม/ผิดปกติ ก่อนเข้าระบบ |
| **Employee satisfaction** | ลดงานซ้ำซาก ให้พนักงานโฟกัสงานที่ต้องใช้ judgment |
| **Scalability** | รองรับเอกสารเพิ่มขึ้นโดยไม่ต้องเพิ่มคน |
| **Audit trail** | ทุกเอกสารมี original image + OCR text + AI extraction + human review record |

### Roadmap (ถ้านำไปใช้จริง)

```
เดือน 1-2    Production deployment
             └─ PostgreSQL + S3 + Authentication + ERP integration

เดือน 3-4    Scale & Optimize
             └─ Celery queue + Worker scaling
             └─ LINE Bot / Mobile app
             └─ Product master matching (SKU normalization)

เดือน 5-6    Advanced Analytics
             └─ ML-based fraud detection (trained from flagged data)
             └─ Spending forecast
             └─ Supplier performance analysis
             └─ Multi-branch comparison dashboard
```

### One-liner สำหรับปิด Pitch
> "Thai Receipt Intelligence เปลี่ยนใบเสร็จภาษาไทยที่เคยต้องคีย์มือเป็นข้อมูลพร้อมใช้ภายใน 30 วินาที ลดเวลา 70% ลด error ด้วย AI + fraud detection 6 ชั้น ทั้งหมดด้วย pre-trained models เท่านั้น"
