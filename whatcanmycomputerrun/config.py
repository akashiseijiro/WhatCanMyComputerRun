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
    return base / "WhatCanMyComputerRun"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    anthropic_api_key: str = ""
    whatcanmycomputerrun_parser_model: str = "claude-haiku-4-5"
    whatcanmycomputerrun_resolver_model: str = "claude-haiku-4-5"
    whatcanmycomputerrun_search_model: str = "claude-sonnet-4-6"
    whatcanmycomputerrun_tips_model: str = "claude-haiku-4-5"
    whatcanmycomputerrun_cache_ttl_hours: float = 24.0
    whatcanmycomputerrun_cache_dir: str = ""

    @property
    def has_api_key(self) -> bool:
        return bool(self.anthropic_api_key.strip())

    @property
    def cache_dir(self) -> Path:
        if self.whatcanmycomputerrun_cache_dir:
            return Path(self.whatcanmycomputerrun_cache_dir)
        return app_data_dir() / "cache"


def get_settings() -> Settings:
    return Settings()
