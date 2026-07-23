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

    # Auth - session/JWT signing key. Generate with:
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    session_secret_key: str
    access_token_expire_minutes: int = 60 * 24  # 24h

    # Auth - OTP (email verification / passwordless login)
    otp_expire_minutes: int = 10
    otp_length: int = 6
    otp_max_attempts: int = 5

    # Auth - email delivery. "console" (default) logs the OTP instead of
    # sending it - works with zero configuration. Switch to "smtp" once real
    # SMTP credentials are added below.
    email_provider: str = "console"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "noreply@sentinel.local"

    # Auth - OAuth (Google/Microsoft). Both optional: a provider's login
    # route returns a clear "not configured" error until its client
    # id/secret are set, rather than the app failing to start.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    microsoft_client_id: str | None = None
    microsoft_client_secret: str | None = None

    # Where OAuth callbacks redirect back to after issuing a session token.
    frontend_base_url: str = "http://localhost:5173"
    backend_base_url: str = "http://localhost:8000"

    # GitHub. The OAuth App is what a real user connects through; each person
    # authorizes their own account, so the token belongs to them rather than
    # to the workspace (the Phase A per-user connection model).
    github_client_id: str | None = None
    github_client_secret: str | None = None
    # Legacy single shared PAT. Kept only so an existing .env doesn't fail to
    # load; nothing reads it any more.
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
