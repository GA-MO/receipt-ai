.PHONY: dev dev-backend dev-frontend stop install install-backend install-frontend test build clean db-migrate db-upgrade docker-up docker-down

# ── Dev servers ──────────────────────────────────────────────

dev: ## Run backend + frontend dev servers concurrently
	@echo "Starting backend on :8000 and frontend on :5173..."
	@make -j2 dev-backend dev-frontend

dev-backend: ## Run backend dev server
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

dev-frontend: ## Run frontend dev server
	cd frontend && bun dev

worker: ## Run arq worker (requires Redis + USE_ARQ=true)
	cd backend && .venv/bin/arq app.worker.WorkerSettings

redis: ## Run a local Redis via Docker for the worker
	docker run -d --name receipt-redis -p 6379:6379 redis:7-alpine || docker start receipt-redis

stop: ## Stop dev servers (kill processes on :8000 and :5173)
	@echo "Stopping dev servers..."
	@lsof -ti :8000 | xargs kill -9 2>/dev/null || true
	@lsof -ti :5173 | xargs kill -9 2>/dev/null || true
	@lsof -ti :5174 | xargs kill -9 2>/dev/null || true
	@echo "Done"

# ── Install ──────────────────────────────────────────────────

install: install-backend install-frontend ## Install all dependencies

install-backend: ## Install backend dependencies
	cd backend && uv venv .venv && uv pip install --python .venv/bin/python -r pyproject.toml

install-frontend: ## Install frontend dependencies
	cd frontend && bun install

# ── Test ─────────────────────────────────────────────────────

test: ## Run backend tests
	cd backend && .venv/bin/python -m pytest tests/ -v

test-watch: ## Run backend tests in watch mode
	cd backend && .venv/bin/python -m pytest tests/ -v --tb=short -x

test-upload: ## Upload test receipts from dataTest/ to running server
	cd backend && .venv/bin/python ../scripts/test_upload.py

# ── Build ────────────────────────────────────────────────────

build: ## Build frontend for production
	cd frontend && bun run build

typecheck: ## TypeScript type check
	cd frontend && npx tsc --noEmit

# ── Database ─────────────────────────────────────────────────

db-migrate: ## Create a new Alembic migration (usage: make db-migrate msg="add xyz")
	cd backend && .venv/bin/alembic revision --autogenerate -m "$(msg)"

db-upgrade: ## Apply all pending migrations
	cd backend && .venv/bin/alembic upgrade head

db-downgrade: ## Rollback one migration
	cd backend && .venv/bin/alembic downgrade -1

# ── Docker ───────────────────────────────────────────────────

docker-up: ## Start services with docker-compose
	docker compose up --build -d

docker-down: ## Stop docker-compose services
	docker compose down

docker-logs: ## Tail docker-compose logs
	docker compose logs -f

# ── Cleanup ──────────────────────────────────────────────────

clean: ## Remove build artifacts and caches
	rm -rf frontend/dist
	rm -rf backend/__pycache__ backend/**/__pycache__
	rm -rf backend/.pytest_cache
	find backend -name "*.pyc" -delete

# ── Help ─────────────────────────────────────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
