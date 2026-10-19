import json
from pathlib import Path

import pytest

from whatcanmycomputerrun.hardware.base import DeviceType, GpuKind, MediaType
from whatcanmycomputerrun.hardware.windows_parse import (
    build_profile,
    classify_gpu_kind,
    detect_device_type,
    gpu_vendor,
)

FIX = Path(__file__).parent / "fixtures" / "windows_raw"


def load(name):
    d = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    return build_profile(d["wmi"], d["registry"], d["dxgi"])


def test_ally_is_handheld_with_shared_vram():
    hw = load("ally")
    assert hw.device_type == DeviceType.HANDHELD and hw.handheld_name == "ASUS ROG Ally"
    gpu = hw.primary_gpu
    assert gpu and gpu.kind == GpuKind.INTEGRATED and gpu.vram_shared
    assert gpu.vram_mb == 4096 and gpu.vram_source == "registry"  # not the 512 MB WMI value
    assert hw.cpu and hw.cpu.threads == 16
    assert hw.ram and hw.ram.speed_mhz == 6400
    assert hw.storage[0].media_type == MediaType.SSD
    assert hw.display and (hw.display.width, hw.display.refresh_hz) == (1920, 120)
    assert hw.os and hw.os.directx == "DirectX 12"
    assert not hw.warnings


def test_registry_beats_wmi_4gb_cap_and_picks_dgpu():
    hw = load("desktop_dual_gpu")
    assert hw.device_type == DeviceType.DESKTOP
    assert len(hw.gpus) == 2
    rtx = hw.primary_gpu
    assert rtx and "RTX 3060" in rtx.name and rtx.vram_mb == 12288 and not rtx.vram_shared
    assert rtx.vram_source == "registry"
    assert hw.cpu and hw.cpu.model == "AMD Ryzen 5 5600X 6-Core Processor"
    assert [d.media_type for d in hw.storage] == [MediaType.SSD, MediaType.HDD]
    assert hw.display and hw.display.refresh_hz == 144  # taken from the GPU that drives the screen


def test_ci_vm_degrades_gracefully():
    hw = load("ci_vm")
    assert hw.gpus and hw.gpus[0].name == "Microsoft Hyper-V Video"
    assert any("no physical GPU" in w for w in hw.warnings)
    assert hw.ram and hw.ram.total_gb == 16.0
    assert hw.storage[0].media_type == MediaType.UNKNOWN


def test_dxgi_used_when_registry_missing():
    d = json.loads((FIX / "ally.json").read_text(encoding="utf-8"))
    hw = build_profile(d["wmi"], [], d["dxgi"])
    assert hw.gpus[0].vram_mb == 4096 and hw.gpus[0].vram_source == "dxgi"


def test_wmi_fallback_warns_when_capped():
    d = json.loads((FIX / "desktop_dual_gpu.json").read_text(encoding="utf-8"))
    hw = build_profile(d["wmi"], [], [])
    rtx = next(g for g in hw.gpus if "RTX" in g.name)
    assert rtx.vram_source == "wmi" and rtx.vram_mb == 4095
    assert any("4 GB or more" in w for w in hw.warnings)


def test_empty_input_never_crashes():
    hw = build_profile({})
    assert hw.cpu is None and hw.gpus == [] and hw.ram is None and hw.os is None
    assert len(hw.warnings) >= 5


def test_garbage_sections_do_not_crash():
    hw = build_profile({"cpu": "oops", "gpu": [1, None], "os": [], "computer_system": 5})
    assert hw.cpu is None and hw.gpus == []


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("NVIDIA GeForce RTX 4090", GpuKind.DISCRETE),
        ("AMD Radeon RX 7800 XT", GpuKind.DISCRETE),
        ("AMD Radeon RX 6800M", GpuKind.DISCRETE),
        ("AMD Radeon(TM) Graphics", GpuKind.INTEGRATED),
        ("AMD Radeon 780M", GpuKind.INTEGRATED),
        ("AMD Radeon(TM) Vega 8 Graphics", GpuKind.INTEGRATED),
        ("Intel(R) UHD Graphics", GpuKind.INTEGRATED),
        ("Intel(R) Iris(R) Xe Graphics", GpuKind.INTEGRATED),
        ("Intel(R) Arc(TM) Graphics", GpuKind.INTEGRATED),
        ("Intel(R) Arc(TM) A770 Graphics", GpuKind.DISCRETE),
    ],
)
def test_gpu_kind(name, kind):
    assert classify_gpu_kind(name, gpu_vendor(name)) == kind


@pytest.mark.parametrize(
    ("man", "model", "chassis", "pcst", "battery", "expected"),
    [
        ("LENOVO", "83E1", [10], 2, True, DeviceType.HANDHELD),
        ("Dell Inc.", "XPS 15", [10], 2, True, DeviceType.LAPTOP),
        ("Dell Inc.", "XPS 15", [], None, True, DeviceType.LAPTOP),
        ("ASUS", "Desktop", [3], 1, False, DeviceType.DESKTOP),
        (None, None, [], None, False, DeviceType.DESKTOP),
    ],
)
def test_device_type(man, model, chassis, pcst, battery, expected):
    assert detect_device_type(man, model, chassis, pcst, battery)[0] == expected
