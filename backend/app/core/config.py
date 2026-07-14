from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Core
    environment: str = "development"
    log_level: str = "INFO"
    log_json: bool = True

    # Database
    database_url: str = "mysql+pymysql://sentinel:sentinel@localhost:3306/sentinel"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Secrets
    # Fernet key used to encrypt connection tokens at rest. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: str

    # GitHub
    github_default_token: str | None = None

    # LLM (Groq)
    groq_api_key: str
    groq_model: str = "openai/gpt-oss-120b"

    # Scheduling
    ingestion_poll_interval_seconds: int = 6 * 60 * 60

    # Findings
    min_finding_confidence: float = 0.55


@lru_cache
def get_settings() -> Settings:
    return Settings()
