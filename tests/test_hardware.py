import ast
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from whatcanmycomputerrun.api.app import create_app
from whatcanmycomputerrun.hardware.base import DeviceType, GpuKind, get_detector
from whatcanmycomputerrun.hardware.handhelds import match_handheld
from whatcanmycomputerrun.hardware.mock import MockDetector, available_profiles

REQUIRED = {"ally_z1e", "ally_x", "desktop_rtx3060", "laptop_igpu_lowend", "desktop_high_end"}


def test_all_required_profiles_present_and_valid():
    assert set(available_profiles()) >= REQUIRED
    for name in REQUIRED:
        hw = MockDetector(name).detect()
        assert hw.cpu and hw.gpus and hw.ram and hw.display
        assert hw.source == f"mock:{name}"


def test_ally_profile_is_handheld_with_shared_vram():
    hw = MockDetector("ally_z1e").detect()
    assert hw.device_type == DeviceType.HANDHELD
    gpu = hw.primary_gpu
    assert gpu and gpu.kind == GpuKind.INTEGRATED and gpu.vram_shared


def test_primary_gpu_prefers_discrete():
    hw = MockDetector("desktop_high_end").detect()
    assert len(hw.gpus) == 2
    assert hw.primary_gpu and "4090" in hw.primary_gpu.name


def test_unknown_profile_errors_helpfully():
    with pytest.raises(FileNotFoundError, match="Available"):
        MockDetector("nope").detect()


@pytest.mark.parametrize(
    ("man", "model", "expected"),
    [
        ("ASUSTeK COMPUTER INC.", "ROG Ally RC71L_RC71L", "ASUS ROG Ally"),
        ("ASUSTeK COMPUTER INC.", "ROG Ally X RC72LA_RC72LA", "ASUS ROG Ally X"),
        ("LENOVO", "83E1", "Lenovo Legion Go"),
        ("Micro-Star International Co., Ltd.", "Claw A1M", "MSI Claw"),
        ("ASUS", "System Product Name", None),
        (None, None, None),
    ],
)
def test_handheld_matching(man, model, expected):
    assert match_handheld(man, model) == expected


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows behaviour")
def test_real_detector_unavailable_off_windows():
    with pytest.raises(RuntimeError, match="mock-hardware"):
        get_detector(None)


def test_windows_module_not_imported_at_module_level():
    root = Path(__file__).parent.parent / "whatcanmycomputerrun"
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "windows.py":
            continue
        for node in ast.parse(path.read_text()).body:
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            if any(n.endswith("hardware.windows") or n in {"winreg", "wmi"} for n in names):
                offenders.append(str(path))
    assert not offenders


def test_api_hardware_and_rescan():
    client = TestClient(create_app(MockDetector("ally_z1e")))
    assert client.get("/api/health").json()["ok"] is True
    body = client.get("/api/hardware").json()
    assert body["device_type"] == "handheld"
    assert client.post("/api/hardware/rescan").status_code == 200
    assert "WhatCanMyComputerRun" in client.get("/").text


def test_api_reports_detection_failure_cleanly():
    class Boom:
        def detect(self):
            raise RuntimeError("kaboom")

    resp = TestClient(create_app(Boom())).get("/api/hardware")
    assert resp.status_code == 500 and "kaboom" in resp.json()["detail"]
