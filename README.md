# Thai Receipt Intelligence

Visit-centric receipt processing for Boonrawd sales reps. Reps visit stores
each month, photograph the month's sales receipts (own and competitor SKUs),
and the system extracts **(product, quantity)** per receipt then rolls it up
into a `(store, month)` summary that audit can sample-check against the
original images.

## What it does

```text
Upload receipts ─▶ Gemini Vision ─▶ Inbox triage ─▶ Visit detail ─▶ Review
                                        │              │
                                  Auto-route to     Aggregate
                                  the right         (product × qty)
                                  Store+Month
```

- **Gemini Vision** extracts merchant, date, and line items (name + quantity,
  unit) — no prices, no VAT, no fraud signals.
- **Store master** is admin-managed; visits attach to a Store and a reporting
  month (`YYYY-MM`).
- **Inbox triage** routes uploads that the AI can't fully place: unknown
  store → admin assigns; merchant unreadable → admin names it; not a
  receipt → auto-purge after 7 days.
- **Doc-by-doc review** uses a side-by-side image + items editor with
  prev/next nav and a one-click "บันทึกว่าตรวจสอบแล้ว" approve.
- **Aggregate view** per visit shows product × qty rolled up across all
  receipts, with green ✓ / orange ? per row for catalog match.

## Quick start

```bash
make install           # backend (uv) + frontend (bun)
cp backend/.env.example backend/.env
# Edit backend/.env — set GEMINI_API_KEY or GCP_CREDENTIALS_PATH
make db-upgrade        # apply alembic migrations
make dev               # backend :8000 + frontend :5173
```

Open <http://localhost:5173>.

## Tech stack

| Layer    | Tech                                                       |
|----------|------------------------------------------------------------|
| Backend  | FastAPI · SQLAlchemy · Alembic · SQLite                    |
| Frontend | React 19 · Vite · Mantine v9 · Tailwind v4 · React Query   |
| AI       | Gemini 3 Flash via `google-genai` (Vertex AI)              |
| Worker   | arq + Redis (opt-in via `USE_ARQ=true`)                    |

## Make targets

```text
make dev              # backend + frontend concurrently
make worker           # arq worker (requires Redis)
make test             # pytest (113 tests)
make typecheck        # frontend tsc --noEmit
make build            # frontend production build
make test-upload      # batch-upload dataTest/ images
make db-upgrade       # apply alembic migrations
make docker-up        # docker compose stack
make help             # all targets
```

## Project layout

```text
backend/
├── app/
│   ├── main.py               # FastAPI app + router mounts
│   ├── models.py             # Document, DocumentItem, Visit, Store,
│   │                         # Product*, *Alias, *Event
│   ├── schemas.py            # Pydantic request/response models
│   ├── routers/
│   │   ├── documents.py      # upload, CRUD, items, approve, reextract
│   │   ├── visits.py         # visit CRUD + bulk upload + SSE stream
│   │   ├── stores.py         # store master CRUD
│   │   ├── inbox.py          # triage: dashboard, assign/create-store,
│   │   │                     # name orphan, purge non-receipts
│   │   ├── products.py       # catalog stats + lookup
│   │   ├── aliases.py        # learned product aliases
│   │   ├── autocomplete.py   # store + product autocomplete
│   │   └── push.py           # web push subscriptions
│   └── services/
│       ├── extraction.py     # default Gemini call (prompt + catalog)
│       ├── extraction_agentic.py  # tool-calling mode (opt-in)
│       ├── visits.py         # ensure_visit_for_doc, period/store check
│       ├── visit_aggregate.py  # (product × qty) rollup per visit
│       ├── merchants.py      # rapidfuzz normalization
│       ├── catalog.py        # DB-backed PRODUCT_CATALOG for the prompt
│       └── validation.py     # post-extract Thai-language warnings
├── alembic/versions/         # 24 migrations (head: 0024)
└── tests/                    # pytest (113 tests)

frontend/src/
├── pages/
│   ├── InboxPage.tsx         # /  and /inbox — landing page
│   ├── StoresPage.tsx        # store master list
│   ├── StoreDetailPage.tsx   # one store's monthly visits
│   ├── VisitsPage.tsx        # all visits (admin view)
│   ├── VisitDetailPage.tsx   # one visit: docs + aggregate
│   ├── VisitReviewPage.tsx   # /visits/:vid/review/:docId — image+items
│   ├── DocumentsPage.tsx     # all-docs admin list
│   └── TrashPage.tsx         # soft-deleted docs
├── api/{client,queries}.ts   # fetch wrappers + React Query hooks
├── components/Layout.tsx     # Mantine AppShell + sidebar
└── theme.ts                  # Mantine theme (indigo, IBM Plex Sans Thai)
```

## Key endpoints

| Method | Path                                          | Notes                             |
|--------|-----------------------------------------------|-----------------------------------|
| POST   | `/api/inbox`                                  | Upload one or many receipts       |
| GET    | `/api/inbox/dashboard`                        | Counts + items needing triage     |
| POST   | `/api/inbox/documents/{id}/assign-store`      | Attach orphan to existing store   |
| POST   | `/api/inbox/documents/{id}/create-store`      | Promote + attach to new store     |
| POST   | `/api/inbox/documents/{id}/name`              | Name a merchant-less doc          |
| GET    | `/api/stores`, `POST/PATCH/DELETE`            | Store master CRUD                 |
| GET    | `/api/visits`, `POST/PATCH/DELETE`            | Visit CRUD (idempotent per month) |
| POST   | `/api/visits/{id}/documents`                  | Bulk upload to a visit            |
| GET    | `/api/visits/{id}/stream`                     | SSE per-doc status updates        |
| GET    | `/api/documents/{id}/image`                   | Serve the original file           |
| PUT    | `/api/documents/{id}/items/{item_id}`         | Edit a line item                  |
| POST   | `/api/documents/{id}/approve`                 | Mark as reviewed                  |

Auto-generated FastAPI docs: <http://localhost:8000/docs>.

## Configuration (`backend/.env`)

| Variable                  | Description                                  | Default                          |
|---------------------------|----------------------------------------------|----------------------------------|
| `GEMINI_API_KEY`          | API key (option 1)                           | —                                |
| `GCP_CREDENTIALS_PATH`    | Service-account JSON (option 2)              | —                                |
| `GEMINI_MODEL`            | Vertex model id                              | `gemini-3-flash-preview`         |
| `EXTRACTION_MODE`         | `default` or `agentic`                       | `default`                        |
| `USE_ARQ`                 | Send processing to arq worker                | `false`                          |
| `REDIS_URL`               | Used when `USE_ARQ=true`                     | `redis://localhost:6379/0`       |
| `MAX_FILE_SIZE_MB`        | Upload size limit                            | `20`                             |
| `CORS_ORIGINS`            | Comma-separated origins                      | `http://localhost:5173`          |

## Testing

```bash
make test          # 113 pytest cases
make typecheck     # tsc --noEmit on the frontend
make test-upload   # end-to-end with sample receipts in dataTest/
```
