import json
import secrets
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AnyUrl, BeforeValidator, HttpUrl, PostgresDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_cors(value: Any) -> list[str] | str:
    if isinstance(value, str) and not value.startswith("["):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list | str):
        return value
    raise ValueError(value)


def parse_json_value(value: Any) -> Any:
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return {}
        return json.loads(normalized)
    return value


class Settings(BaseSettings):
    """Application settings loaded from `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "test-fast-api"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    FIRST_SUPERUSER_USERNAME: str | None = None
    FIRST_SUPERUSER_PASSWORD: str | None = None
    FIRST_SUPERUSER_EMAIL: str | None = None
    FRONTEND_HOST: str = "http://localhost:5173"
    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []
    SENTRY_DSN: HttpUrl | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]

    DATA_ROOT_DIR: str = "./data"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def TMP_UPLOAD_DIR(self) -> Path:
        """临时文件目录。"""
        return Path(self.DATA_ROOT_DIR) / "tmp"

    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5433
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres@pwd"
    POSTGRES_DB: str = "app"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6380
    REDIS_PASSWORD: str = "redis@pwd"
    REDIS_DB: int = 0
    REDIS_MAX_CONNECTIONS: int = 20
    REDIS_SOCKET_TIMEOUT: int = 30
    REDIS_SOCKET_CONNECT_TIMEOUT: int = 30
    REDIS_RETRY_ON_TIMEOUT: bool = True
    CACHE_DEFAULT_TTL: int = 604800
    LLM_API_BASE_URL: str = "http://127.0.0.1:1104/v1"
    LLM_API_KEY: str = "107815"
    LLM_CHAT_MODEL: str = "Qwen3.5-9B-MLX-4bit"
    LLM_CHAT_SESSION_TTL_SECONDS: int = 86400
    LLM_CHAT_MAX_HISTORY_MESSAGES: int = 20
    LLM_CHAT_MAX_UPLOAD_FILES: int = 20
    LLM_CHAT_MAX_UPLOAD_BYTES: int = 20 * 1024 * 1024
    LLM_CHAT_MAX_TEXT_FILE_BYTES: int = 512 * 1024

    @computed_field  # type: ignore[prop-decorator]
    @property
    def CELERY_BROKER_URL(self) -> str:
        """Celery broker URL backed by Redis."""
        return (
            f"redis://:{self.REDIS_PASSWORD}@"
            f"{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        )

    CELERY_BEAT_HEALTHCHECK_INTERVAL_SECONDS: float = 3600.0
    RUNTIME_EXTRA_ENV: Annotated[dict[str, str], BeforeValidator(parse_json_value)] = {}


settings = Settings()
