from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # OpenRouter (OpenAI-compatible) — single LLM gateway
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "google/gemini-3-flash-preview"
    openrouter_app_title: str = "Thai Receipt Intelligence"
    openrouter_app_url: str = ""

    # Database
    database_url: str = "sqlite:///./data/receipts.db"

    # Storage
    upload_dir: str = "./uploads"
    max_file_size_mb: int = 20

    # CORS
    cors_origins: str = "http://localhost:5173"

    # Logging
    log_level: str = "INFO"

    # LLM retry
    llm_max_retries: int = 3
    llm_retry_delay: float = 1.0
    llm_request_timeout: float = 60.0

    # Concurrent in-process extractions (FastAPI BackgroundTasks fallback).
    # arq mode uses ``WorkerSettings.max_jobs`` instead.
    extraction_concurrency: int = 4

    # Review thresholds
    review_confidence_threshold: float = 0.9

    # Merchant normalization
    merchant_fuzzy_threshold: int = 88  # 0-100; RapidFuzz token_set_ratio cutoff

    # Background worker (arq/Redis). If false, falls back to FastAPI BackgroundTasks.
    use_arq: bool = False
    redis_url: str = "redis://localhost:6379/0"

    # Web Push (VAPID)
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"

    # ``extra=ignore`` so a stale .env carrying retired keys (LLM_PROVIDER,
    # GEMINI_*, GCP_*, EXTRACTION_MODE) doesn't crash boot.
    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
