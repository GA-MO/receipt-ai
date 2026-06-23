# Per-line accuracy / confidence — ทำได้จริงไหม?

## ✅ Feedback loop (2026-06-22): ยืนยันแล้วฉลาดขึ้นรอบหน้า

ก่อนหน้านี้กด "ยืนยัน" ไม่ทำให้ระบบเรียนตัวย่อหนัก (guard <50% บล็อก). แก้แล้ว:

- `upsert_alias(confirmed=True)` — คนยืนยันเอง = สัญญาณแรง → ข้าม guard semantic-jump
  (แต่ path auto-mining เดิมยังเข้ม)
- `learn_confirmed_aliases(items)` — ตอน approve/บันทึก เรียน (raw → SKU) ทุกบรรทัดที่ match
  เรียกจาก `documents.approve_document`, `bulk_approve`, และ `inbox.mark_visit_reviewed`
- **corroboration**: `build_known_forms` trust learned alias เมื่อ `hit_count >= 2` เท่านั้น
  → คนเผลอยืนยันผิดครั้งเดียวไม่ทำให้ mapping ผิดดูมั่นใจ

E2E จริง (กด "บันทึกทั้งหมด" ที่ flow → `mark-reviewed` คืน `aliases_confirmed: 24`):
`บส.ญ` ยืนยัน 2 ใบ → hit=3 → **conf 0.36 ⚠ กลายเป็น 1.00 ✓**; flagged 16→14 บรรทัด

## AI เอา alias ที่ยืนยันแล้วไปทำอะไรต่อ (3 ทาง — ยิ่งใช้ยิ่งแม่น)

1. **ใส่กลับเข้า prompt catalog** (`_build_prompt_entries` → `build_system_instruction`)
   — รอบ extract หน้า โมเดล**เห็น** "บส.ญ" เป็นคำย่อของ เบียร์สิงห์ขวดใหญ่ ในตาราง
   catalog ที่ฉีดเข้า prompt → อ่านถูกตั้งแต่แรกอย่างมั่นใจ → **ความแม่น extraction สูงขึ้น**
2. **Map อัตโนมัติหลัง extract** (`apply_aliases_to_items`) — ถ้าโมเดล emit raw "บส.ญ"
   เฉย ๆ ไม่มี code ระบบ map เข้า SKU ถูกให้ → safety net
3. **Dictionary ของ per-line confidence** (`build_known_forms`, hit≥2) — บรรทัดนั้นเขียว
   ไม่ถูก flag → **rep ตรวจน้อยลง** เหลือเฉพาะของแปลกจริง

วงจร: ยืนยัน → เรียน → รอบหน้าอ่านแม่นขึ้น + flag น้อยลง + map อัตโนมัติ → ยืนยันน้อยลง

## ✅ Implemented (2026-06-22): verifiable per-line confidence ใน pipeline

**ปัญหา:** "AI อ่าน สัวเล็ก ผิด แล้วให้คะแนนตัวเองสูง — เราตรวจสอบไม่ได้"
**ทางออก:** ไม่ให้ AI ให้คะแนนตัวเองเลย — คำนวณฝั่ง server จากสัญญาณที่ตรวจสอบได้

`backend/app/services/line_confidence.py` — `score_line(raw, code, known_forms)`:
- **familiarity** = "ข้อความที่ AI อ่าน (raw)" ตรงกับ "คำย่อ/ชื่อที่ SKU นี้เคยถูก
  ยืนยันแล้ว" ไหม (dictionary = catalog names + seed คำย่อ + product_aliases ที่ rep
  ยืนยัน) → ตัวย่อที่พิสูจน์แล้ว trust, scribble ที่ไม่เคยเห็น flag
- **catalog gap** = ไม่มี SKU → 0.30 flag เสมอ
- เก็บลงคอลัมน์เดิม `document_items.confidence` + `needs_review` (ไม่ต้อง migration)
- wire ใน `routers/documents.py` (upload path); backfill ด้วย
  `scripts/backfill_line_confidence.py`

**ตอบคำถาม "แยก สัวเล็ก ออกจาก บส.ญ ยังไง":** แยกด้วย **"เคยยืนยันไหม" ไม่ใช่ "หน้าตา
เหมือนชื่อเต็มไหม"** — พิสูจน์แล้วใน `scripts/demo_confidence_loop.py`:

```
ก่อนยืนยัน (cold-start):  บส.ญ 0.36 ⚠ | เบียร์สิงห์ 0.76 ⚠ | สัวเล็ก 0.53 ⚠   (flag หมด = ปลอดภัย)
หลังยืนยันตัวย่อที่ถูก:    บส.ญ 1.00 ✓ | เบียร์สิงห์ 1.00 ✓ | สัวเล็ก 0.53 ⚠   ← สัวเล็ก ยังโดน
```

**cold-start caveat (พูดตรง ๆ):** วันแรก dictionary ยังไม่อิ่ม → บรรทัดที่ยังไม่พิสูจน์
ถูก flag หมด (ตอนนี้ backfill แล้ว 16/93 = 17%) ปลอดภัยแต่ review เยอะ Dictionary เติมจาก
(ก) seed คำย่อใน catalog (ที่ทำให้ AI อ่านถูกตั้งแต่แรกอยู่แล้ว) (ข) ทุกครั้งที่ rep ยืนยัน
— guard `upsert_alias` กันการเรียนคำที่ห่าง <50% (กัน poison) ดังนั้นตัวย่อหนักมาก ๆ
ต้องมาทาง seed/curation ไม่ใช่ auto-learn

**สิ่งที่ยังจับไม่ได้ (ซื่อสัตย์):** "อ่านผิดแบบมั่นใจ + เป็นคำที่ดูคุ้น" จะหลุด — ไม่มี
สัญญาณ verifiable ตัวไหนจับได้ในโดเมนที่ไม่มีราคา/ยอดรวมให้ครอสเช็ค → human review
ยังเป็นด่านสุดท้าย (เราไม่เคย auto-accept)

---



คำถามกรรมการ: "อยากได้ accuracy rate ของแต่ละบรรทัด ทำได้จริงเหรอ"
คำตอบสั้น: **ได้จริง 3 ระดับ — แต่ต้องแยกให้ชัดว่าแต่ละระดับเชื่อได้แค่ไหน**

## ระดับ 1 — per-line accuracy แบบ "วัดผล" : ทำได้ และมีแล้ว ✅
เราเทียบทุกบรรทัดกับที่คน review แล้ว → รู้ว่าบรรทัดไหนถูก/ผิด
- 22 ใบจริง / 85 บรรทัด: ถูก 83, ผิด 2 = **97.6%** (จำนวน 100%)
- `scripts/measure_accuracy_truth.py --diff` พิมพ์ทุกบรรทัดที่ผิดได้เลย
นี่คือ "accuracy rate ต่อบรรทัด" ในความหมายตรงตัว — มีของจริง

## ระดับ 2 — สัญญาณ per-line ที่ระบบมี "วันนี้" : catalog match ✓/? ✅
แต่ละบรรทัด resolve เป็น SKU code ได้ (✓ เชื่อมั่น) หรือไม่ได้ (? = catalog gap → flag
ให้ review, set `needs_review`)
- จับเคส `"Singha Sparking"` (ไม่มี code) ได้
- **ข้อจำกัด**: ตอนนี้ field `confidence` ต่อบรรทัดใน DB เป็น **doc-level ที่ copy ลงทุก
  บรรทัด** (ยืนยันแล้ว: 0 docs ที่บรรทัดมีค่าต่างกัน) — ยังไม่ใช่ confidence ต่อบรรทัดจริง

## ระดับ 3 — per-line confidence จากโมเดล : ทำได้ (PoC แล้ว) แต่ไม่ perfect ⚠️
`scripts/poc_per_line_confidence.py` ให้โมเดลให้ 2 คะแนนต่อบรรทัด:
`legibility` (อ่านชัดแค่ไหน) + `match_confidence` (มั่นใจว่าตรง SKU แค่ไหน)

ผลจริง:
- **มี variation จริง 0.70–1.00** (ไม่ใช่ 0.95 หมดแบบ doc-level เดิม)
- บรรทัดลายมือกำกวมตัวจริง `"สิโอ เล็ก / สัวเล็ก"` (เคสสิงห์เล็ก↔ลีโอเล็ก)
  ได้ **legibility 0.70 ต่ำสุดของใบนั้น** → สัญญาณจับ "ลายมือเสี่ยง" ได้
- บรรทัดพิมพ์ชัด/สินค้านอก catalog (Pepsi, Singha Sparking) ได้ ~0.95 — **ถูกต้อง**
  เพราะ AI อ่านถูก (ที่คนลบออกเป็นเรื่อง scope ไม่ใช่อ่านผิด)

**ข้อจำกัดที่ต้องพูดตรง ๆ กับกรรมการ:** per-line confidence จับ "ลายมือเลือน" ได้ดี
แต่ **จับ "อ่านผิดแบบมั่นใจ" ไม่ได้** (โมเดลให้คะแนนตัวเองสูงทั้งที่ผิดได้) — ดังนั้นมันคือ
**สัญญาณ triage ไม่ใช่การรับประกัน** นี่คือเหตุผลที่ขั้นตอน human review ยังต้องอยู่

## สรุปสิ่งที่พูดบนเวทีได้
> "ได้ครับ — เราวัด accuracy ต่อบรรทัดได้จริง (97.6%) และระบบให้คะแนนความมั่นใจราย
> บรรทัดได้ ลายมือที่เลือนจะถูก flag คะแนนต่ำให้ rep ดูก่อน แต่เราไม่เคลมว่า AI รู้ตัว
> เองว่าผิด 100% — บรรทัดที่ AI ไม่มั่นใจถูกส่งให้คนยืนยันเสมอ ความแม่น 96% คือ
> *หลังจาก* ระบบช่วยกรองแล้ว"

## ถ้าจะ ship เป็นฟีเจอร์จริง (เล็ก)
1. เพิ่ม `legibility` + `match_confidence` ต่อ item ใน schema/prompt (`extraction.py`)
2. เก็บลง `document_items.confidence` (เลิก copy doc-level) + เพิ่มคอลัมน์ legibility
3. UI review: แสดงแถบความมั่นใจ + เรียงบรรทัดเสี่ยงขึ้นบน (ต่อยอดจาก ✓/? เดิม)
