from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Preset(StrEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    ULTRA = "Ultra"


class UpscaleMode(StrEnum):
    QUALITY = "Quality"
    BALANCED = "Balanced"
    PERFORMANCE = "Performance"


class UpscalerAdvice(BaseModel):
    technology: str  # DLSS | FSR | XeSS
    mode: UpscaleMode | None = None
    needed: bool = False
    note: str


class FrameGenAdvice(BaseModel):
    suggested: bool
    technology: str | None = None
    note: str
    latency_caveat: str


class FpsEstimate(BaseModel):
    low: int
    high: int
    label: str = "Rough estimate from relative hardware scores, not a benchmark."
    limited_by: Literal["GPU", "CPU"] = "GPU"


class HandheldAdvice(BaseModel):
    device: str
    power_mode: str
    watts: int
    fps_cap: int
    battery_fps_cap: int
    battery_note: str
    power_note: str | None = None


class GameTip(BaseModel):
    setting: str
    advice: str


class SettingsRecommendation(BaseModel):
    available: bool
    unavailable_reason: str | None = None
    playable: bool = True
    preset: Preset | None = None
    target_fps: int | None = None
    output_resolution: str | None = None
    render_resolution: str | None = None
    upscaler: UpscalerAdvice | None = None
    frame_generation: FrameGenAdvice | None = None
    fps: FpsEstimate | None = None
    handheld: HandheldAdvice | None = None
    vram_tip: str | None = None
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
