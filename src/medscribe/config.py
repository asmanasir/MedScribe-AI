from __future__ import annotations

"""
Centralized configuration using pydantic-settings.

Why pydantic-settings?
- Validates config at startup (fail fast, not at 3am in prod)
- Type-safe: no more `os.getenv("PORT")` returning strings
- Supports .env files, env vars, and secrets
- Every setting is documented via type hints

All secrets come from environment variables — never hardcoded.
"""

from enum import Enum
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PRODUCTION = "production"


class LLMBackend(str, Enum):
    """Which LLM provider to use. Add new ones here as you implement them."""
    OPENAI = "openai"
    OLLAMA = "ollama"


class STTBackend(str, Enum):
    """Which STT provider to use."""
    OPENAI = "openai"      # Cloud — sends audio to OpenAI
    LOCAL = "local"        # Local — faster-whisper, nothing leaves your machine


class Settings(BaseSettings):
    """
    Application settings. Every field maps to an env var:
    e.g. `llm_backend` → `MEDSCRIBE_LLM_BACKEND`
    """

    model_config = SettingsConfigDict(
        env_prefix="MEDSCRIBE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Core ---
    environment: Environment = Environment.DEV
    debug: bool = False
    app_name: str = "MedScribe AI"
    api_version: str = "v1"

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///./medscribe.db"

    # --- Auth ---
    secret_key: SecretStr = Field(
        default=SecretStr("CHANGE-ME-IN-PRODUCTION"),
        description="JWT signing key. MUST override in staging/prod.",
    )
    access_token_expire_minutes: int = 60

    # --- LLM ---
    llm_backend: LLMBackend = LLMBackend.OPENAI
    openai_api_key: SecretStr = Field(default=SecretStr(""))
    openai_model: str = "gpt-4o"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    # --- STT (Speech-to-Text) ---
    stt_backend: STTBackend = STTBackend.LOCAL  # Default to LOCAL — data stays on device
    whisper_model: str = "base"  # tiny, base, small, medium, large
    whisper_device: str = "cpu"  # "cpu" or "cuda" (GPU acceleration)

    # --- Safety ---
    max_input_length: int = 50_000  # chars
    require_human_approval: bool = True  # MUST be true in prod

    # --- Privacy / GDPR ---
    auto_purge_hours: int = 24      # Auto-delete patient data after N hours
    store_audio_on_disk: bool = False  # NEVER store audio files — memory only
    allow_cloud_processing: bool = False  # Block cloud APIs by default (GDPR)

    # --- Integration ---
    webhook_url: str | None = None
    webhook_secret: SecretStr = Field(default=SecretStr(""))


@lru_cache
def get_settings() -> Settings:
    """
    Singleton settings instance. Cached so we parse env vars once.
    In tests, you can override this with dependency injection.
    """
    return Settings()
