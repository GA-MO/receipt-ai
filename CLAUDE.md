# CLAUDE.md

## Project overview

Thai Receipt Intelligence — a visit-centric receipt-processing tool for
Boonrawd sales reps. Reps visit retail stores each month, photograph the
month's receipts (own + competitor SKUs), and the system extracts
**(product, quantity)** per receipt then rolls it up into `(store, month) →
[(product, qty)]`. Image files stay in storage as audit evidence.

The pivot from a generic "rich receipt extraction" tool happened in May 2026
(see `visit-pivot-plan.md`); price/VAT/fraud features were removed because
they were not part of the real workflow.

## Architecture

- **Backend** — FastAPI (Python 3.11+) at `backend/`
- **Frontend** — React 19 + Vite + Mantine v9 + Tailwind v4 at `frontend/`
- **AI** — Gemini 3 Flash (default) via OpenRouter using the OpenAI SDK,
  vision-only. Swap model via `OPENROUTER_MODEL`.
- **DB** — SQLite via SQLAlchemy + Alembic (head: `0026`)
- **Worker** — arq + Redis, opt-in via `USE_ARQ=true`; default falls back
  to FastAPI `BackgroundTasks` guarded by a `threading.Semaphore(1)`

## User flow

```text
/inbox  (landing)
  ├─ Upload N receipts in one go
  ├─ AI extracts → docs land in one of:
  │     • a Visit (store matched, period inferred)
  │     • Unknown-store section (admin picks/creates store)
  │     • Orphan section (merchant unreadable, admin names it)
  │     • Non-receipts (auto-purge in 7 days)
  └─ Visits-to-review section links into:

/stores                  list of admin-managed stores
  └─ /stores/:id         store detail: list of months (visits)
       └─ /visits/:id    visit: aggregate (product × qty) + docs panel
            └─ /visits/:vid/review/:docId
                         per-doc review: ImageCanvas left, items right
                         (autocomplete, ✓/? catalog match, approve, prev/next)
```

## Key commands

```bash
make dev           # backend :8000 + frontend :5173
make worker        # arq worker (requires Redis + USE_ARQ=true)
make test          # pytest in backend/tests (113 tests)
make typecheck     # tsc --noEmit on the frontend
make build         # frontend production build
make test-upload   # batch-upload dataTest/ to a running server
make db-upgrade    # alembic upgrade head
make docker-up     # docker compose
```

## AI pipeline

- Single OpenRouter vision call. The system instruction carries the live
  `PRODUCT_CATALOG` (built from active `products` rows) plus the JSON
  schema; the user prompt is a short task override.
- Retry with exponential backoff (3 attempts) inside `llm_client`.
- LLM emits only `product_name_raw` + `product_code`. The display name
  `product_name_normalized` is derived server-side from the code via
  `catalog.name_by_code`, falling back to raw when no code matches — so
  (code, name) can never desync.
- The pipeline extracts: `merchant_name/_normalized`, `document_number`,
  `document_date` (ค.ศ.), `category`, `items[]` with
  `product_name_raw`, `product_code`, `quantity`, `unit`.
  **Prices, VAT, discount, totals are not extracted** — they were removed
  from the schema, the prompt, and the DB.
- **Unit is catalog-driven, not model-driven.** The shop sells by
  ลัง/ถาด/แพ็ค (never a single ขวด), so for a catalog match the parser
  overrides the model's per-document `unit` guess with the SKU's selling
  unit via `catalog.selling_unit_by_code` (derived from `products.size`'s
  "จำนวน 1 …" clause, falling back to ลัง for beer/spirits). Quantity is
  left as written; off-catalog items keep the extracted unit. This keeps the
  visit aggregate from mixing ขวด with ลัง. Backfill old rows with
  `scripts/backfill_units.py`.

## Data model

- `documents` — id, file path/hash, status, raw extraction JSON,
  merchant_name/_normalized, document_number/_date, category, notes,
  confidence, needs_review, visit_id FK
- `document_items` — product_name_raw/_normalized, product_code, category,
  quantity, unit
- `visits` — store_id FK, store_key (normalized merchant), store_label,
  report_period (`YYYY-MM`), rep_name, last_reviewed_at
- `stores` — name, code (unique), normalized_name, address, active
- `products` — Boonrawd catalog + admin-added competitor SKUs;
  `manufacturer` distinguishes ours from competitor
- `product_aliases` — learned alias mappings from user corrections
  (merchant aliases exist but are no longer being learned — Store master
  is the source of truth for merchants)
- `catalog_gap_events`, `typo_recovery_events`, `document_events` — audit
  trail surfaces

## Extraction details

- System instruction (`services/extraction.py`) carries the Boonrawd
  PRODUCT_CATALOG markdown + the JSON schema. Top categories are 4:
  `เครื่องดื่ม`, `อาหาร และของว่าง`, `สินค้าพรีเมียมสิงห์`, `สินค้าอื่นๆ`.
  Legacy 8-category names are remapped on parse.
- **Merchant normalization** — extraction returns both `merchant_name`
  (raw) and `merchant_normalized` (canonical); `services/merchants` uses
  rapidfuzz to cluster similar raw names; the visit-creation path links a
  doc to an existing Store by `normalized_name`.
- **Visit auto-attach** — after extraction, `ensure_visit_for_doc` finds
  or creates a Visit for the doc's `(store_id, report_period)`. Mismatches
  (e.g., date outside the visit's month) are flagged on the doc itself
  via `check_period_mismatch` + `check_store_mismatch`.
- JSON response is defensively parsed (handles array-instead-of-object,
  nested item lists, invalid categories).

## Development notes

- Backend venv at `backend/.venv` — invoke as `.venv/bin/python` or
  `.venv/bin/uvicorn` / `.venv/bin/alembic`.
- Package management: `uv` for Python, `bun` for Node.
- Tests mock `_process_document` (not `extract_receipt`) because background
  tasks open their own DB session.
- Test DB uses in-memory SQLite with `StaticPool` for cross-connection
  state sharing.
- Config via `.env` in `backend/` — see `backend/.env.example`. Requires
  `OPENROUTER_API_KEY` (get one at <https://openrouter.ai/keys>).
- Frontend API base URL from `VITE_API_BASE` env var (defaults to
  `http://localhost:8000/api`).
- DB schema changes: add a file under `backend/alembic/versions/` and run
  `make db-upgrade`.
- SSE: `GET /api/visits/{id}/stream` and `GET /api/documents/{id}/events`
  publish per-doc status updates via the in-process `event_bus`.
- React Query: `frontend/src/api/queries.ts` defines query keys + hooks
  (`useVisit`, `useStores`, `useDocument`, …). Mutations invalidate
  `["documents"]`, `["visits"]`, `["trash"]`.

## File map (important)

```text
backend/app/services/extraction.py        # OpenRouter vision call + prompt
backend/app/services/llm_client.py        # OpenRouter (OpenAI SDK) wrapper
backend/app/services/visits.py              # ensure_visit_for_doc,
                                            # check_period_mismatch,
                                            # check_store_mismatch
backend/app/services/visit_aggregate.py     # product×qty rollup per visit
backend/app/services/merchants.py           # rapidfuzz normalization
backend/app/services/catalog.py             # DB-backed PRODUCT_CATALOG
backend/app/services/validation.py          # Thai post-extract warnings
backend/app/routers/documents.py            # upload, CRUD, items, approve
backend/app/routers/visits.py               # visit CRUD + bulk + stream
backend/app/routers/stores.py               # store master CRUD
backend/app/routers/inbox.py                # triage dashboard + actions
backend/app/models.py                       # all SQLAlchemy models

frontend/src/pages/InboxPage.tsx            # / and /inbox — landing
frontend/src/pages/StoresPage.tsx           # store master list
frontend/src/pages/StoreDetailPage.tsx      # one store, list of months
frontend/src/pages/VisitDetailPage.tsx      # one visit: aggregate + docs
frontend/src/pages/VisitReviewPage.tsx      # ImageCanvas + items editor
frontend/src/api/{client,queries}.ts        # fetch + React Query
frontend/src/components/Layout.tsx          # Mantine AppShell sidebar
frontend/src/theme.ts                       # indigo, IBM Plex Sans Thai
```

## Style conventions

- Backend: Python; no docstrings except on non-obvious functions; Thai
  for user-facing error messages, English for log strings.
- Frontend: TypeScript strict; functional components; Mantine v9 for
  components; Tailwind v4 for layout utilities; Thai for UI labels.
- Commit messages in English.
- Use `var(--mantine-color-default-border)` (not Tailwind `border-t`) for
  dividers so theme tokens stay consistent. The app is light-only — no
  `dark:` classes or `light-dark()` CSS.

## Things that used to exist but are gone

If a doc/comment references any of these, it's stale:

- **Dashboard** (`/api/dashboard/*`, `DashboardPage.tsx`) — removed; this
  pivot doesn't aggregate revenue.
- **Fraud detection** (`services/fraud.py`, `extraction_combined.py`,
  `fraud_flags` column) — removed.
- **Price fields** (`subtotal`, `discount`, `vat`, `grand_total`,
  `unit_price`, `line_total`) — dropped from DB, schema, and prompt.
- **`extraction_combined`** mode and `use_combined_extraction` setting —
  removed.
- **8-category taxonomy** (เบียร์/น้ำดื่ม/โซดา/…) — replaced with 4
  Singha-Online categories; legacy values auto-remap on parse.
- **CSV export** (`/api/dashboard/export`) — removed.
- **AI Health** (`/api/ai-health/*`, AIHealthPage) — removed.
- **Stepper visit creation** (`/visits/new`, `VisitNewPage.tsx`) —
  replaced by the Inbox + Store-detail "+ เพิ่มเดือน" flow.
- **Vertex AI / google-genai** (`get_gemini_client`, `_create_vertex_client`,
  `GCP_*` / `GEMINI_*` env vars, `LLM_PROVIDER`) — removed; all LLM calls
  now go through OpenRouter via the OpenAI SDK.
- **Agentic extraction** (`extraction_agentic.py`, `extraction_tools.py`,
  `EXTRACTION_MODE=agentic`, `lookup_catalog` tool) — removed; the default
  one-shot call is the only path.
- **`product_name_normalized` from LLM** — model now emits only
  `product_name_raw + product_code`; display name is derived server-side
  from `catalog.name_by_code(code)`.
- **Web Push notifications** (`routers/push.py`, `services/push.py`,
  `scripts/gen_vapid.py`, `hooks/useWebPush.ts`, `public/sw.js`,
  `push_subscriptions` table, `VAPID_*` env vars, `pywebpush` dep) — removed
  (migration `0026`). The toast feedback (`@mantine/notifications`) and the
  SSE live-progress streams are unrelated and stay.
- **Dark mode / color-scheme toggle** (Moon/Sun button, `useMantineColorScheme`,
  `dark:` Tailwind classes, `light-dark()` CSS) — removed; the app is
  light-only.
