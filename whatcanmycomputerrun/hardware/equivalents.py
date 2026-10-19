"""Plain-language "this part is roughly equal to..." references, mainly for handheld APUs.

Edit EQUIVALENTS to add parts. Keys are normalized component keys (see compare.normalize):
"gpu:<name>" / "cpu:<name>". basis="user" means the pairing was supplied by the project owner;
"estimate" means it is an approximate, from-memory comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from whatcanmycomputerrun.compare.normalize import (
    GENERIC_IGPU,
    igpu_from_cpu,
    normalize_cpu,
    normalize_gpu,
)


@dataclass(frozen=True)
class _Eq:
    desktop: str | None
    laptop: str | None
    basis: Literal["user", "estimate"] = "estimate"


EQUIVALENTS: dict[str, _Eq] = {
    # --- integrated GPUs ---
    "gpu:radeon 780m": _Eq("GeForce GTX 1650", "GeForce RTX 2050", "user"),  # Ally / Legion Go
    "gpu:radeon 890m": _Eq("GeForce GTX 1650 SUPER", "GeForce RTX 3050 (4 GB)"),
    "gpu:radeon 680m": _Eq("GeForce GTX 1050 Ti", "GeForce GTX 1650 Max-Q"),
    "gpu:radeon 760m": _Eq("GeForce GTX 1050", "GeForce MX450"),
    "gpu:intel iris xe graphics": _Eq("GeForce GT 1030", "GeForce MX350"),
    "gpu:intel arc graphics": _Eq("GeForce GTX 1650", "GeForce GTX 1650 Max-Q"),
    # --- CPUs ---
    "cpu:ryzen z1 extreme": _Eq("Ryzen 5 5600X (at higher power)", "Ryzen 7 7840U"),
    "cpu:ryzen z1": _Eq("Ryzen 5 3600", "Ryzen 5 7640U"),
    "cpu:core ultra 7 155h": _Eq("Core i5-12600K", "Core i7-13700H"),
}


class PartEquivalent(BaseModel):
    part: str
    desktop: str | None = None
    laptop: str | None = None
    basis: Literal["user", "estimate"] = "estimate"

    @property
    def summary(self) -> str:
        bits = [
            f"desktop {self.desktop}" if self.desktop else "",
            f"laptop {self.laptop}" if self.laptop else "",
        ]
        return " / ".join(b for b in bits if b)


class Equivalents(BaseModel):
    cpu: PartEquivalent | None = None
    gpu: PartEquivalent | None = None
    memory: str | None = None


def lookup(
    kind: Literal["cpu", "gpu"], name: str, cpu_hint: str | None = None
) -> PartEquivalent | None:
    norm = normalize_gpu(name) if kind == "gpu" else normalize_cpu(name)
    if kind == "gpu" and norm in GENERIC_IGPU:  # "AMD Radeon Graphics": identify via the CPU
        norm = igpu_from_cpu(norm, cpu_hint) or norm
    eq = EQUIVALENTS.get(f"{kind}:{norm}")
    if eq is None:
        return None
    return PartEquivalent(part=name, desktop=eq.desktop, laptop=eq.laptop, basis=eq.basis)


def memory_note(total_gb: float, graphics_gb: float) -> str:
    """Handhelds and other shared-memory machines: one pool split between RAM and graphics."""
    system = max(total_gb - graphics_gb, 0)
    return (
        f"One shared {total_gb:g} GB pool: with {graphics_gb:g} GB given to graphics it behaves "
        f"like a PC with about {system:g} GB of RAM plus a {graphics_gb:g} GB graphics card."
    )
