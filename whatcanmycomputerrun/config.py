import importlib
import os
import sys
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


def embedded_gemini_key() -> str:
    """Key baked in by build/build.ps1 (git-ignored module, absent in dev; spec adds it)."""
    try:
        _embedded = importlib.import_module("whatcanmycomputerrun._embedded")
    except ImportError:
        return ""
    return str(getattr(_embedded, "GEMINI_API_KEY", "")).strip()


def app_data_dir() -> Path:
    """User-level data folder for the (deletable) HTTP/LLM response cache."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "WhatCanMyComputerRun"


def env_files() -> tuple[str, ...]:
    """Where .env may live. Later entries win: app-data folder < next to the .exe < current dir."""
    files = [app_data_dir() / ".env"]
    if getattr(sys, "frozen", False):  # PyInstaller build
        files.append(Path(sys.executable).parent / ".env")
    files.append(Path(".env"))
    return tuple(str(f) for f in files)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=env_files(), env_prefix="", extra="ignore")

    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    # "auto": Anthropic when its key is set, otherwise Gemini (own or build-time embedded key).
    whatcanmycomputerrun_llm_provider: Literal["auto", "anthropic", "gemini"] = "auto"
    whatcanmycomputerrun_gemini_model: str = "gemini-3.5-flash-lite"
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
    def gemini_key(self) -> str:
        """The user's own key wins over the one baked in at build time."""
        return self.gemini_api_key.strip() or embedded_gemini_key()

    @property
    def provider(self) -> Literal["anthropic", "gemini"]:
        choice = self.whatcanmycomputerrun_llm_provider
        if choice != "auto":
            return choice
        if self.has_api_key or not self.gemini_key:
            return "anthropic"
        return "gemini"

    @property
    def llm_available(self) -> bool:
        return bool(self.gemini_key) if self.provider == "gemini" else self.has_api_key

    def _model(self, claude_model: str) -> str:
        return self.whatcanmycomputerrun_gemini_model if self.provider == "gemini" else claude_model

    # Model per task, for whichever provider is active (also part of the cache keys).
    @property
    def parser_model(self) -> str:
        return self._model(self.whatcanmycomputerrun_parser_model)

    @property
    def resolver_model(self) -> str:
        return self._model(self.whatcanmycomputerrun_resolver_model)

    @property
    def search_model(self) -> str:
        return self._model(self.whatcanmycomputerrun_search_model)

    @property
    def tips_model(self) -> str:
        return self._model(self.whatcanmycomputerrun_tips_model)

    @property
    def cache_dir(self) -> Path:
        if self.whatcanmycomputerrun_cache_dir:
            return Path(self.whatcanmycomputerrun_cache_dir)
        return app_data_dir() / "cache"


def get_settings() -> Settings:
    return Settings()
