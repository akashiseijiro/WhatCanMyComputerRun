from __future__ import annotations

import sys
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field, computed_field

from whatcanmycomputerrun.hardware.equivalents import Equivalents, lookup, memory_note


class DeviceType(StrEnum):
    DESKTOP = "desktop"
    LAPTOP = "laptop"
    HANDHELD = "handheld"


class GpuVendor(StrEnum):
    NVIDIA = "nvidia"
    AMD = "amd"
    INTEL = "intel"
    OTHER = "other"


class GpuKind(StrEnum):
    INTEGRATED = "integrated"
    DISCRETE = "discrete"


class MediaType(StrEnum):
    SSD = "ssd"
    HDD = "hdd"
    UNKNOWN = "unknown"


class CpuInfo(BaseModel):
    model: str
    cores: int | None = None
    threads: int | None = None
    base_clock_mhz: int | None = None
    boost_clock_mhz: int | None = None


class GpuInfo(BaseModel):
    name: str
    vendor: GpuVendor = GpuVendor.OTHER
    kind: GpuKind = GpuKind.DISCRETE
    vram_mb: int | None = None
    # True for iGPUs: "VRAM" is just a slice of system RAM, adjustable in BIOS/Armoury Crate.
    vram_shared: bool = False
    driver_version: str | None = None
    vram_source: str | None = None  # registry | dxgi | wmi | fixture | manual
    # Set when the app assumes a software-adjustable allocation (see handhelds.HANDHELD_VRAM).
    vram_assumed: bool = False
    vram_detected_mb: int | None = None


class RamInfo(BaseModel):
    total_gb: float | None = None
    # Physical RAM when known exactly (manual selection). Windows reports less on machines whose
    # iGPU reserves memory, so detected profiles leave this unset.
    installed_gb: float | None = None
    speed_mhz: int | None = None


class DriveInfo(BaseModel):
    letter: str
    free_gb: float | None = None
    total_gb: float | None = None
    media_type: MediaType = MediaType.UNKNOWN


class OsInfo(BaseModel):
    name: str | None = None
    version: str | None = None
    build: str | None = None
    directx: str | None = None


class DisplayInfo(BaseModel):
    width: int | None = None
    height: int | None = None
    refresh_hz: int | None = None


class HardwareProfile(BaseModel):
    cpu: CpuInfo | None = None
    gpus: list[GpuInfo] = Field(default_factory=list)
    ram: RamInfo | None = None
    storage: list[DriveInfo] = Field(default_factory=list)
    os: OsInfo | None = None
    display: DisplayInfo | None = None
    device_type: DeviceType = DeviceType.DESKTOP
    manufacturer: str | None = None
    model: str | None = None
    handheld_name: str | None = None
    warnings: list[str] = Field(default_factory=list)
    source: str = "detected"  # detected | mock:<name>

    @computed_field  # type: ignore[prop-decorator]
    @property
    def equivalents(self) -> Equivalents:
        """What the CPU/GPU roughly equal in desktop and laptop terms (display only)."""
        gpu = self.primary_gpu
        cpu_name = self.cpu.model if self.cpu else None
        memory = None
        if gpu and gpu.vram_shared and gpu.vram_mb and self.ram:
            ram = self.ram.installed_gb or (
                (self.ram.total_gb or 0) + (gpu.vram_detected_mb or gpu.vram_mb) / 1024
            )
            if self.device_type == DeviceType.HANDHELD and ram:
                memory = memory_note(ram, gpu.vram_mb / 1024)
        return Equivalents(
            cpu=lookup("cpu", cpu_name) if cpu_name else None,
            gpu=lookup("gpu", gpu.name, cpu_name) if gpu else None,
            memory=memory,
        )

    @property
    def primary_gpu(self) -> GpuInfo | None:
        """Most capable GPU for gaming: discrete beats integrated, then more VRAM."""
        if not self.gpus:
            return None
        return max(
            self.gpus,
            key=lambda g: (g.kind == GpuKind.DISCRETE, g.vram_mb or 0),
        )


class HardwareDetector(Protocol):
    def detect(self) -> HardwareProfile: ...


def get_detector(mock_profile: str | None = None) -> HardwareDetector:
    """Pick a detector. Windows-only code is imported lazily so macOS never loads it."""
    if mock_profile:
        from whatcanmycomputerrun.hardware.mock import MockDetector

        return MockDetector(mock_profile)
    if sys.platform == "win32":
        from whatcanmycomputerrun.hardware.windows import WindowsDetector

        return WindowsDetector()
    raise RuntimeError(
        "Real hardware detection only works on Windows. "
        "Use --mock-hardware <profile> (e.g. ally_z1e) on this platform."
    )
