# Test Data Catalog

ข้อมูลทดสอบสำหรับ Thai Receipt Intelligence
อัปเดตล่าสุด: 2026-04-08 (Gemini 3 Flash, prompt v2 — ปรับ category + fraud sensitivity)

ผลรวม: **35 ไฟล์ tested** | Category อื่นๆ ลดจาก 76% → 26% | Fraud high risk ลดจาก 59% → 37%

---

## demo/ — ไฟล์สำหรับ Pitching Day

| ลำดับ | ไฟล์ | ใช้โชว์อะไร | ที่มา |
|-------|------|-----------|-------|
| 1 | `01_happy_path.webp` | **Happy path** — อัปโหลด → AI ดึงข้อมูลถูก | groupA/3.webp |
| 2 | `02_happy_pdf.pdf` | **PDF support** | groupA/12.pdf |
| 3 | `03_beer_clean.jpeg` | **หมวดเบียร์** — AI จัดหมวดสินค้าบุญรอดได้ | groupB (รวยสุรา) |
| 4 | `04_spirits.jpeg` | **หมวดสุรา** — หงส์ทอง/แสงโสม | groupB (Elephant Brand) |
| 5 | `05_water.jpeg` | **หมวดน้ำดื่ม** | groupB (มิตรราชบุรี) |
| 6a-c | `06_same_merchant_*.jpeg` | **ร้านเดียวกัน 3 ใบ** — เทียบประวัติร้าน | groupB (รวยสุรา) |
| 7a-b | `07_similar_*.png` | **ยอดเดียวกัน** — fraud จับซ้ำ | groupA (5+6.png) |
| 8 | `08_fraud_vat.jpeg` | **Fraud: VAT ผิด** | groupB |
| 9 | `09_fraud_price.jpeg` | **Fraud: ราคาผิดปกติ** | groupB (โจวบุ่งไช้) |
| 10 | `10_multi_items.webp` | **หลายรายการ** | groupA/8.webp |

### Demo Script (15 นาที)

```
นาที 1-3:   ปัญหา → อัปโหลด 01 + 02 → AI ดึงข้อมูลเร็ว
นาที 3-5:   Boonrawd category → อัปโหลด 03 + 04 + 05 → จัดหมวดถูก
นาที 5-8:   Fraud Detection →
             06a-c (ร้านเดียวกัน 3 ใบ → ดูประวัติ)
             07a แล้ว 07b (ยอดเดียวกัน → fraud จับซ้ำ)
นาที 8-10:  Fraud detail → 08 (VAT ผิด) + 09 (ราคาผิดปกติ)
นาที 10-12: Dashboard → ยอดรายวัน, หมวดหมู่, fraud summary, export CSV
นาที 12-15: Architecture + ROI + Q&A
```

---

## Quick Reference — เลือกตาม Test Case

| ต้องการทดสอบ | ไฟล์แนะนำ |
|-------------|----------|
| **Happy path** (clean, high conf) | `groupA/1.jpg` (0%), `groupA/2.webp` (0%), `groupA/10.jpg` (0%) |
| **Fraud สูง (≥60%)** | `groupB/20260113180042082009.jpeg` (90%), `groupB/20260114001825677002.jpeg` (90%) |
| **Fraud clean (0%)** | `groupB/20260109213556685004.jpeg`, `groupB/20260117165214163001.jpeg` |
| **หมวดเบียร์** | `groupB/20260108153625237004.jpeg`, `groupB/20260109213556685004.jpeg`, `groupB/20260117165214163001.jpeg` |
| **หมวดสุรา** | `groupB/20260113180042082011.jpeg`, `groupB/20260118123859593001.jpeg` |
| **หมวดอาหาร** | `groupA/2.webp`, `groupA/7.png` |
| **PDF** | `groupB/20260109160337353001.pdf`, `groupB/20260109161032808001.pdf`, `groupB/20260109223646691001.pdf` |
| **Items เยอะ** | `groupB/20260110231354266001.jpeg` (117), `groupB/20260119161224458003.jpeg` (28) |
| **ยอดสูง (≥฿100K)** | `groupB/20260110182412680001.jpeg` (฿485K), `groupB/20260117165214163001.jpeg` (฿178K) |
| **Confidence ต่ำ** | `groupB/20260110231354266001.jpeg` (40%), `groupB/20260113211240781001.jpeg` (45%) |

---

## groupA (7 files tested)

| ไฟล์ | Format | ยอดรวม | ร้านค้า | หมวด | Items | Conf | Fraud | Tags |
|------|--------|--------|---------|------|-------|------|-------|------|
| `1.jpg` | JPG | ฿61,953 | SME MOVE | อื่นๆ | 1 | 90% | 0% | high-conf clean |
| `2.webp` | WEBP | ฿3,000 | คุณยายเบเกอรี่ | อาหาร | 1 | 90% | 0% | high-conf clean |
| `4.png` | PNG | ฿6,802,058 | บริษัท ตัวอย่าง | อื่นๆ | 5 | 60% | 75% | fraud-high high-value |
| `7.png` | PNG | ฿12,500 | ESDES | อาหาร | 1 | 90% | 0% | high-conf clean |
| `9.webp` | WEBP | ฿20,000 | GIGGLING PLATYPUS | อื่นๆ | 1 | 90% | 80% | fraud-high |
| `10.jpg` | JPG | ฿51,360 | Apple Gump | อื่นๆ | 1 | 95% | 0% | high-conf clean |
| `11.webp` | WEBP | ฿690 | อีซี่ คิดส์ | อื่นๆ | 1 | 90% | 85% | fraud-high low-value |

## groupB (19 files tested)

| ไฟล์ | Format | ยอดรวม | ร้านค้า | หมวด | Items | Conf | Fraud | Tags |
|------|--------|--------|---------|------|-------|------|-------|------|
| `20260108153625237004.jpeg` | JPEG | ฿203,210 | ณ บวร เทรดดิ้ง | **เบียร์** | 9 | 75% | 85% | fraud-high high-value |
| `20260109160337353001.pdf` | PDF | ฿56,445 | สิงห์ สามารถ | **เบียร์** | 8 | 50% | 10% | clean |
| `20260109161032808001.pdf` | PDF | ฿273,501 | สิงห์ สามารถ | เครื่องดื่มอื่นๆ | 94 | 60% | 77% | fraud-high high-value |
| `20260109173123435001.jpeg` | JPEG | ฿184,640 | จำปิสโตร์ | **เบียร์** | 5 | 85% | 45% | fraud-mid high-value |
| `20260109182259531002.jpeg` | JPEG | ฿685 | ร้านน้อยหน่า | **เบียร์** | 1 | 70% | 0% | **clean** low-value |
| `20260109213556685004.jpeg` | JPEG | ฿16,105 | กว้างพาณิชย์ | **เบียร์** | 4 | 90% | 0% | **high-conf clean** |
| `20260109223646691001.pdf` | PDF | ฿352,972 | อำ วิสกี้ | **เบียร์** | 13 | 50% | 35% | fraud-mid high-value |
| `20260110101706330004.jpeg` | JPEG | ฿48,840 | ประสงค์การค้าแพร่ | **เบียร์** | 2 | 60% | 40% | fraud-mid |
| `20260110105911473001.jpeg` | JPEG | ฿4,200 | รัก 99999 | อาหาร | 1 | 70% | 0% | clean |
| `20260110182412680001.jpeg` | JPEG | ฿485,031 | - | **เบียร์** | 15 | 65% | 60% | fraud-high high-value |
| `20260110231354266001.jpeg` | JPEG | - | สิงห์ชลบุรี | **เบียร์** | 117 | 40% | - | items มากสุด |
| `20260113180042082009.jpeg` | JPEG | ฿21,342 | ร้านโจวบุ่งไช้ | อื่นๆ | 6 | 75% | 90% | fraud-high |
| `20260113180042082011.jpeg` | JPEG | ฿30,431 | - | **สุรา** | 10 | 55% | 90% | fraud-high |
| `20260113211240781001.jpeg` | JPEG | ฿186,770 | - | **เบียร์** | 7 | 45% | 75% | fraud-high high-value |
| `20260114001825677002.jpeg` | JPEG | ฿26,475 | Shimgou izakaya | **เบียร์** | 6 | 65% | 90% | fraud-high |
| `20260117165214163001.jpeg` | JPEG | ฿178,322 | CSB | **เบียร์** | 7 | 90% | 0% | **high-conf clean** high-value |
| `20260117191638884001.jpeg` | JPEG | ฿7,470 | - | **สุรา** | 2 | 50% | 20% | clean |
| `20260118123859593001.jpeg` | JPEG | ฿130,305 | ร้านสุดาพาณิชย์ | **สุรา** | 6 | 65% | 45% | fraud-mid high-value |
| `20260119161224458003.jpeg` | JPEG | - | นครศรีเบเวอเรจ | **เบียร์** | 28 | 50% | - | low-conf |

---

## สถิติ (prompt v2, 2026-04-08)

| Metric | Before (v1) | After (v2) | Change |
|--------|-------------|------------|--------|
| Category "อื่นๆ" | 76% | **26%** | ลด 50% |
| Boonrawd products | 16% | **60%** | เพิ่ม 4x |
| Fraud high risk | 59% | **37%** | ลด 22% |
| Avg risk score | 63% | **37%** | ลดเกือบครึ่ง |

## วิธีใช้

```bash
# Upload ไฟล์เดียว
curl -X POST http://localhost:8000/api/documents/upload -F "file=@dataTest/demo/01_happy_path.webp"

# Upload ทั้งหมดและเก็บผลลัพธ์
cd backend && uv run python ../scripts/retest_all.py

# ดูผลลัพธ์ละเอียด
cat dataTest/test_results.json
```
