import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from canirunit.api.app import create_app
from canirunit.config import Settings
from canirunit.hardware.mock import MockDetector
from canirunit.llm.client import LLMClient, LLMRateLimited
from canirunit.parsing.llm_parser import LLMRequirementsParser
from canirunit.parsing.schemas import LLMParsedRequirements, Requirements
from canirunit.sources.cache import TTLCache
from canirunit.sources.service import GameService
from canirunit.sources.steam import (
    DETAILS_URL,
    SEARCH_URL,
    GameNotFound,
    SteamClient,
    SteamRateLimited,
    SteamUnavailable,
)

FIX = Path(__file__).parent / "fixtures" / "steam"


def fx(name):
    return json.loads((FIX / name).read_text())


@pytest.fixture
def cache(tmp_path):
    return TTLCache(tmp_path / "cache", ttl_hours=24)


@pytest.fixture
async def steam(cache):
    async with httpx.AsyncClient() as http:
        yield SteamClient(http, cache)


@respx.mock
async def test_search_parses_and_caches(steam):
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=fx("search_cyberpunk.json")))
    results = await steam.search("Cyberpunk")
    assert results[0].appid == 1091500 and results[0].name == "Cyberpunk 2077"
    assert results[0].image and results[0].price == "59.99 USD"
    assert route.calls.last.request.url.params["term"] == "Cyberpunk"
    await steam.search("cyberpunk")  # served from cache
    assert route.call_count == 1


@respx.mock
async def test_app_details(steam):
    respx.get(DETAILS_URL).mock(return_value=httpx.Response(200, json=fx("appdetails_1091500.json")))
    game, raw = await steam.app_details(1091500)
    assert game.name == "Cyberpunk 2077" and game.release_date == "Dec 9, 2020"
    assert game.price and game.price.final_cents == 5999 and game.price.formatted == "$59.99"
    assert "minimum" in raw


@respx.mock
async def test_unknown_app(steam):
    respx.get(DETAILS_URL).mock(return_value=httpx.Response(200, json={"1": {"success": False}}))
    with pytest.raises(GameNotFound):
        await steam.app_details(1)


@respx.mock
@pytest.mark.parametrize(
    ("response", "exc"),
    [
        (httpx.Response(429), SteamRateLimited),
        (httpx.Response(503), SteamUnavailable),
        (httpx.Response(200, text="<html>not json"), SteamUnavailable),
        (httpx.ConnectError("offline"), SteamUnavailable),
        (httpx.ReadTimeout("slow"), SteamUnavailable),
    ],
)
async def test_error_mapping(steam, response, exc):
    route = respx.get(SEARCH_URL)
    route.mock(side_effect=response) if isinstance(response, Exception) else route.mock(return_value=response)
    with pytest.raises(exc):
        await steam.search("x")


def test_cache_ttl_and_corruption(tmp_path):
    t = [1000.0]
    c = TTLCache(tmp_path, ttl_hours=1, clock=lambda: t[0])
    c.set("k", {"a": 1})
    assert c.get("k") == {"a": 1}
    t[0] += 3601
    assert c.get("k") is None
    c.set("k", 1)
    next(tmp_path.glob("*.json")).write_text("{broken")
    assert c.get("k") is None
    c.set("k2", 2)
    assert c.clear() >= 1 and c.get("k2") is None


class StubMessages:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return type("R", (), {"parsed_output": self.result})()


def stub_llm(result=None, error=None):
    msgs = StubMessages(result, error)
    return LLMClient(Settings(anthropic_api_key=""), client=type("C", (), {"messages": msgs})()), msgs


GAPPY = {
    "minimum": "<ul><li><strong>OS:</strong> Windows 10</li><li><strong>Processor:</strong> Quad core CPU</li>"
    "<li><strong>Memory:</strong> 8 GB RAM</li></ul>"
}


@respx.mock
async def test_llm_fills_only_gaps(steam):
    data = fx("appdetails_1091500.json")
    data["1091500"]["data"]["pc_requirements"] = GAPPY
    respx.get(DETAILS_URL).mock(return_value=httpx.Response(200, json=data))
    llm, msgs = stub_llm(
        LLMParsedRequirements(minimum=Requirements(cpu=["WRONG"], gpu=["GTX 960 4GB"], ram_gb=99))
    )
    svc = GameService(steam, LLMRequirementsParser(llm, "claude-haiku-4-5"))
    g = await svc.game(1091500)
    mn = g.requirements.minimum
    assert mn.ram_gb == 8  # deterministic value wins over the LLM's
    assert mn.cpu == ["Quad core CPU"]
    assert mn.gpu == ["GTX 960 4GB"] and mn.vram_gb == 4  # gap filled by the LLM
    assert g.requirements.parse_method == "mixed"
    assert msgs.calls[0]["model"] == "claude-haiku-4-5"
    assert msgs.calls[0]["output_format"] is LLMParsedRequirements


@respx.mock
async def test_gaps_without_api_key_warn_not_crash(steam):
    data = fx("appdetails_1091500.json")
    data["1091500"]["data"]["pc_requirements"] = GAPPY
    respx.get(DETAILS_URL).mock(return_value=httpx.Response(200, json=data))
    svc = GameService(steam, LLMRequirementsParser(LLMClient(Settings(anthropic_api_key="")), "m"))
    g = await svc.game(1091500)
    assert g.requirements.minimum.gpu == [] and g.requirements.warnings
    assert g.requirements.parse_method == "deterministic"


@respx.mock
async def test_llm_failure_degrades_to_warning(steam):
    data = fx("appdetails_1091500.json")
    data["1091500"]["data"]["pc_requirements"] = GAPPY
    respx.get(DETAILS_URL).mock(return_value=httpx.Response(200, json=data))
    llm = LLMClient(Settings(anthropic_api_key="k"))

    async def boom(**_):
        raise LLMRateLimited("slow down")

    llm.parse = boom  # type: ignore[method-assign]
    g = await GameService(steam, LLMRequirementsParser(llm, "m")).game(1091500)
    assert any("slow down" in w for w in g.requirements.warnings)


@respx.mock
async def test_no_pc_requirements_marks_missing(steam):
    data = fx("appdetails_1091500.json")
    data["1091500"]["data"]["pc_requirements"] = []
    respx.get(DETAILS_URL).mock(return_value=httpx.Response(200, json=data))
    g = await GameService(steam, None).game(1091500)
    assert g.requirements is None and g.requirements_status == "missing"


@respx.mock
def test_api_routes_and_errors(tmp_path):
    settings = Settings(anthropic_api_key="", canirunit_cache_dir=str(tmp_path / "c"))
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=fx("search_cyberpunk.json")))
    respx.get(DETAILS_URL).mock(return_value=httpx.Response(200, json=fx("appdetails_1245620.json")))
    app = create_app(MockDetector("ally_z1e"), settings)
    with TestClient(app) as client:
        assert client.get("/api/search", params={"q": ""}).status_code == 422
        r = client.get("/api/search", params={"q": "cyberpunk"})
        assert r.status_code == 200 and r.json()[0]["appid"] == 1091500
        g = client.get("/api/game/1245620").json()
        assert g["name"] == "ELDEN RING" and g["requirements"]["minimum"]["ram_gb"] == 12

    respx.get(SEARCH_URL).mock(return_value=httpx.Response(429))
    with TestClient(create_app(MockDetector("ally_z1e"), settings)) as client:
        r = client.get("/api/search", params={"q": "zzz-uncached"})
        assert r.status_code == 429 and r.json()["code"] == "steam_rate_limited"
