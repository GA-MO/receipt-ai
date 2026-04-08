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
- **Processing is serialized** via `threading.Semaphore(1)` in `_process_document` to bound memory and API concurrency
- Large images may be resized before upload to the model to stay within limits (see implementation in `documents` processing)

## Gemini Extraction

- Prompt instructs Gemini to extract structured JSON with merchant, items, totals, VAT, category
- **Category auto-classification**: 8 categories (อาหาร, วัตถุดิบ, สำนักงาน, เดินทาง, สาธารณูปโภค, การตลาด, บริการ, อื่นๆ)
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
- DB schema changes: add column via `ALTER TABLE` for SQLite (create_all doesn't add to existing tables)

## File Layout (important files)

```
backend/app/services/extraction.py  — Gemini Vision extraction (category, fraud-aware prompt, retry)
backend/app/services/validation.py  — Business rule validation (totals, VAT, dates)
backend/app/routers/documents.py    — Upload, CRUD, re-extract, approve, search+filter, semaphore queue
backend/app/routers/dashboard.py    — Stats, daily-sales, top-merchants, category breakdown, VAT summary, CSV export
backend/app/models.py               — Document (category, fraud_flags) + DocumentItem
frontend/src/theme.ts               — Mantine theme (indigo primary, IBM Plex Sans Thai, component defaults)
frontend/src/index.css              — Tailwind v4 import + font config
frontend/src/api/client.ts          — All API functions + TypeScript types
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
