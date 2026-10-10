import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def app_data_dir() -> Path:
    """User-level data folder for the (deletable) HTTP/LLM response cache."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "CanIRunIt"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    anthropic_api_key: str = ""
    canirunit_parser_model: str = "claude-haiku-4-5-20251001"
    canirunit_resolver_model: str = "claude-haiku-4-5-20251001"
    canirunit_search_model: str = "claude-sonnet-4-6"
    canirunit_cache_ttl_hours: float = 24.0

    @property
    def has_api_key(self) -> bool:
        return bool(self.anthropic_api_key.strip())

    @property
    def cache_dir(self) -> Path:
        return app_data_dir() / "cache"


def get_settings() -> Settings:
    return Settings()
