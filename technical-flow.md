# Technical Flow — สำหรับ present (คะแนน technical)

> ร่างเพื่อเคาะ flow + wording ก่อนทำเป็นสไลด์ HTML (ธีม Ledger)
> แก้คำในนี้ได้เลย แล้วค่อยยกไปทำสไลด์

---

## Diagram 0 — พระเอก: Trust-zone (AI vs Guardrail)

แก่นของเรื่อง: **เราไม่เชื่อ LLM ดื้อๆ** — output ที่เป็น probabilistic ทุกตัว
ถูก re-ground ด้วย logic ฝั่ง server ที่ deterministic ก่อนเข้าสู่ aggregate

```mermaid
flowchart LR
    P["📸 รูปใบเสร็จ"] --> AI
    CAT["🗄 PRODUCT_CATALOG<br/>live จาก products (DB)<br/>code · ชื่อทางการ · คำย่อ/ลายมือ"] -.->|"ฉีดเข้า system prompt ทุก call<br/>(cached, auto-invalidate)"| AI1

    subgraph AI["🤖 PROBABILISTIC — AI zone (OpenRouter vision)"]
        direction TB
        AI1["อ่านรูป + จับคู่ลายมือ → code<br/>(เลือกจากชุดปิด ไม่แต่ง code เอง)"]
        AI2["คืน product_code · raw · quantity<br/>+ merchant_name (raw)"]
        AI1 --> AI2
    end

    subgraph GUARD["🛡 DETERMINISTIC — Server guardrails"]
        direction TB
        G1["code → name derive<br/>(ชื่อ-รหัส desync ไม่ได้)"]
        G2["catalog-driven unit override<br/>(ลัง/ถาด ไม่ใช่ ขวด)"]
        G0["store match: normalize + RapidFuzz<br/>→ Visit / Unknown-store"]
        G3["period / store mismatch guard"]
        G1 --> G2 --> G0 --> G3
    end

    STORE["🏪 Store master<br/>live จาก stores (DB)<br/>admin-curated · single source of truth"] -.->|"match raw merchant<br/>(exact + RapidFuzz)"| G0

    AI -->|"handoff: code + raw + qty + merchant"| GUARD
    GUARD --> OUT["✅ Trusted record<br/>→ aggregate"]

    classDef ai fill:#efe3d0,stroke:#a8794a,stroke-width:1px,color:#2b2417;
    classDef guard fill:#dfe7da,stroke:#5b7050,stroke-width:1px,color:#1f2b1a;
    classDef io fill:#f5efe1,stroke:#6b5b3e,stroke-width:1px,color:#2b2417;
    classDef data fill:#e6ddc8,stroke:#6b5b3e,stroke-width:1px,color:#2b2417;
    class AI1,AI2 ai;
    class G0,G1,G2,G3 guard;
    class P,OUT io;
    class CAT,STORE data;
```

**ประโยคปิดบนภาพ:** *"AI เดาเก่ง — แต่เราไม่ปล่อยให้เดาคนเดียว ทุก output ถูกตรวจสอบด้วยกฎที่ deterministic"*

---

## Diagram 1 — ชีวิตของรูปใบเสร็จ 1 ใบ (single-receipt pipeline)

ภาพขยาย: เส้นทางข้อมูลจริง ซ้าย→ขวา + ป้าย callout จุดที่ใส่ "ความฉลาด" เข้าไป

```mermaid
flowchart LR
    A["📸 อัปโหลด<br/>รูปใบเสร็จ N รูป"] --> B["🤖 Vision call<br/>OpenRouter · vision-only<br/>(Gemini 3 Flash)"]
    B --> C["🧠 Enrichment<br/>ฝั่ง server<br/>(catalog-driven)"]
    C --> D{"🗂 Routing<br/>จัดเข้าปลายทาง"}
    D --> E1["✅ Visit<br/>(จับคู่ร้าน + เดือนได้)"]
    D --> E2["❓ Unknown store<br/>(admin เลือก/สร้างร้าน)"]
    D --> E3["🏷 Orphan<br/>(อ่านชื่อร้านไม่ออก)"]
    D --> E4["🗑 Non-receipt<br/>(auto-purge 7 วัน)"]
    E1 --> F["📊 Aggregate<br/>(store, month) →<br/>[(product, qty)]"]

    %% callouts — จุดขายเชิง technical
    B -.->|"ฉีด live PRODUCT_CATALOG<br/>เข้า system prompt ทุกครั้ง + JSON schema"| B
    B -.->|"retry + exponential backoff ×3<br/>+ defensive JSON parse"| B
    C -.->|"code → name derive ฝั่ง server<br/>ชื่อ-รหัส desync ไม่ได้"| C
    C -.->|"catalog-driven unit override<br/>ลัง/ถาด/แพ็ค ไม่ใช่ ขวด"| C
    D -.->|"auto-attach visit<br/>+ period / store mismatch detection"| D

    classDef step fill:#f5efe1,stroke:#6b5b3e,stroke-width:1px,color:#2b2417;
    classDef route fill:#e8dcc0,stroke:#6b5b3e,stroke-width:1px,color:#2b2417;
    class A,B,C,F step;
    class D,E1,E2,E3,E4 route;
```

### Callout — wording ที่จะปักบน flow (เคาะคำตรงนี้)

| จุดในflow | callout (สั้น) | ประโยคขยายตอนพูด |
|---|---|---|
| Vision call | **Live catalog injection** | ฉีด PRODUCT_CATALOG จาก DB เข้า system prompt ทุกครั้ง → model อ่าน shorthand ออกเพราะ "รู้จักสินค้า" ไม่ใช่เดา |
| Vision call | **Resilient call** | retry exponential backoff 3 ครั้ง + parse JSON แบบกัน output เพี้ยน (array/nested/หมวดผิด) |
| Enrichment | **Code→name derive** | LLM ส่งแค่ `product_code` + `raw` ชื่อแสดงผลคำนวณฝั่ง server → กัน LLM มั่วชื่อ |
| Enrichment | **Catalog-driven unit** | หน่วยมาจาก catalog (ลัง/ถาด) ไม่ใช่จาก model → aggregate ไม่ปนหน่วย (domain knowledge) |
| Routing | **Self-routing + mismatch guard** | ระบบจัดเข้า visit เอง + ตรวจ period/store ไม่ตรงให้ คนแค่ยืนยัน |

---

## Diagram 2 — Layered architecture (เผื่อกรรมการถาม "สถาปัตยกรรม")

```mermaid
flowchart TB
    subgraph FE["Frontend"]
        FE1["React 19 + Vite<br/>Mantine v9 · Tailwind v4<br/>SSE live progress"]
    end
    subgraph API["Backend — FastAPI (Python 3.11+)"]
        API1["routers: inbox · documents<br/>visits · stores"]
        API2["services: extraction · catalog<br/>merchants(rapidfuzz) · visits · validation"]
    end
    subgraph AI["AI layer"]
        AI1["OpenRouter (OpenAI SDK)<br/>vision-only · swap ผ่าน OPENROUTER_MODEL"]
    end
    subgraph WORK["Async worker"]
        W1["arq + Redis (opt-in)<br/>fallback: BackgroundTasks + Semaphore(1)"]
    end
    subgraph DB["Storage"]
        DB1["SQLite + SQLAlchemy + Alembic"]
        DB2["Image files = audit evidence"]
    end

    FE1 -->|REST + SSE| API1
    API1 --> API2
    API2 --> AI1
    API2 --> W1
    API2 --> DB1
    W1 --> AI1
    API2 --> DB2

    classDef box fill:#f5efe1,stroke:#6b5b3e,stroke-width:1px,color:#2b2417;
    class FE1,API1,API2,AI1,W1,DB1,DB2 box;
```

---

## ตัวเลขที่จะโชว์ (technical credibility)

- **1 vision call / ใบเสร็จ** (one-shot — ไม่มี agentic loop)
- **6 ฟิลด์ / ใบเสร็จ**: merchant(raw+normalized), document_number, document_date, category, items[]
- **113 tests** (pytest) + `make typecheck` (tsc strict)
- **4 หมวดสินค้า** (Singha-Online taxonomy)
- retry **×3** · auto-purge non-receipt **7 วัน**

> ⚠️ อย่าโชว์: fraud / price / VAT / discount / totals — ถอดออกหมดแล้ว (pivot พ.ค. 2026) ถ้าโชว์แล้วโดนถามจะตอบไม่ตรง
