"""Manual hardware selection: a catalog of parts (2019 onwards) and a profile builder.

The catalog lives in catalog.json (plain data, easy to extend by hand). It is only used when
automatic detection fails or the user wants to try a different machine; it is not game data.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from whatcanmycomputerrun.hardware.base import (
    CpuInfo,
    DeviceType,
    DisplayInfo,
    DriveInfo,
    GpuInfo,
    GpuKind,
    GpuVendor,
    HardwareProfile,
    MediaType,
    OsInfo,
    RamInfo,
)
from whatcanmycomputerrun.hardware.handhelds import apply_handheld_assumptions

CATALOG_PATH = Path(__file__).parent / "catalog.json"


class CatalogError(ValueError):
    """A selection referred to something that isn't in the catalog."""


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return data


class ManualSelection(BaseModel):
    device_type: DeviceType
    handheld_id: str | None = None
    cpu_id: str
    gpu_id: str
    ram_gb: float = Field(ge=2, le=512)
    storage_free_gb: float = Field(ge=1, le=100_000)
    storage_type: MediaType = MediaType.SSD
    width: int = Field(ge=640, le=7680)
    height: int = Field(ge=360, le=4320)
    refresh_hz: int = Field(ge=24, le=540)
    windows: Literal["10", "11"] = "11"


def _find(items: list[dict[str, Any]], item_id: str, what: str) -> dict[str, Any]:
    for item in items:
        if item["id"] == item_id:
            return item
    raise CatalogError(f"Unknown {what}: {item_id}")


def build_manual_profile(sel: ManualSelection) -> HardwareProfile:
    cat = load_catalog()
    cpu = _find(cat["cpus"], sel.cpu_id, "CPU")
    gpu = _find(cat["gpus"], sel.gpu_id, "GPU")
    hand = _find(cat["handhelds"], sel.handheld_id, "handheld") if sel.handheld_id else None

    integrated = gpu["kind"] == "integrated"
    vram_mb = round(gpu["vram_gb"] * 1024)
    if hand and hand["gpu"] == gpu["id"] and hand.get("gpu_vram_mb"):
        vram_mb = int(hand["gpu_vram_mb"])  # the device's usual allocation

    build = "26100" if sel.windows == "11" else "19045"
    profile = HardwareProfile(
        cpu=CpuInfo(model=cpu["name"], cores=cpu["cores"], threads=cpu["threads"]),
        gpus=[
            GpuInfo(
                name=gpu["name"],
                vendor=GpuVendor(gpu["vendor"]),
                kind=GpuKind.INTEGRATED if integrated else GpuKind.DISCRETE,
                vram_mb=vram_mb,
                vram_shared=integrated,
                vram_source="manual",
            )
        ],
        ram=RamInfo(total_gb=sel.ram_gb, installed_gb=sel.ram_gb),
        storage=[
            DriveInfo(
                letter="C:",
                free_gb=sel.storage_free_gb,
                total_gb=None,
                media_type=sel.storage_type,
            )
        ],
        os=OsInfo(
            name=f"Microsoft Windows {sel.windows}",
            version=f"10.0.{build}",
            build=build,
            directx="DirectX 12",
        ),
        display=DisplayInfo(width=sel.width, height=sel.height, refresh_hz=sel.refresh_hz),
        device_type=DeviceType.HANDHELD if hand else sel.device_type,
        manufacturer=hand["manufacturer"] if hand else None,
        model=hand["model"] if hand else None,
        handheld_name=hand["handheld_name"] if hand else None,
        source="manual",
    )
    apply_handheld_assumptions(profile)
    return profile
