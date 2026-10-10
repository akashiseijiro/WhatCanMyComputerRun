from __future__ import annotations

from pathlib import Path

from canirunit.hardware.base import HardwareProfile

PROFILES_DIR = Path(__file__).parent / "profiles"


def available_profiles() -> list[str]:
    return sorted(p.stem for p in PROFILES_DIR.glob("*.json"))


class MockDetector:
    """Loads a HardwareProfile from a bundled JSON fixture (or a path to one)."""

    def __init__(self, profile: str) -> None:
        self.profile = profile

    def detect(self) -> HardwareProfile:
        path = Path(self.profile)
        if not path.suffix:
            path = PROFILES_DIR / f"{self.profile}.json"
        if not path.is_file():
            raise FileNotFoundError(
                f"Unknown mock hardware profile '{self.profile}'. "
                f"Available: {', '.join(available_profiles())}"
            )
        hw = HardwareProfile.model_validate_json(path.read_text(encoding="utf-8"))
        hw.source = f"mock:{path.stem}"
        return hw
