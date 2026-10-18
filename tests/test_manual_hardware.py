import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from test_engine import FIX, SCORES

from canirunit.api.app import create_app
from canirunit.compare.engine import build_report
from canirunit.compare.models import Verdict
from canirunit.compare.normalize import normalize_cpu, normalize_gpu
from canirunit.compare.resolver import StaticResolver
from canirunit.config import Settings
from canirunit.hardware.base import DeviceType, GpuInfo, GpuKind, HardwareProfile, MediaType
from canirunit.hardware.catalog import (
    CatalogError,
    ManualSelection,
    build_manual_profile,
    load_catalog,
)
from canirunit.hardware.handhelds import HANDHELD_VRAM, apply_handheld_assumptions
from canirunit.hardware.mock import MockDetector
from canirunit.sources.steam import DETAILS_URL

CAT = load_catalog()


def sel(**kw):
    base = dict(
        device_type="desktop",
        cpu_id="cpu-amd-ryzen-5-5600x",
        gpu_id="gpu-nvidia-geforce-rtx-3060-12gb",
        ram_gb=16,
        storage_free_gb=300,
        storage_type="ssd",
        width=2560,
        height=1440,
        refresh_hz=144,
    )
    base.update(kw)
    return ManualSelection(**base)


def test_catalog_integrity():
    ids = [x["id"] for x in CAT["cpus"] + CAT["gpus"] + CAT["handhelds"]]
    assert len(ids) == len(set(ids))
    assert len(CAT["cpus"]) > 100 and len(CAT["gpus"]) > 100
    assert all(x["year"] >= 2019 for x in CAT["cpus"] + CAT["gpus"])  # the 2019+ rule
    cpu_ids = {c["id"] for c in CAT["cpus"]}
    gpu_ids = {g["id"] for g in CAT["gpus"]}
    for h in CAT["handhelds"]:
        assert h["cpu"] in cpu_ids and h["gpu"] in gpu_ids
    for c in CAT["cpus"]:
        assert c["cores"] <= c["threads"] <= 2 * c["cores"] and normalize_cpu(c["name"])
    for g in CAT["gpus"]:
        assert g["vram_gb"] > 0 and normalize_gpu(g["name"])
        assert (g["kind"] == "integrated") == (g["segment"] == "integrated")


def test_laptop_and_desktop_gpus_stay_distinct():
    # same marketing number, different (slower) part: must not share a score-cache key
    assert normalize_gpu("NVIDIA GeForce RTX 4060 Laptop GPU") != normalize_gpu(
        "NVIDIA GeForce RTX 4060"
    )
    assert normalize_gpu("AMD Radeon RX 6800M") == "radeon rx 6800m"


def test_build_desktop_profile():
    hw = build_manual_profile(sel())
    assert hw.source == "manual" and hw.device_type == DeviceType.DESKTOP
    gpu = hw.primary_gpu
    assert gpu.name == "NVIDIA GeForce RTX 3060" and gpu.vram_mb == 12288 and not gpu.vram_shared
    assert hw.cpu.cores == 6 and hw.ram.installed_gb == 16
    assert hw.storage[0].media_type == MediaType.SSD and hw.os.build == "26100"
    assert hw.display.refresh_hz == 144


def test_build_windows_10_and_laptop_igpu():
    hw = build_manual_profile(
        sel(device_type="laptop", gpu_id="gpu-intel-iris-xe-graphics", windows="10", ram_gb=8)
    )
    gpu = hw.primary_gpu
    assert gpu.kind == GpuKind.INTEGRATED and gpu.vram_shared and hw.os.build == "19045"
    assert hw.device_type == DeviceType.LAPTOP and hw.handheld_name is None


def test_handheld_preset_sets_device_and_assumes_vram():
    hw = build_manual_profile(
        sel(
            device_type="desktop",
            handheld_id="handheld-rog-ally",
            cpu_id="cpu-amd-ryzen-z1-extreme",
            gpu_id="gpu-amd-radeon-780m",
            ram_gb=16,
            width=1920,
            height=1080,
            refresh_hz=120,
        )
    )
    assert hw.device_type == DeviceType.HANDHELD and hw.handheld_name == "ASUS ROG Ally"
    gpu = hw.primary_gpu
    assert gpu.vram_mb == 6144 and gpu.vram_assumed and gpu.vram_detected_mb == 4096
    assert gpu.vram_source == "manual"  # so notes say "usually 4 GB", not "detected"


def test_unknown_ids_rejected():
    with pytest.raises(CatalogError):
        build_manual_profile(sel(gpu_id="gpu-nope"))
    with pytest.raises(CatalogError):
        build_manual_profile(sel(handheld_id="handheld-nope"))


def test_ally_assumes_six_gb_but_other_devices_untouched():
    hw = MockDetector("ally_z1e").detect()  # fixture reports a 4 GB allocation
    gpu = hw.primary_gpu
    assert gpu.vram_mb == HANDHELD_VRAM["ASUS ROG Ally"].assumed_mb == 6144
    assert gpu.vram_assumed and gpu.vram_detected_mb == 4096
    apply_handheld_assumptions(hw)  # idempotent
    assert gpu.vram_mb == 6144 and gpu.vram_detected_mb == 4096
    ally_x = MockDetector("ally_x").detect().primary_gpu
    assert ally_x.vram_mb == 8192 and not ally_x.vram_assumed
    desktop = MockDetector("desktop_rtx3060").detect().primary_gpu
    assert not desktop.vram_assumed


def test_assumption_never_lowers_a_larger_allocation_or_touches_discrete():
    hw = HardwareProfile(
        handheld_name="ASUS ROG Ally",
        gpus=[
            GpuInfo(
                name="AMD Radeon Graphics", kind=GpuKind.INTEGRATED, vram_mb=8192, vram_shared=True
            )
        ],
    )
    apply_handheld_assumptions(hw)
    assert hw.gpus[0].vram_mb == 8192 and not hw.gpus[0].vram_assumed


async def test_ram_addback_uses_detected_reserve_not_assumed():
    from canirunit.compare.engine import _effective_ram

    hw = MockDetector("ally_z1e").detect()  # 16 GB reported, 4 GB reserved (detected)
    total, note = _effective_ram(hw)
    assert total == 20 and "4 GB is reserved" in note  # not 16 + 6
    manual = build_manual_profile(
        sel(
            handheld_id="handheld-rog-ally",
            cpu_id="cpu-amd-ryzen-z1-extreme",
            gpu_id="gpu-amd-radeon-780m",
            ram_gb=16,
        )
    )
    assert _effective_ram(manual)[0] == 16  # manual RAM is the physical total: no add-back


async def test_ally_vram_row_and_tip_reflect_assumption():
    from test_engine import cyberpunk

    from canirunit.settings.rules import recommend_settings

    hw = MockDetector("ally_z1e").detect()
    rep = await build_report(hw, cyberpunk(), StaticResolver(SCORES))
    vram = next(r for r in rep.rows if r.key == "vram")
    assert vram.verdict == Verdict.MEETS_MIN and "assumed" in vram.yours
    assert "currently 4 GB" in vram.note and "Armoury Crate" in vram.note
    tip = recommend_settings(hw, rep).vram_tip
    assert "assume 6 GB" in tip and "up to 8 GB" in tip and "currently 4 GB" in tip


@respx.mock
def test_manual_endpoints_and_report(tmp_path):
    data = json.loads((FIX / "appdetails_1091500.json").read_text())
    respx.get(DETAILS_URL).mock(return_value=httpx.Response(200, json=data))
    st = Settings(anthropic_api_key="", canirunit_cache_dir=str(tmp_path))
    app = create_app(MockDetector("ally_z1e"), st, resolver=StaticResolver(SCORES))
    body = sel().model_dump(mode="json")
    with TestClient(app) as client:
        cat = client.get("/api/hardware/catalog").json()
        assert cat["cpus"] and cat["gpus"] and cat["handhelds"] and cat["ram_options_gb"]
        r = client.post("/api/hardware/manual", json=body)
        assert r.status_code == 200 and r.json()["source"] == "manual"
        assert client.get("/api/hardware").json()["source"] == "manual"  # sticks until re-scan
        rep = client.get("/api/report/1091500").json()
        assert rep["rows"][0]["yours"].startswith("NVIDIA GeForce RTX 3060")
        assert (
            client.post("/api/hardware/manual", json={**body, "gpu_id": "gpu-nope"}).status_code
            == 400
        )
        assert client.post("/api/hardware/manual", json={**body, "ram_gb": 0}).status_code == 422
        back = client.post("/api/hardware/rescan").json()
        assert back["source"] == "mock:ally_z1e"  # re-scan returns to automatic detection
