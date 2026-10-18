"""Runs only on a real Windows machine (CI windows-latest, your PC, the Ally)."""

import json
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_real_detection_smoke():
    from whatcanmycomputerrun.hardware.windows import WindowsDetector

    det = WindowsDetector()
    hw = det.detect()
    print(json.dumps({"profile": hw.model_dump(mode="json"), "raw": det.last_raw}, indent=1))
    assert hw.cpu and hw.cpu.model
    assert hw.ram and hw.ram.total_gb and hw.ram.total_gb > 0
    assert hw.os and hw.os.build
    assert hw.gpus, f"no GPU found; warnings={hw.warnings}"
    assert hw.storage
    assert hw.primary_gpu
    HardwareProfile = type(hw)
    assert HardwareProfile.model_validate_json(hw.model_dump_json()) == hw


def test_collectors_do_not_raise():
    from whatcanmycomputerrun.hardware.windows import read_dxgi_adapters, read_registry_gpus

    assert isinstance(read_registry_gpus(), list)
    assert isinstance(read_dxgi_adapters(), list)
