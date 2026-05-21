# Visit-Centric Pivot Plan

> Drafted 2026-05-21. Pivots the system from "rich single-receipt extraction" to
> "monthly product-sales aggregation per store visit" after root-cause discovery
> with real field users.

## 1. Problem & Root Cause

**Current user workflow (sales rep / merchandiser):**
1. Visit a store once a month.
2. Photograph all of that month's sales receipts — both Boonrawd and competitor
   products (10–30 images per visit).
3. Back at the office, open each receipt one by one and manually pick the
   product from a catalog dropdown, type the quantity.
4. Attach the original image so auditors can sample-check later.

**What the business actually needs:**

`(store, month) → [(product, quantity)]` — for every store, every month, every
brand on the shelf (own + competitor).

VAT extraction, fraud detection, document-number capture, payment-method
detection — all built into the current system — are **not** part of this real
need. They are nice-to-haves that consumed prompt budget and dev time.

## 2. Design Decisions (locked 2026-05-21)

| Question | Decision | Notes |
|----------|----------|-------|
| Store identity | Visit table + `store_key = merchant_normalized` | No standalone Store entity yet — promote later if needed. |
| Competitor catalog seed | None up-front | Reuse `CatalogGapEvent` admin workflow to grow catalog from real receipts. |
| Visit time scope | Aggregation is query-time over `document_date` | Visit is a light grouping, no `month` column. |
| Existing data | Migrate — backfill Visit per `merchant_normalized` | Don't lose history. |
| Per-doc Review page | Remove | Drill-down inside Visit replaces it. |
| Fraud + VAT analysis | Remove from prompt + code | Demo target doesn't need it; saves tokens. |
| Demo wow moment | "Drop 20 photos → aggregate table in < 1 min" | Drives all priority calls below. |
| Legacy single-file upload | Keep, auto-create Visit | Don't break existing mobile capture flow. |
| Inline edit on aggregate row | Skip — edit only via doc drill-down | Aggregate refresh after doc edit. |

## 3. Target Architecture

```
                  ┌────────────────────────────────────┐
                  │   Visit (new)                      │
                  │   id, store_key, store_label,      │
                  │   rep_name, notes, created_at      │
                  └────┬───────────────────────────────┘
                       │ 1
                       │
                       │ N
              ┌────────▼──────────────┐
              │  Document (existing)  │ +visit_id FK (nullable)
              └────────┬──────────────┘
                       │ 1
                       │
                       │ N
              ┌────────▼──────────────┐
              │  DocumentItem         │ unchanged
              └───────────────────────┘
```

**Aggregation** is computed on demand by a service that groups
`DocumentItem` rows across docs belonging to the same Visit (optionally
filtered by `document_date` range). No materialized table — keeps writes
simple, query is cheap at hackathon scale.

## 4. Slice 1 — MVP Demo Path

Goal: cover the demo wow moment end-to-end. Other niceties wait for Slice 2.

### 4.1 Schema + migration

**Files**
- [backend/app/models.py](backend/app/models.py) — add `Visit` model, add `Document.visit_id` column.
- `backend/alembic/versions/<new>_add_visits.py` — new migration.

**Schema**
```python
class Visit(Base):
    __tablename__ = "visits"
    id = Column(String, primary_key=True, default=_gen_id)
    store_key = Column(String, nullable=True, index=True)  # = merchant_normalized
    store_label = Column(String, nullable=True)            # human-friendly display
    rep_name = Column(String, nullable=True)               # free text, no auth yet
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)
    documents = relationship("Document", back_populates="visit")

# Document changes:
visit_id = Column(String, ForeignKey("visits.id"), nullable=True, index=True)
visit    = relationship("Visit", back_populates="documents")
```

**Migration**
1. Create `visits` table.
2. Add `documents.visit_id` (nullable).
3. Add composite index `(visit_id, document_date)`.
4. Backfill: `INSERT INTO visits (id, store_key, store_label, created_at)
   SELECT uuid(), merchant_normalized, MIN(merchant_name), MIN(uploaded_at)
   FROM documents WHERE merchant_normalized IS NOT NULL
   GROUP BY merchant_normalized` — then `UPDATE documents SET visit_id = …`
   matching on `merchant_normalized`. Docs with `merchant_normalized IS NULL`
   are left orphaned (visible in legacy list view, not in any Visit).

### 4.2 Strip fraud + VAT focus from extraction

**Files**
- [backend/app/services/extraction_combined.py](backend/app/services/extraction_combined.py)
  — delete `_FRAUD_SCHEMA_ADDITION`, `_parse_fraud_block`,
  `compute_history_fraud_checks`, `merge_fraud_results`. Keep
  `extract_with_fraud()` but rename → `extract()` and have it just call the
  combined system instruction (now equal to legacy's
  `build_system_instruction`). Net result: combined and legacy converge.
- [backend/app/services/extraction.py](backend/app/services/extraction.py) —
  in `_SYSTEM_INSTRUCTION_TAIL_TEMPLATE`:
  - Reword "PRODUCT_CATALOG ของเครือบุญรอด" → "PRODUCT_CATALOG (เครือบุญรอด + คู่แข่งที่ระบบเรียนรู้ไว้)".
  - Add a short paragraph: "ถ้าเจอสินค้าจากแบรนด์คู่แข่ง (ช้าง / ลีโอ-คู่แข่ง / ไฮเนเก้น / โค้ก / เป๊ปซี่ / อาซาฮี ฯลฯ) ให้ extract ชื่อตามที่อ่านได้ใน `product_name_raw` ตามปกติ — ห้าม map กลับเป็น SKU ของบุญรอด, product_code = null."
  - Compress VAT block from ~12 bullets to ~3 (keep just: subtotal pre-VAT, items VAT-inclusive note). Don't remove — auditors still want it parsed.
  - Update one-shot example to keep current shape (it already includes a non-catalog item — perfect).
- [backend/app/routers/documents.py](backend/app/routers/documents.py) — remove
  any code path that reads/writes `fraud_flags`, calls `compute_history_fraud_checks`,
  or merges fraud results. Keep the `fraud_flags` column itself (rollback insurance).
- [backend/app/services/extraction_agentic.py](backend/app/services/extraction_agentic.py)
  — remove `emit_fraud_analysis` tool + the fraud invocation step.
- [backend/app/services/extraction_tools.py](backend/app/services/extraction_tools.py)
  — keep `lookup_catalog` (still useful for cross-brand mapping); remove
  `check_merchant_history` and `emit_fraud_analysis` tool declarations.
- Settings: drop `use_combined_extraction` toggle — single path going forward.

### 4.3 Visit API

**File**: [backend/app/routers/visits.py](backend/app/routers/visits.py) — new.

| Endpoint | Behavior |
|----------|----------|
| `POST /api/visits` | Create empty Visit. Body: `{store_label?, rep_name?, notes?}`. |
| `POST /api/visits/{id}/documents` | Multipart bulk upload (N files). Creates one Document per file, sets `visit_id`, kicks off extraction. Returns `{visit_id, document_ids[]}`. After all docs settle, sets `visit.store_key` from the most-common `merchant_normalized` across docs. |
| `GET /api/visits` | Paginated list. Filters: `store_key`, `from`, `to` (filters by docs in range), `rep_name`. |
| `GET /api/visits/{id}` | Visit detail: docs[] + aggregate (`?from=` / `?to=` for time slice). |
| `GET /api/visits/{id}/stream` | SSE — emits per-doc completion events. Reuses [`events.py`](backend/app/events.py) pattern. |
| `PATCH /api/visits/{id}` | Update store_label / rep_name / notes. |
| `DELETE /api/visits/{id}` | Soft delete (`deleted_at`). Documents stay (their visit_id becomes a dangling reference, surfaced in legacy view). |
| `PATCH /api/documents/{id}` | Extend existing route to allow `visit_id` change (move doc between visits). |

**Legacy `POST /api/documents` keeps working**: after a single-file upload
completes extraction, an after-extract hook creates a Visit if
`visit_id IS NULL`, keyed on the doc's `merchant_normalized`. Existing Visit
with the same `store_key` is reused.

### 4.4 Aggregation service

**File**: [backend/app/services/visit_aggregate.py](backend/app/services/visit_aggregate.py) — new.

```python
def aggregate_visit(db: Session, visit_id: str, *, date_from=None, date_to=None) -> list[AggregateRow]:
    """Group line items belonging to visit's docs by SKU (or normalized name fallback).

    AggregateRow:
      - product_code: str | None
      - display_name: str
      - manufacturer: str | None       # "Boonrawd" / "ThaiBev" / None
      - is_catalog_match: bool
      - total_quantity: float
      - unit: str | None               # taken from the most common unit across contributors
      - source_doc_ids: list[str]
      - source_count: int              # how many docs contributed
    """
```

Grouping key precedence:
1. `product_code` (catalog match — wins).
2. Lowercased+stripped `product_name_normalized`.

Unit normalization: out of scope for slice 1. If contributors mix units
("ลัง" + "ขวด"), surface a warning row and let the user resolve.

### 4.5 Frontend — Visit-centric pages

**Removed**
- [frontend/src/pages/ReviewPage.tsx](frontend/src/pages/ReviewPage.tsx) and its route.

**Added**
- `/visits` — list page. Table of visits with store_label, rep, date range
  (min/max document_date among contained docs), doc count, total qty.
- `/visits/new` — create + bulk upload page. Mantine Dropzone (multi),
  rep_name input, store hint optional. Submits → POST `/visits` then POST
  `/visits/:id/documents`. Shows SSE-driven progress bar.
- `/visits/:id` — detail page. **Main = pivot table** sorted by qty desc:
  `[product | qty | unit | manufacturer | docs(count)]`. Column right = list
  of docs (filename, status, doc date). Click product row → expand to show
  per-doc breakdown. Click doc → drawer opens with image + line items
  editable (this is where the old ReviewPage's editing lives now).

**Existing pages adjusted**
- [DocumentsPage.tsx](frontend/src/pages/DocumentsPage.tsx) — keep, but
  re-label to "All documents (audit view)" — useful for orphaned legacy
  docs and for finding a specific doc across visits. Remove category
  filter chips that don't fit the new taxonomy.
- [DashboardPage.tsx](frontend/src/pages/DashboardPage.tsx) — trim to:
  total visits, total docs, top products (this month), share of doc by
  manufacturer (Boonrawd vs ThaiBev vs unknown). Remove fraud detection
  panel.

**API client**: extend [api/client.ts](frontend/src/api/client.ts) +
[api/queries.ts](frontend/src/api/queries.ts) with `useVisits`,
`useVisit(id)`, `useCreateVisit`, `useUploadToVisit`, `useVisitStream`.

### 4.6 Test scope

- New backend tests: `tests/test_visits_router.py` (create, bulk upload,
  aggregate, list-filter, soft delete, legacy auto-visit creation).
- New backend tests: `tests/test_visit_aggregate.py` (grouping by
  product_code, fallback by normalized name, date filter, mixed-unit
  warning).
- Migrate or delete existing fraud tests that no longer apply.
- E2E run: `make dev`, drop ~10 receipts from `dataTest/` into a single
  Visit via the new UI, confirm aggregate table is correct against a
  hand-calculated baseline.

## 5. Slice 2 — Post-Demo Polish

- Inline edit on aggregate row (rejected for slice 1 — revisit if demo
  feedback asks for it).
- Manufacturer-based dashboard (Boonrawd vs competitor share %, requires
  catalog growth + `Product.manufacturer` to be populated).
- Unit normalization service (ลัง → ขวด, แพ็ค → ขวด, with per-SKU pack
  size from catalog).
- Re-extract entire Visit (parallel, with progress bar).
- Mobile capture flow that auto-creates Visit when offline-queued photos
  upload.
- Auth + per-rep visit ownership.
- Audit role (read-only + flag-for-recheck UI).

## 6. Out of Scope (this iteration)

- Separate Store entity / store master data import.
- Seeding competitor SKUs up-front.
- Dropping `fraud_flags`, `vat`, `discount`, etc. columns (schema stays;
  just unused).
- CSV export of aggregate (easy follow-up — defer to after demo).
- Mobile-specific re-design of Visit pages (responsive but not redesigned).

## 7. Open Questions / Risks

- **Mixed-merchant uploads in one Visit**: current plan creates one Visit
  regardless of how many merchants are in the batch — `store_key` ends up
  = most-common merchant. If a batch has truly mixed merchants we'll see
  it in the aggregate (multiple manufacturers, weird "rest" group). May
  need a "split visit" action; defer until we hit it in real data.
- **Catalog gap event noise**: every competitor receipt will trigger gap
  events. Need to revisit the [admin gap workflow](backend/app/routers/)
  UX once volume hits — current UI may not scale to 100s of unknown SKUs.
- **Visit date semantics**: aggregating across `document_date` ranges
  works, but a single batch can have receipts from different months. UX
  should display the visit's doc-date range prominently to avoid
  confusion ("I uploaded April photos — why does May data show up?").
- **Test data**: `dataTest/` is mostly Boonrawd-heavy. To stress the
  competitor path before demo, collect a handful of competitor receipts
  (Chang, Heineken, Coke) — separate ask to user.

## 8. Acceptance Criteria for Slice 1

The demo path passes when:

1. From `/visits/new`, drop 20 receipt photos. Within < 60s the page
   shows: per-doc progress, then an aggregate table listing every product
   with summed quantity, with the source receipt count per row.
2. Clicking a product row expands to show which docs contributed, with
   per-doc quantities.
3. Clicking a doc opens a drawer with the photo and editable line items;
   editing a qty + saving causes the aggregate to refresh on close.
4. The list at `/visits` shows the new visit with a sensible
   `store_label` (mode of `merchant_normalized` from its docs).
5. Existing data from before the migration is visible as historical
   Visits, grouped by `merchant_normalized`.
6. Single-file legacy upload (`POST /api/documents`) still works and
   auto-creates / joins the right Visit.
7. Backend tests pass (`make test`); `dataTest/` E2E run produces sane
   aggregates within manual-spot-check tolerance.
