"""Windows hardware detection. Imported lazily; never import this at module level elsewhere.

Milestone 1 placeholder: real detection (registry/DXGI/WMI) is milestone 2.
"""

from __future__ import annotations

from canirunit.hardware.base import HardwareProfile


class WindowsDetector:
    def detect(self) -> HardwareProfile:
        raise NotImplementedError("Windows detection is implemented in milestone 2.")
