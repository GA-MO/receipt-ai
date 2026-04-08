# Thai Receipt Intelligence

AI-powered Thai receipt and sales document extraction system. Upload Thai receipts, invoices, or sales documents and get structured sales data automatically.

## Features

- **PaddleOCR + Gemini AI** — Hybrid pipeline: OCR reads text first, then Gemini extracts structured data with OCR context for higher accuracy
- **Thai-first design** — Handles Thai dates (พ.ศ.), Thai abbreviations, mixed Thai-English text
- **Human-in-the-loop** — Confidence scoring, validation warnings, side-by-side review
- **Dashboard** — Sales charts, top merchants, date range filtering, CSV export
- **Duplicate detection** — SHA-256 file hashing prevents re-uploading the same document
- **Background processing** — Upload returns immediately, AI processes in background with polling

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + SQLAlchemy + Alembic + SQLite |
| Frontend | React 19 + Vite 8 + Tailwind CSS 4 + TypeScript 6 |
| AI | Google Gemini 3 Flash (via `google-genai` SDK) — Vision-Language Model |
| Infrastructure | Docker Compose + GitHub Actions CI |

## Prerequisites

- Python 3.11+
- Node.js 20+
- Google Cloud credentials (service account key) or Gemini API key

## Quick Start

```bash
# Install everything
make install

# Configure
cp backend/.env.example backend/.env
# Edit backend/.env — set GEMINI_API_KEY or GCP_CREDENTIALS_PATH

# Run both servers
make dev
```

Open http://localhost:5173

## Available Commands

```
make dev              # Run backend + frontend dev servers
make test             # Run backend tests (33 tests)
make build            # Build frontend for production
make test-upload      # Upload test receipts from dataTest/
make db-upgrade       # Apply Alembic migrations
make docker-up        # Start with Docker Compose
make help             # Show all commands
```

## Project Structure

```
receipt-ai/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app + middleware
│   │   ├── config.py            # Settings (env-based)
│   │   ├── models.py            # SQLAlchemy models
│   │   ├── schemas.py           # Pydantic schemas
│   │   ├── database.py          # DB engine + session
│   │   ├── routers/
│   │   │   ├── documents.py     # Upload, CRUD, approve, re-extract
│   │   │   └── dashboard.py     # Stats, charts, CSV export
│   │   └── services/
│   │       ├── ocr.py           # PaddleOCR service
│   │       ├── extraction.py    # Gemini AI extraction
│   │       └── validation.py    # Business rule validation
│   ├── alembic/                 # Database migrations
│   ├── tests/                   # pytest (33 tests)
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/client.ts        # API client + types
│   │   ├── components/
│   │   │   ├── Layout.tsx       # Sidebar layout
│   │   │   └── Toast.tsx        # Toast notifications
│   │   └── pages/
│   │       ├── UploadPage.tsx   # Drag-drop upload
│   │       ├── DocumentsPage.tsx # List + search + filter
│   │       ├── ReviewPage.tsx   # Side-by-side review + edit
│   │       └── DashboardPage.tsx # Charts + stats + export
│   ├── Dockerfile
│   └── nginx.conf
├── docker-compose.yml
├── Makefile
└── scripts/test_upload.py       # Batch upload test script
```

## Processing Pipeline

```
Upload → [PaddleOCR] → OCR text → [Gemini + image + OCR context] → JSON
                                         ↓
                              Validation → Store → Review → Approve → Export
```

## API Documentation

FastAPI auto-generated docs: http://localhost:8000/docs

### Key Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/documents/upload` | Upload receipt |
| GET | `/api/documents` | List with search/filter/pagination |
| GET | `/api/documents/{id}` | Get document details |
| POST | `/api/documents/{id}/reextract` | Re-run OCR + AI |
| POST | `/api/documents/{id}/approve` | Approve document |
| GET | `/api/dashboard/stats` | Summary statistics |
| GET | `/api/dashboard/daily-sales` | Sales by date |
| GET | `/api/dashboard/top-merchants` | Top merchants |
| GET | `/api/dashboard/export` | CSV export (filterable) |

## Configuration

See `backend/.env.example` for all options:

| Variable | Description | Default |
|----------|-------------|---------|
| `GEMINI_API_KEY` | Gemini API key (option 1) | - |
| `GCP_CREDENTIALS_PATH` | GCP service account JSON (option 2) | - |
| `GEMINI_MODEL` | Gemini model | `gemini-3-flash-preview` |
| `OCR_ENABLED` | Enable PaddleOCR preprocessing (off by default) | `false` |
| `MAX_FILE_SIZE_MB` | Upload size limit | `20` |
| `CORS_ORIGINS` | Allowed origins (comma-separated) | `http://localhost:5173` |

## Docker

```bash
# Build and start
docker compose up --build -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

## Testing

```bash
# Unit + integration tests
make test

# Upload test receipts to running server
make test-upload
```
