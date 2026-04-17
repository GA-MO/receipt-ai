# CLAUDE.md

## Project Overview

Thai Receipt Intelligence — AI-powered system that extracts structured data from Thai receipts, invoices, and sales documents. Built for SBP AI Hackathon 2026.

## Architecture

- **Backend:** FastAPI (Python 3.11+) at `backend/`
- **Frontend:** React + Vite + Tailwind CSS 4 + Mantine v9 at `frontend/`
- **AI Pipeline:** Google Gemini 3 Flash (via `google-genai` SDK) — vision-only extraction from images/PDFs
- **Database:** SQLite via SQLAlchemy + Alembic migrations
- **UI Theme:** Mantine theme in `src/theme.ts` (indigo primary, IBM Plex Sans Thai font, defaultRadius md) + dark mode via MantineProvider

## Key Commands

```bash
make dev           # Run backend (:8000) + frontend (:5173) concurrently
make test          # pytest (33 tests) — in backend/tests/
make build         # Frontend production build
make test-upload   # Upload dataTest/ receipts to running server
make db-upgrade    # Apply Alembic migrations
make docker-up     # Docker Compose
```

## AI Pipeline — Gemini Vision

- Documents are sent to **Gemini 3 Flash** as image or PDF bytes; the model returns structured JSON (merchant, line items, totals, VAT, category)
- **Extraction pipeline** is selectable via `EXTRACTION_MODE` (default `combined`):
  - `combined` (default) — single Gemini call returning extraction + self-contained fraud analysis; history-based fraud checks (duplicate, unusual amount) run in Python/SQL afterwards. ~15% faster and ~23% cheaper than legacy.
  - `legacy` — two serial Gemini calls (extract, then fraud). Original behaviour, kept as a safe fallback.
  - `agentic` — multi-turn tool-calling loop (`lookup_catalog`, `check_merchant_history`, `emit_extraction`, `emit_fraud_analysis`). Useful when the catalog grows large but currently slower and more expensive per doc.
- **Processing runs on an arq/Redis worker** (opt-in via `USE_ARQ=true`) or falls back to FastAPI `BackgroundTasks` with a `threading.Semaphore(1)` guard for local dev
- The catalog and schema live in Gemini's `system_instruction` (in legacy/combined) or as tool responses (in agentic), keeping per-request prompts lean

## Gemini Extraction

- System instruction carries the Boonrawd **PRODUCT_CATALOG** (alias → official name → category) and JSON schema; the user prompt only carries task-specific overrides
- **Category auto-classification** (document-level + per item): `เบียร์, น้ำดื่ม, โซดาและน้ำอัดลม, น้ำแร่, สุรา, เครื่องดื่มอื่นๆ, อาหาร, อื่นๆ`
  - `DocumentItem.category` mirrors the catalog category for each line-item (not just the document)
- **Merchant normalization** — extraction returns both `merchant_name` (raw) and `merchant_normalized` (canonical); `services/merchants.normalize_merchant` uses `rapidfuzz` to cluster similar raw names into the same canonical merchant, used in dashboards and fraud history
- **Non-receipt documents** (reports, slips): Gemini sets low confidence (0.3-0.6) and notes the document type
- JSON response is validated — handles array-instead-of-object and nested lists from Gemini edge cases
- Retry with exponential backoff (3 attempts)

## Development Notes

- Backend venv is at `backend/.venv` — use `.venv/bin/python` or `.venv/bin/uvicorn`
- Package management: `uv` for Python, `bun` for Node
- Tests mock `_process_document` (not `extract_receipt`) because background tasks create their own DB session
- Test DB uses in-memory SQLite with `StaticPool` (required for shared state across connections)
- Config via `.env` file in `backend/` — see `.env.example`
- GCP auth: service account key with `google.auth.default(scopes=["cloud-platform"])` + Vertex AI client
- Frontend API base URL from `VITE_API_BASE` env var (defaults to `http://localhost:8000/api`)
- DB schema changes: add migration under `backend/alembic/versions/` and run `make db-upgrade`
- **Worker**: `make worker` runs `arq app.worker.WorkerSettings` against Redis for durable background processing
- **React Query**: `frontend/src/api/queries.ts` defines query keys + hooks (`useDocument`, `useDocuments`, etc.); invalidate on mutation
- **SSE**: `GET /api/documents/{id}/events` streams status updates; frontend uses `EventSource` via `useDocumentStream` hook to avoid polling

## File Layout (important files)

```
backend/app/services/extraction.py  — Legacy Gemini Vision extraction (system_instruction + catalog, retry)
backend/app/services/extraction_combined.py — Default: 1-call extraction + fraud; Python post-check for history
backend/app/services/extraction_agentic.py — Tool-calling (lookup_catalog, check_merchant_history) multi-turn loop
backend/app/services/extraction_tools.py   — Tool implementations + Gemini FunctionDeclaration schemas
backend/app/services/merchants.py   — Merchant name normalization (rapidfuzz clustering)
backend/app/services/validation.py  — Business rule validation (totals, VAT, dates)
backend/app/services/storage.py     — File upload / hash / magic-byte validation
backend/app/worker.py               — arq worker: process_document task
backend/app/events.py               — In-process pub/sub for SSE status events
backend/app/routers/documents.py    — Upload, CRUD, re-extract, approve, search+filter, SSE stream
backend/app/routers/dashboard.py    — Stats, daily-sales, top-merchants, category breakdown, VAT summary, CSV export
backend/app/models.py               — Document (+ merchant_normalized, fraud_flags) + DocumentItem (+ category)
frontend/src/theme.ts               — Mantine theme (indigo primary, IBM Plex Sans Thai, component defaults)
frontend/src/index.css              — Tailwind v4 import + font config
frontend/src/api/client.ts          — Raw fetch wrappers + TypeScript types
frontend/src/api/queries.ts         — React Query hooks (useDocument, useDocuments, useDashboardStats, …)
frontend/src/hooks/useDocumentStream.ts — SSE EventSource hook for live document status
frontend/src/components/Layout.tsx   — Mantine AppShell (sidebar, dark mode toggle, mobile burger)
frontend/src/components/Toast.tsx    — Thin wrapper around @mantine/notifications (useToast API)
frontend/src/pages/ReviewPage.tsx   — Side-by-side review, category select, auto-calculate
frontend/src/pages/DocumentsPage.tsx — Search, status+category filter, date range, pagination
frontend/src/pages/DashboardPage.tsx — Stats, charts, category breakdown, VAT summary, fraud detection
frontend/src/pages/CapturePage.tsx  — Mobile camera capture
```

## Style Conventions

- Backend: Python, no docstrings except on complex functions, Thai error messages for user-facing errors, English for logs
- Frontend: TypeScript strict, functional components, Mantine v9 components + Tailwind CSS 4 for layout utilities
- Thai language used in UI labels, validation messages, and prompts
- Commit messages in English
