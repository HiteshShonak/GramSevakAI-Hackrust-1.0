"""Pydantic BaseSettings — all env vars for GramSevak AI."""

import os
import tempfile
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Loads all config from .env file. Never hardcode secrets."""

    # WhatsApp (Meta Cloud API)
    WHATSAPP_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    VERIFY_TOKEN: str = "gramsevak_verify_2024"
    META_APP_SECRET: str = ""
    WHATSAPP_OTP_TEMPLATE_NAME: str = ""
    WHATSAPP_OTP_TEMPLATE_LANG: str = "en_US"
    WHATSAPP_OTP_TEMPLATE_PARAMS: str = "otp"

    # LLMs — active fallback chain: Sarvam → Groq
    SARVAM_API_KEY: str = ""
    SARVAM_API_KEYS: str = ""
    GROQ_API_KEY: str = ""
    GROQ_API_KEYS: str = ""

    # URL Verification APIs (Scam Detection) — graceful degradation if empty
    VIRUSTOTAL_API_KEY: str = ""
    VIRUSTOTAL_API_KEYS: str = ""     # Pool of keys for rotation (4 req/min per key)
    GOOGLE_SAFE_BROWSING_KEY: str = ""

    # Database
    MONGODB_URI: str = ""

    # Session + Cache
    SESSION_CACHE_DIR: str = Field(
        default_factory=lambda: str(Path(tempfile.gettempdir()) / "gramsevak_sessions")
    )
    MEMORY_BUDGET_MB: int = 300
    ENABLE_PHASE2_API: bool = False

    # JWT Auth (Phase 2)
    JWT_SECRET: str = ""
    JWT_EXPIRE_DAYS: int = 30

    # Environment
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "*"  # Comma-separated origins, or "*" for all (dev only)

    @field_validator("SESSION_CACHE_DIR", mode="before")
    @classmethod
    def normalize_session_cache_dir(cls, value: str | None) -> str:
        """Map Linux-style /tmp paths to the platform temp dir when needed."""
        if not value:
            return str(Path(tempfile.gettempdir()) / "gramsevak_sessions")

        if os.name == "nt" and str(value).startswith("/tmp"):
            return str(Path(tempfile.gettempdir()) / Path(str(value)).name)

        return str(value)

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }


settings = Settings()
