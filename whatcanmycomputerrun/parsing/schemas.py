from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Requirements(BaseModel):
    """One requirement tier (minimum or recommended). Alternatives are all kept."""

    cpu: list[str] = Field(default_factory=list)
    gpu: list[str] = Field(default_factory=list)
    ram_gb: float | None = None
    vram_gb: float | None = None
    storage_gb: float | None = None
    os: str | None = None
    directx: str | None = None
    notes: str | None = None


class RequirementsSet(BaseModel):
    minimum: Requirements | None = None
    recommended: Requirements | None = None
    source: Literal["steam", "web_search"] = "steam"
    parse_method: Literal["deterministic", "llm", "mixed"] = "deterministic"
    source_urls: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Price(BaseModel):
    currency: str
    initial_cents: int
    final_cents: int
    discount_percent: int = 0
    formatted: str | None = None


class SearchResult(BaseModel):
    appid: int
    name: str
    image: str | None = None
    price: str | None = None


class GameDetails(BaseModel):
    appid: int
    name: str
    type: str = "game"
    header_image: str | None = None
    store_url: str
    is_free: bool = False
    price: Price | None = None
    release_date: str | None = None
    coming_soon: bool = False
    windows_supported: bool = True
    requirements: RequirementsSet | None = None
    requirements_status: Literal["ok", "missing"] = "ok"


class LLMParsedRequirements(BaseModel):
    """Strict schema the LLM must fill when the deterministic parser leaves gaps."""

    minimum: Requirements | None = None
    recommended: Requirements | None = None
