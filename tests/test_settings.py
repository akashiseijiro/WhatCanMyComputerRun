import json

import httpx
import respx
from fastapi.testclient import TestClient
from test_engine import FIX, SCORES, cyberpunk

from whatcanmycomputerrun.api.app import create_app
from whatcanmycomputerrun.compare.engine import build_report
from whatcanmycomputerrun.compare.models import Confidence
from whatcanmycomputerrun.compare.resolver import StaticResolver
from whatcanmycomputerrun.config import Settings
from whatcanmycomputerrun.hardware.base import GpuInfo, GpuVendor
from whatcanmycomputerrun.hardware.handhelds import power_profile
from whatcanmycomputerrun.hardware.mock import MockDetector
from whatcanmycomputerrun.llm.client import LLMClient, LLMRateLimited
from whatcanmycomputerrun.settings.llm_tips import GameTipsProvider
from whatcanmycomputerrun.settings.models import (
    GameTip,
    Preset,
    SettingsRecommendation,
    UpscaleMode,
)
from whatcanmycomputerrun.settings.rules import (
    frame_generation,
    interp_fps,
    recommend_settings,
    upscaler_technology,
)
from whatcanmycomputerrun.sources.cache import TTLCache
from whatcanmycomputerrun.sources.steam import DETAILS_URL


async def settings_for(profile, scores=SCORES, game=None):
    hw = MockDetector(profile).detect()
    rep = await build_report(hw, game or cyberpunk(), StaticResolver(scores))
    return hw, rep, recommend_settings(hw, rep)


async def test_high_end_gets_native_4k_without_upscaler():
    _, _, s = await settings_for("desktop_high_end")
    assert s.available and s.preset in (Preset.HIGH, Preset.ULTRA)
    assert s.upscaler.needed is False and s.upscaler.technology == "DLSS"
    assert s.render_resolution == s.output_resolution == "3840x2160"
    assert s.handheld is None and s.playable


async def test_midrange_desktop_uses_dlss_and_is_cpu_limited():
    _, _, s = await settings_for("desktop_rtx3060")
    assert s.upscaler.technology == "DLSS" and s.upscaler.needed
    assert s.preset in (Preset.HIGH, Preset.MEDIUM)
    assert s.fps.limited_by == "CPU"  # 5600X only just meets the minimum CPU score here
    assert any("CPU limits" in w for w in s.warnings)
    assert s.frame_generation.technology.startswith("FSR 3")  # RTX 30-series: no DLSS FG


async def test_ally_gets_fsr_handheld_advice_and_low_settings():
    _, rep, s = await settings_for("ally_z1e")
    assert s.preset == Preset.LOW
    assert s.upscaler.technology == "FSR" and s.upscaler.mode == UpscaleMode.PERFORMANCE
    assert s.render_resolution == "960x540" and s.output_resolution == "1920x1080"
    h = s.handheld
    assert h and h.device == "ASUS ROG Ally" and h.power_mode == "Turbo" and h.watts == 25
    assert h.fps_cap == 30 and h.battery_fps_cap == 30 and "h of play" in h.battery_note
    assert s.vram_tip and "Armoury Crate" in s.vram_tip
    assert s.playable and any("below the game's minimum" in w for w in s.warnings)
    assert s.frame_generation.suggested is False  # base FPS too low
    assert rep.settings is None  # attached by the API layer, not the report builder


async def test_easy_game_on_ally_uses_low_power_and_native():
    from whatcanmycomputerrun.parsing.schemas import GameDetails, Requirements, RequirementsSet

    game = GameDetails(
        appid=1,
        name="Indie",
        store_url="x",
        requirements=RequirementsSet(
            minimum=Requirements(cpu=["Core i7-6700"], gpu=["GeForce GTX 1060"], ram_gb=8),
            recommended=Requirements(cpu=["Core i7-12700"], gpu=["GeForce GTX 1060"], ram_gb=8),
        ),
    )
    scores = {**SCORES, "gpu:radeon 780m": 12000}
    _, _, s = await settings_for("ally_x", scores, game)
    assert s.handheld.power_mode in ("Silent", "Performance")  # no need for Turbo
    assert s.fps.low >= 30 and s.handheld.fps_cap in (40, 60)


async def test_unknown_gpu_gives_no_settings():
    no_gpu = {k: v for k, v in SCORES.items() if not k.startswith("gpu:")}
    _, _, s = await settings_for("desktop_high_end", no_gpu)
    assert not s.available and not s.playable and "couldn't be compared" in s.unavailable_reason
    assert s.preset is None


async def test_low_vram_caps_preset():
    game = cyberpunk()
    hw = MockDetector("desktop_rtx3060").detect()
    game.requirements.minimum.vram_gb = 24  # more than the 3060's 12 GB
    rep = await build_report(hw, game, StaticResolver(SCORES))
    s = recommend_settings(hw, rep)
    assert s.preset in (Preset.MEDIUM, Preset.LOW)
    assert any("video memory" in n for n in s.notes)


async def test_low_confidence_widens_fps_range():
    hw = MockDetector("desktop_high_end").detect()
    hi = await build_report(hw, cyberpunk(), StaticResolver(SCORES))
    lo = await build_report(hw, cyberpunk(), StaticResolver(SCORES, Confidence.LOW))
    a, b = recommend_settings(hw, hi).fps, recommend_settings(hw, lo).fps
    assert (b.high - b.low) > (a.high - a.low)
    assert any("Low confidence" in w for w in recommend_settings(hw, lo).warnings)


def test_interp_fps_anchors():
    assert interp_fps(200, 100, 200, 30, 60) == 60  # recommended spec -> 60
    assert interp_fps(100, 100, 200, 30, 60) == 30  # minimum spec -> 30
    assert 30 < interp_fps(150, 100, 200, 30, 60) < 60
    assert interp_fps(400, 100, 200, 30, 60) == 120  # linear beyond the recommended spec
    assert interp_fps(50, 100, 200, 30, 60) == 15
    assert interp_fps(100, None, 200, 30, 60) == 30  # recommended-only anchor


def test_upscaler_and_frame_gen_rules():
    def g(name, vendor):
        return GpuInfo(name=name, vendor=vendor)

    assert upscaler_technology(g("NVIDIA GeForce RTX 3060", GpuVendor.NVIDIA)) == "DLSS"
    assert upscaler_technology(g("NVIDIA GeForce GTX 1060", GpuVendor.NVIDIA)) == "FSR"
    assert upscaler_technology(g("AMD Radeon RX 6600", GpuVendor.AMD)) == "FSR"
    assert upscaler_technology(g("Intel(R) Arc(TM) A770", GpuVendor.INTEL)) == "XeSS"
    assert upscaler_technology(g("Intel(R) UHD Graphics", GpuVendor.INTEL)) == "FSR"
    rtx40 = g("NVIDIA GeForce RTX 4070", GpuVendor.NVIDIA)
    assert frame_generation(rtx40, 50, 144).technology == "DLSS Frame Generation"
    assert frame_generation(rtx40, 50, 144).suggested
    assert not frame_generation(rtx40, 30, 144).suggested
    assert not frame_generation(rtx40, 120, 144).suggested
    assert "latency" in frame_generation(rtx40, 50, 144).latency_caveat


def test_power_profiles_extensible_and_generic_fallback():
    assert power_profile("ASUS ROG Ally")[1] is True
    generic, known = power_profile("Some New Handheld")
    assert not known and [m.watts for m in generic.modes] == [9, 15, 25]


@respx.mock
def test_report_endpoint_includes_settings(tmp_path):
    data = json.loads((FIX / "appdetails_1091500.json").read_text(encoding="utf-8"))
    respx.get(DETAILS_URL).mock(return_value=httpx.Response(200, json=data))
    st = Settings(anthropic_api_key="", whatcanmycomputerrun_cache_dir=str(tmp_path))
    app = create_app(MockDetector("ally_z1e"), st, resolver=StaticResolver(SCORES))
    with TestClient(app) as client:
        body = client.get("/api/report/1091500").json()
        assert body["settings"]["preset"] == "Low"
        assert body["settings"]["handheld"]["power_mode"] == "Turbo"
        assert client.get("/api/tips/1091500").json() == {
            "tips": [],
            "warning": "Game-specific tips need an ANTHROPIC_API_KEY.",
        }


class StubMessages:
    def __init__(self, tips=None, error=None):
        self.tips, self.error, self.calls = tips, error, 0

    async def parse(self, **kw):
        self.calls += 1
        if self.error:
            raise self.error
        return type("R", (), {"parsed_output": kw["output_format"](tips=self.tips)})()


def provider(tmp_path, tips=None, error=None):
    msgs = StubMessages(tips, error)
    llm = LLMClient(Settings(anthropic_api_key="k"), client=type("C", (), {"messages": msgs})())
    return GameTipsProvider(llm, "claude-haiku-4-5", TTLCache(tmp_path, 24)), msgs


async def test_tips_cached_and_failures_degrade(tmp_path):
    rec = SettingsRecommendation(available=True, preset=Preset.LOW, render_resolution="960x540")
    p, msgs = provider(tmp_path, [GameTip(setting="Ray tracing", advice="Turn it off.")] * 7)
    tips, warn = await p.tips(1, "Cyberpunk 2077", rec, "handheld", "Radeon 780M")
    assert len(tips) == 5 and warn is None  # capped at five
    await p.tips(1, "Cyberpunk 2077", rec, "handheld", "Radeon 780M")
    assert msgs.calls == 1  # second call served from cache
    p2, _ = provider(tmp_path / "b", error=LLMRateLimited("slow"))
    tips, warn = await p2.tips(1, "X", rec, "desktop", "GPU")
    assert tips == [] and "slow" in warn
    none_rec = SettingsRecommendation(available=False)
    assert await p.tips(1, "X", none_rec, "desktop", "GPU") == ([], None)
