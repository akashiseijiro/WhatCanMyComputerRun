"""Known handheld PCs. Extend HANDHELDS to add devices (manufacturer + model substring match).

Model codes come from Win32_ComputerSystem.Model / SystemSKU. Entries marked "verify" are
from public sources and have not been confirmed on real hardware.
"""

from __future__ import annotations

from dataclasses import dataclass

from whatcanmycomputerrun.hardware.base import GpuKind, HardwareProfile


@dataclass(frozen=True)
class HandheldSpec:
    name: str
    manufacturer_contains: str
    model_contains: tuple[str, ...]


HANDHELDS: tuple[HandheldSpec, ...] = (
    # Order matters: more specific entries first.
    HandheldSpec("ASUS ROG Ally X", "asus", ("RC72LA",)),
    HandheldSpec("ASUS ROG Xbox Ally X", "asus", ("RC73XA",)),  # verify
    HandheldSpec("ASUS ROG Xbox Ally", "asus", ("RC73YA",)),  # verify
    HandheldSpec("ASUS ROG Ally", "asus", ("RC71L",)),
    HandheldSpec("Lenovo Legion Go S", "lenovo", ("83L3", "83N6", "Legion Go S")),  # verify
    HandheldSpec("Lenovo Legion Go", "lenovo", ("83E1", "Legion Go")),
    HandheldSpec("MSI Claw", "micro-star", ("Claw",)),
    HandheldSpec("MSI Claw", "msi", ("Claw",)),
)


def match_handheld(manufacturer: str | None, model: str | None) -> str | None:
    if not manufacturer or not model:
        return None
    man, mod = manufacturer.lower(), model.lower()
    for spec in HANDHELDS:
        if spec.manufacturer_contains in man and any(m.lower() in mod for m in spec.model_contains):
            return spec.name
    return None


@dataclass(frozen=True)
class PowerMode:
    name: str
    watts: int


@dataclass(frozen=True)
class HandheldPower:
    modes: tuple[PowerMode, ...]  # ordered lowest to highest power
    battery_wh: float


# Power modes per handheld, keyed by the names in HANDHELDS. Extend to add devices.
# Values are from public specs / memory and unverified on real hardware ("verify").
HANDHELD_POWER: dict[str, HandheldPower] = {
    "ASUS ROG Ally": HandheldPower(
        (PowerMode("Silent", 9), PowerMode("Performance", 15), PowerMode("Turbo", 25)), 40
    ),
    "ASUS ROG Ally X": HandheldPower(  # verify
        (PowerMode("Silent", 9), PowerMode("Performance", 17), PowerMode("Turbo", 25)), 80
    ),
    "Lenovo Legion Go": HandheldPower(  # verify
        (PowerMode("Quiet", 8), PowerMode("Balanced", 15), PowerMode("Performance", 20)), 49
    ),
    "MSI Claw": HandheldPower(  # verify
        (PowerMode("Battery saver", 15), PowerMode("Balanced", 20), PowerMode("Performance", 30)),
        53,
    ),
}
GENERIC_HANDHELD_POWER = HandheldPower(
    (PowerMode("Low power", 9), PowerMode("Balanced", 15), PowerMode("High power", 25)), 40
)


def power_profile(handheld_name: str | None) -> tuple[HandheldPower, bool]:
    """Return (power profile, known). Unknown devices get a generic 9/15/25 W profile."""
    if handheld_name and handheld_name in HANDHELD_POWER:
        return HANDHELD_POWER[handheld_name], True
    return GENERIC_HANDHELD_POWER, False


@dataclass(frozen=True)
class VramAssumption:
    assumed_mb: int  # what reports assume the iGPU memory allocation is set to
    max_mb: int  # the most the device allows


# iGPU memory on these handhelds is a software setting, so we assume it is raised.
HANDHELD_VRAM: dict[str, VramAssumption] = {
    "ASUS ROG Ally": VramAssumption(assumed_mb=6144, max_mb=8192),
}


def apply_handheld_assumptions(hw: HardwareProfile) -> None:
    """Raise the primary iGPU's memory to the assumed allocation, remembering the original."""
    gpu = hw.primary_gpu
    spec = HANDHELD_VRAM.get(hw.handheld_name or "")
    if gpu is None or spec is None or gpu.kind != GpuKind.INTEGRATED or gpu.vram_assumed:
        return
    if gpu.vram_mb is None or gpu.vram_mb < spec.assumed_mb:
        gpu.vram_detected_mb = gpu.vram_mb
        gpu.vram_mb = spec.assumed_mb
        gpu.vram_assumed = True
