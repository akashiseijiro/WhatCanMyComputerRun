import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from canirunit.api.app import create_app
from canirunit.compare.engine import build_report, tier_verdict
from canirunit.compare.models import Confidence, Recommendation, Verdict
from canirunit.compare.resolver import StaticResolver
from canirunit.config import Settings
from canirunit.hardware.mock import MockDetector
from canirunit.parsing.requirements_parser import parse_pc_requirements
from canirunit.parsing.schemas import GameDetails, Requirements, RequirementsSet
from canirunit.sources.steam import DETAILS_URL, parse_app_data

FIX = Path(__file__).parent / "fixtures" / "steam"

# Approximate PassMark-style numbers; the tests exercise the logic, not the benchmark data.
SCORES = {
    "gpu:geforce gtx 1060": 10000,
    "gpu:radeon rx 580": 9000,
    "gpu:arc a380": 6000,
    "gpu:geforce rtx 2060 super": 16000,
    "gpu:radeon rx 5700 xt": 17000,
    "gpu:arc a770": 15500,
    "gpu:geforce rtx 3060": 17000,
    "gpu:geforce rtx 4090": 38000,
    "gpu:radeon 780m": 3300,
    "gpu:intel uhd graphics": 1100,
    "cpu:core i7-6700": 7800,
    "cpu:ryzen 5 1600": 7500,
    "cpu:core i7-12700": 25000,
    "cpu:ryzen 7 7800x3d": 34000,
    "cpu:ryzen z1 extreme": 20000,
    "cpu:ryzen 5 5600x": 22000,
    "cpu:ryzen 9 7950x3d": 60000,
    "cpu:core i3-1115g4": 7000,
}


def cyberpunk() -> GameDetails:
    d = json.loads((FIX / "appdetails_1091500.json").read_text())["1091500"]["data"]
    game = parse_app_data(1091500, d)
    p = parse_pc_requirements(d["pc_requirements"])
    game.requirements = RequirementsSet(
        minimum=p.minimum.requirements, recommended=p.recommended.requirements
    )
    return game


async def report(profile, scores=SCORES, game=None):
    hw = MockDetector(profile).detect()
    return await build_report(hw, game or cyberpunk(), StaticResolver(scores))


def row(rep, key):
    return next(r for r in rep.rows if r.key == key)


async def test_high_end_desktop_buys_and_exceeds():
    rep = await report("desktop_high_end")
    assert rep.recommendation == Recommendation.BUY
    assert row(rep, "gpu").verdict == Verdict.EXCEEDS_RECOMMENDED
    assert "Also present" in row(rep, "gpu").note  # the second (integrated) GPU is shown
    assert rep.overall_verdict in (Verdict.MEETS_RECOMMENDED, Verdict.EXCEEDS_RECOMMENDED)


async def test_rtx3060_desktop():
    rep = await report("desktop_rtx3060")
    assert row(rep, "gpu").verdict == Verdict.MEETS_RECOMMENDED
    assert row(rep, "cpu").verdict == Verdict.MEETS_MIN  # 22000 vs 25000 recommended
    assert (
        row(rep, "vram").verdict == Verdict.MEETS_RECOMMENDED
    )  # no recommended VRAM listed; 2x the minimum
    assert rep.recommendation == Recommendation.BUY_WITH_COMPROMISES
    assert rep.bottleneck == "cpu"


async def test_ally_gpu_is_hopelessly_below_for_cyberpunk():
    rep = await report("ally_z1e", {**SCORES, "gpu:radeon 780m": 2700})  # 45% of the minimum
    gpu = row(rep, "gpu")
    assert gpu.verdict == Verdict.BELOW_MIN
    assert "Compared against the weakest listed option: Arc A380" in gpu.note
    assert gpu.your_score == 2700 and gpu.min_score == 6000  # 780M resolved via the Z1 Extreme hint
    assert rep.recommendation == Recommendation.DONT_BUY  # 45% of the minimum, under the 50% bar
    assert rep.bottleneck == "gpu"
    assert "weakest" not in rep.headline


async def test_ally_shared_vram_is_not_a_hard_fail():
    rep = await report("ally_z1e")
    vram = row(rep, "vram")
    assert vram.verdict == Verdict.MEETS_MIN  # 6 GB assumed (software-adjustable; detected 4)
    assert "Armoury Crate" in vram.note and "assumed" in vram.yours
    ram = row(rep, "ram")
    assert ram.verdict != Verdict.BELOW_MIN and "reserved" in ram.note


async def test_low_end_laptop_dont_buy_and_fails_storage_ram():
    rep = await report("laptop_igpu_lowend")
    assert rep.recommendation == Recommendation.DONT_BUY
    assert row(rep, "ram").verdict == Verdict.BELOW_MIN  # 8 GB vs 12 GB
    assert row(rep, "storage").verdict == Verdict.BELOW_MIN  # 60 GB free vs 70


async def test_borderline_gpu_is_risky_not_dont_buy():
    scores = {**SCORES, "gpu:radeon 780m": 4200}  # 70% of the minimum
    rep = await report("ally_z1e", scores)
    assert row(rep, "gpu").verdict == Verdict.BELOW_MIN
    assert rep.recommendation == Recommendation.RISKY


async def test_unknown_is_never_a_pass():
    no_gpu = {k: v for k, v in SCORES.items() if not k.startswith("gpu:")}
    rep = await report("desktop_high_end", no_gpu)
    gpu = row(rep, "gpu")
    assert gpu.verdict == Verdict.UNKNOWN and gpu.confidence == Confidence.LOW
    assert rep.recommendation == Recommendation.INSUFFICIENT_DATA
    assert rep.confidence == Confidence.LOW
    assert any("could not be compared" in r for r in rep.reasons)


async def test_weakest_alternative_and_unresolved_alternatives_lower_confidence():
    partial = {k: v for k, v in SCORES.items() if k != "gpu:arc a380"}  # weakest alt unresolved
    rep = await report("desktop_rtx3060", partial)
    gpu = row(rep, "gpu")
    assert gpu.min_score == 9000  # falls back to the weakest *resolved* alternative
    assert gpu.confidence == Confidence.LOW
    assert "could not be scored" in gpu.note


async def test_missing_requirements_gives_insufficient_data():
    game = cyberpunk()
    game.requirements = None
    game.requirements_status = "missing"
    rep = await report("ally_z1e", game=game)
    assert rep.recommendation == Recommendation.INSUFFICIENT_DATA and rep.rows == []


async def test_unspecified_rows_are_not_counted_as_unknowns():
    game = GameDetails(
        appid=1,
        name="Tiny",
        store_url="x",
        requirements=RequirementsSet(
            minimum=Requirements(cpu=["Core i7-6700"], gpu=["GeForce GTX 1060"], ram_gb=8)
        ),
    )
    rep = await report("desktop_rtx3060", game=game)
    assert not row(rep, "os").specified and row(rep, "os").verdict == Verdict.UNKNOWN
    assert rep.recommendation in (Recommendation.BUY, Recommendation.BUY_WITH_COMPROMISES)
    assert rep.confidence == Confidence.HIGH


async def test_os_and_ssd_rules():
    game = cyberpunk()
    game.requirements.minimum.os = "Windows 11"
    rep = await report("laptop_igpu_lowend", game=game)  # build 22631 -> Windows 11, passes
    assert row(rep, "os").verdict != Verdict.BELOW_MIN
    hdd_game = cyberpunk()
    hdd_game.requirements.minimum.storage_gb = 400  # only the 600 GB HDD has room
    rep = await report("desktop_rtx3060", game=hdd_game)
    st = row(rep, "storage")
    assert st.verdict == Verdict.BELOW_MIN and "SSD" in st.note


async def test_no_windows_build_is_dont_buy():
    game = cyberpunk()
    game.windows_supported = False
    rep = await report("desktop_high_end", game=game)
    assert rep.recommendation == Recommendation.DONT_BUY


@pytest.mark.parametrize(
    ("mine", "mn", "rec", "expected"),
    [
        (50, 100, 200, Verdict.BELOW_MIN),
        (96, 100, 200, Verdict.MEETS_MIN),  # within the 5% margin
        (150, 100, 200, Verdict.MEETS_MIN),
        (200, 100, 200, Verdict.MEETS_RECOMMENDED),
        (300, 100, 200, Verdict.EXCEEDS_RECOMMENDED),
        (150, 100, None, Verdict.MEETS_MIN),
        (250, 100, None, Verdict.MEETS_RECOMMENDED),
        (120, None, 100, Verdict.MEETS_RECOMMENDED),
        (50, None, 100, Verdict.UNKNOWN),
        (50, None, None, Verdict.UNKNOWN),
    ],
)
def test_tier_verdict(mine, mn, rec, expected):
    assert tier_verdict(mine, mn, rec)[0] == expected


@respx.mock
def test_report_endpoint(tmp_path):
    data = json.loads((FIX / "appdetails_1091500.json").read_text())
    respx.get(DETAILS_URL).mock(return_value=httpx.Response(200, json=data))
    settings = Settings(anthropic_api_key="", canirunit_cache_dir=str(tmp_path))
    app = create_app(MockDetector("desktop_rtx3060"), settings, resolver=StaticResolver(SCORES))
    with TestClient(app) as client:
        r = client.get("/api/report/1091500")
        assert r.status_code == 200
        body = r.json()
        assert body["recommendation"] == "BUY_WITH_COMPROMISES"
        assert body["rows"][0]["icon"] and body["game"]["name"] == "Cyberpunk 2077"
