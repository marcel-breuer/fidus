from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RegistrationMode = Literal["open", "invite-only", "closed"]


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables only."""

    model_config = SettingsConfigDict(extra="ignore")

    # Application role: no superuser, not the table owner, no BYPASSRLS.
    database_url: str = "postgresql+asyncpg://fidus_app:change-me@db:5432/fidus"
    # Owner role: used only by the migrate service.
    database_owner_url: str = "postgresql+asyncpg://fidus:change-me@db:5432/fidus"
    app_db_user: str = "fidus_app"
    app_db_password: str = "change-me"

    redis_url: str = "redis://redis:6379/0"
    storage_path: str = "/data/files"

    secret_key: str = Field(default="change-me", min_length=8)
    app_url: str = "http://localhost:8080"
    cookie_secure: bool = False
    registration_mode: RegistrationMode = "open"
    session_lifetime_seconds: int = 60 * 60 * 24 * 14
    auth_rate_limit_attempts: int = Field(default=10, ge=1)
    auth_rate_limit_window_seconds: int = Field(default=60, ge=1)

    mcp_rate_limit_requests: int = Field(default=120, ge=1)
    mcp_rate_limit_window_seconds: int = Field(default=60, ge=1)

    openai_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
