# Thai Receipt Intelligence Plan

## Project Summary
`Thai Receipt Intelligence` คือระบบ AI ที่แปลงใบเสร็จและเอกสารการขายภาษาไทยให้เป็นข้อมูลยอดขายพร้อมใช้งาน โดยใช้ `pre-trained models only` และไม่เทรนโมเดลใหม่

ระบบจะรับรูปภาพหรือ PDF ของเอกสารภาษาไทย แล้วประมวลผลผ่าน OCR, LLM extraction, validation rules, และ human review เพื่อให้ได้ข้อมูล structured สำหรับ export หรือแสดงผลบน dashboard

## Why This Project
- ลดเวลาการคีย์ข้อมูลจากเอกสารขายด้วยมือ
- ลดความผิดพลาดจากการตีความเอกสารภาษาไทยหลายรูปแบบ
- ทำให้ข้อมูลยอดขายเข้าสู่ระบบเร็วขึ้น
- ต่อยอดเป็น data insight และ decision support ได้
- สามารถทำ MVP ได้ภายในเวลาประมาณ 1 เดือน

## Hackathon Fit
- เพิ่มประสิทธิภาพการทำงาน
- ลดความซ้ำซ้อนของงาน manual
- ช่วยให้ตัดสินใจจากข้อมูลได้เร็วขึ้น
- ต่อยอดจาก use case ด้านการเก็บข้อมูลยอดขายและการจัดการเอกสาร

## Core Problem
การเก็บข้อมูลยอดขายจากร้านค้ายังอาศัยใบเสร็จ บิลเงินสด ใบกำกับภาษี หรือรูปถ่ายเอกสารจากมือถือ ทำให้เกิดปัญหา:

- ต้องคีย์ข้อมูลด้วยมือ ใช้เวลามาก
- เอกสารภาษาไทยมีรูปแบบหลากหลายและอ่านยาก
- ข้อมูลขึ้นระบบช้า ไม่ทันต่อการวิเคราะห์หรือสรุปยอด
- ชื่อสินค้า วันที่ และข้อมูลยอดเงินมักไม่เป็นมาตรฐาน

## Target Users
- Sales Operations
- Trade Marketing
- Distributor Operations
- Back Office ที่ต้องรวบรวมข้อมูลยอดขายจากเอกสาร

## Proposed Solution
ระบบจะทำงานตาม flow นี้:

1. ผู้ใช้อัปโหลดรูปหรือ PDF ของเอกสารการขายภาษาไทย
2. OCR อ่านข้อความจากเอกสาร
3. LLM แยกและตีความ field สำคัญจากข้อความ OCR
4. Validation layer ตรวจสอบความถูกต้องของข้อมูล
5. ระบบแสดงผลให้ผู้ใช้ review เฉพาะจุดที่ AI ไม่มั่นใจ
6. บันทึกผลและส่งออกเป็น CSV หรือ dashboard

## Thai-First Requirements
เพื่อให้ระบบโดดเด่นเรื่องภาษาไทย ควรรองรับ:

- วันที่ภาษาไทยและ พ.ศ.
- คำย่อภาษาไทย เช่น `บจก.`, `สาขา`, `ต.`, `อ.`
- ชื่อสินค้าไทยหลากหลายรูปแบบ
- เอกสารไทยปนอังกฤษ
- ใบเสร็จจากเครื่องพิมพ์ความร้อนที่ตัวอักษรไม่ชัด
- การ normalize คำที่คล้ายกัน เช่น `รวมสุทธิ`, `ยอดสุทธิ`, `ยอดชำระ`

## MVP Scope
MVP ควรจำกัดให้แคบพอที่จะเดโมได้แน่นภายใน 1 เดือน

### In Scope
- อัปโหลดรูปและ PDF
- รองรับเอกสาร 2-3 ประเภท
- ดึง field สำคัญจากเอกสารภาษาไทย
- มีหน้า review เพื่อแก้ไขข้อมูล
- export CSV หรือแสดงผลใน dashboard
- duplicate check เบื้องต้น

### Suggested Fields
- ชื่อร้านค้า
- เลขที่เอกสาร
- วันที่เอกสาร
- รายการสินค้า
- จำนวน
- หน่วย
- ราคาต่อหน่วย
- ส่วนลด
- VAT
- ยอดรวมสุทธิ

### Out of Scope
- การเชื่อม ERP แบบ production-ready
- การรองรับเอกสารทุกประเภทตั้งแต่แรก
- การทำ workflow อนุมัติหลายชั้น
- การเทรนหรือ fine-tune โมเดล

## Functional Requirements
### Upload and Input
- อัปโหลดไฟล์รูปภาพหรือ PDF
- preview เอกสารก่อนประมวลผล
- รองรับการอัปโหลดทีละไฟล์หรือ batch เล็กๆ

### AI Extraction
- เรียก OCR เพื่ออ่านข้อความ
- ใช้ LLM แยกข้อมูลเป็น JSON มาตรฐาน
- แสดง confidence หรือ uncertainty field

### Validation
- ตรวจรูปแบบวันที่
- ตรวจยอดรวมกับรายการสินค้า
- ตรวจ VAT และยอดสุทธิ
- ตรวจชื่อสินค้ากับ master data
- ตรวจเอกสารซ้ำจากเลขที่เอกสารและยอดเงิน

### Review and Output
- ให้ผู้ใช้แก้ข้อมูลที่ระบบไม่มั่นใจ
- บันทึกข้อมูลลงฐานข้อมูล
- export CSV ได้
- แสดง dashboard ยอดขายเบื้องต้นได้

## Non-Functional Requirements
- รองรับภาษาไทยเป็นหลัก
- response time ต่อเอกสารต้องเร็วพอสำหรับเดโม
- มี audit trail เบื้องต้นว่า AI ดึงข้อมูลอะไรมา
- ออกแบบให้ human-in-the-loop ป้องกันความผิดพลาด

## Recommended Architecture
## Frontend
- หน้าอัปโหลดเอกสาร
- หน้า review extracted data
- หน้า dashboard สรุปผล

## Backend API
- รับไฟล์
- orchestrate OCR และ LLM
- validate และ normalize ข้อมูล
- บันทึกลงฐานข้อมูล

## AI Services
- OCR pre-trained service
- LLM pre-trained service
- optional embedding/search สำหรับช่วย map ชื่อสินค้า

## Data Layer
- document storage
- extracted fields
- validation status
- review history
- export data

## Suggested Tech Stack
- Frontend: `Next.js`
- Backend: `Next.js API routes` หรือ `FastAPI`
- Database: `Postgres` หรือ `Supabase`
- Storage: `Supabase Storage` หรือ object storage
- OCR: `Google Vision`, `Azure Document Intelligence`, หรือ `Mistral OCR`
- LLM: `OpenAI`, `Claude`, หรือ `Gemini`

## Model Usage Plan
ใช้เฉพาะ pre-trained services และ orchestration logic

### OCR Model Responsibilities
- อ่านข้อความไทยจากเอกสาร
- ตรวจจับ text block หรือ line item

### LLM Responsibilities
- แยก field สำคัญจาก OCR text
- ตีความคำไทยที่หลากหลาย
- normalize วันที่ พ.ศ. เป็น format มาตรฐาน
- สรุปผลให้อยู่ใน JSON schema เดียวกัน

### Rules Engine Responsibilities
- validate ยอดรวม
- check missing field
- detect duplicate document
- match ชื่อสินค้าเข้ากับ master SKU

## Proposed JSON Output Schema
```json
{
  "merchant_name": "",
  "document_number": "",
  "document_date": "",
  "currency": "THB",
  "items": [
    {
      "product_name_raw": "",
      "product_name_normalized": "",
      "quantity": 0,
      "unit": "",
      "unit_price": 0,
      "line_total": 0
    }
  ],
  "subtotal": 0,
  "discount": 0,
  "vat": 0,
  "grand_total": 0,
  "confidence": 0,
  "needs_review": true
}
```

## UX Flow
1. User uploads receipt image or PDF
2. System extracts OCR text
3. System runs LLM extraction and normalization
4. System shows extracted fields with confidence highlights
5. User reviews only flagged fields
6. User confirms and exports sales data

## Delivery Plan
## Week 1: Discovery and Setup
- finalize use case and KPI
- collect sample Thai receipts and documents
- define extraction schema
- set up project repo and app skeleton
- integrate one OCR provider and one LLM provider

## Week 2: Core Extraction
- build upload flow
- implement OCR pipeline
- implement LLM extraction prompt and parser
- support Thai date normalization
- support key financial fields

## Week 3: Validation and Review UI
- build review screen
- add confidence and flagged fields
- add validation rules for totals and duplicates
- add product name normalization with simple mapping
- persist extracted results to database

## Week 4: Dashboard and Demo Hardening
- build simple dashboard and CSV export
- test with multiple Thai document formats
- improve prompts and error handling
- prepare demo script and pitch deck
- define measured impact from sample run

## Team Plan
สำหรับทีม 3-5 คน แนะนำการแบ่งงานแบบนี้

- Product/Business: define use case, KPI, pitch
- Frontend: upload flow, review UI, dashboard
- Backend: orchestration API, validation, persistence
- AI/Integration: OCR, prompt engineering, schema extraction
- QA/Demo: sample data, testing, demo scenario

## Demo Plan
เดโมควรมี 3 ช่วง

1. โชว์ pain point จากการคีย์ข้อมูลใบเสร็จภาษาไทยด้วยมือ
2. อัปโหลดเอกสารจริง 2-3 แบบ และโชว์ AI แยกข้อมูลอัตโนมัติ
3. โชว์ผลลัพธ์ใน dashboard หรือ CSV พร้อมสรุป impact

## Success Metrics
- เวลาประมวลผลต่อเอกสาร
- accuracy ของ field สำคัญ
- จำนวน field ที่ต้องแก้ด้วยมือ
- เวลาที่ลดลงเทียบกับ manual entry
- จำนวนเอกสารที่รองรับใน MVP

## Risks and Mitigations
### Risk: OCR อ่านใบเสร็จจางไม่ดี
Mitigation: ใช้ image preprocessing และให้ user review

### Risk: เอกสารหลากหลายเกินไป
Mitigation: จำกัดเอกสาร 2-3 format ใน MVP

### Risk: ชื่อสินค้าไม่ตรง master
Mitigation: ใช้ product alias mapping และ review step

### Risk: ยอดรวมไม่ตรงจาก OCR error
Mitigation: ใช้ validation rules และ highlight mismatch

## Judging-Oriented Pitch Points
- ใช้ AI เพื่อแก้ปัญหางานจริง ไม่ใช่แค่ demo OCR
- โฟกัสภาษาไทยซึ่งมีความซับซ้อนและเป็น pain point ชัด
- ใช้ pre-trained models only จึงทำ MVP ได้เร็วและ deploy ได้จริง
- วัด impact เชิงธุรกิจได้ชัด เช่น เวลาและความถูกต้อง
- มี architecture ที่ต่อยอดสู่ production ได้

## Elevator Pitch
`Thai Receipt Intelligence` คือ AI ผู้ช่วยอ่านเอกสารการขายภาษาไทยและแปลงให้เป็นข้อมูลยอดขายพร้อมใช้ในไม่กี่นาที ลดงานคีย์มือ ลดความผิดพลาด และช่วยให้ธุรกิจเห็นข้อมูลเร็วขึ้น โดยใช้ pre-trained models เท่านั้น

## Next Steps
1. รวบรวมตัวอย่างเอกสารไทยจริง 20-30 ใบ
2. เลือก OCR provider และ LLM provider สำหรับ MVP
3. นิยาม extraction schema และ KPI ที่จะใช้วัดผล
4. เริ่มพัฒนา upload -> extract -> review -> export flow
