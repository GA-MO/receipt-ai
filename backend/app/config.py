from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AI
    gemini_api_key: str = ""
    gcp_credentials_path: str = ""
    gcp_project_id: str = ""
    gcp_location: str = "asia-southeast1"
    gemini_model: str = "gemini-3-flash-preview"

    # Database
    database_url: str = "sqlite:///./data/receipts.db"

    # Storage
    upload_dir: str = "./uploads"
    max_file_size_mb: int = 20

    # CORS
    cors_origins: str = "http://localhost:5173"

    # Logging
    log_level: str = "INFO"

    # Retry
    gemini_max_retries: int = 3
    gemini_retry_delay: float = 1.0

    model_config = {"env_file": ".env"}

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
