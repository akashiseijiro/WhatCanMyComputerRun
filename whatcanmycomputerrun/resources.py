import sys
from pathlib import Path


def resource_dir(name: str) -> Path:
    """Locate a package subfolder in dev and inside a PyInstaller bundle."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "whatcanmycomputerrun" / name
    return Path(__file__).parent / name
