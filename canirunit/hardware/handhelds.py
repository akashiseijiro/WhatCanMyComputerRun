"""Known handheld PCs. Extend HANDHELDS to add devices (manufacturer + model substring match).

Model codes come from Win32_ComputerSystem.Model / SystemSKU. Entries marked "verify" are
from public sources and have not been confirmed on real hardware.
"""

from __future__ import annotations

from dataclasses import dataclass


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
