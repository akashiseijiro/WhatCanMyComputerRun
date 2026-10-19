import json
from types import SimpleNamespace as NS

import anthropic
import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from test_engine import FIX, SCORES

from whatcanmycomputerrun.api.app import create_app
from whatcanmycomputerrun.compare.resolver import StaticResolver
from whatcanmycomputerrun.config import Settings
from whatcanmycomputerrun.hardware.mock import MockDetector
from whatcanmycomputerrun.llm.client import LLMClient, LLMRateLimited, LLMUnavailable
from whatcanmycomputerrun.parsing.llm_parser import LLMRequirementsParser
from whatcanmycomputerrun.sources.cache import TTLCache
from whatcanmycomputerrun.sources.service import GameService
from whatcanmycomputerrun.sources.steam import DETAILS_URL, SteamClient
from whatcanmycomputerrun.sources.web_fallback import (
    WebRequirementsFinder,
    WebRequirementsNotFound,
    parse_answer,
    split_tiers,
)

ANSWER = """Here are the requirements I found.

**MINIMUM:**
- **OS:** Windows 10 64-bit
- **Processor:** Intel Core i5-8400 or AMD Ryzen 3 1200
- **Memory:** 8 GB RAM
- **Graphics:** NVIDIA GeForce GTX 960 4GB or AMD Radeon RX 470
- **DirectX:** Version 12
- **Storage:** 50 GB available space

## RECOMMENDED:
OS: Windows 11
Processor: Intel Core i7-9700K
Memory: 16 GB RAM
Graphics: NVIDIA GeForce RTX 2060
"""


def text(t, urls=()):
    cites = [NS(type="web_search_result_location", url=u, title="t") for u in urls]
    return NS(type="text", text=t, citations=cites or None)


def results(*urls):
    return NS(
        type="web_search_tool_result",
        content=[NS(type="web_search_result", url=u, title="t") for u in urls],
    )


def resp(blocks, stop="end_turn"):
    return NS(content=blocks, stop_reason=stop)


class StubMessages:
    def __init__(self, *responses, error=None):
        self.responses, self.error, self.calls = list(responses), error, []

    async def create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return self.responses.pop(0)


def llm_with(msgs):
    return LLMClient(Settings(anthropic_api_key="k"), client=NS(messages=msgs))


async def ask(llm):
    return await llm.web_search(model="claude-haiku-4-5", system="s", user="u")


async def test_web_search_returns_text_and_prefers_cited_urls():
    msgs = StubMessages(
        resp(
            [
                text("Searching."),
                results("https://a.example/x", "https://b.example/y"),
                text(
                    "ANSWER", ["https://b.example/y", "javascript:alert(1)", "https://b.example/y"]
                ),
            ]
        )
    )
    out, urls = await ask(llm_with(msgs))
    assert out == "Searching.ANSWER"
    assert urls == ["https://b.example/y"]  # cited only, deduped, non-http dropped
    tool = msgs.calls[0]["tools"][0]
    assert tool["type"] == "web_search_20250305" and tool["max_uses"] == 3


async def test_web_search_falls_back_to_found_urls_when_nothing_cited():
    msgs = StubMessages(
        resp([results("https://a.example/1", "ftp://bad", "https://a.example/2"), text("A")])
    )
    _, urls = await ask(llm_with(msgs))
    assert urls == ["https://a.example/1", "https://a.example/2"]


async def test_pause_turn_is_resumed_with_the_assistant_turn():
    first = resp([text("partial"), results("https://a.example/1")], stop="pause_turn")
    second = resp([text("final", ["https://a.example/1"])])
    msgs = StubMessages(first, second)
    out, urls = await ask(llm_with(msgs))
    assert out == "final" and urls == ["https://a.example/1"]
    resumed = msgs.calls[1]["messages"]
    assert resumed[0]["role"] == "user" and resumed[1] == {
        "role": "assistant",
        "content": first.content,
    }


async def test_all_searches_failed_raises():
    err = NS(
        type="web_search_tool_result",
        content=NS(type="web_search_tool_result_error", error_code="unavailable"),
    )
    with pytest.raises(LLMUnavailable, match="unavailable"):
        await ask(llm_with(StubMessages(resp([err]))))


async def test_api_errors_are_translated():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    rl = anthropic.RateLimitError("slow", response=httpx.Response(429, request=req), body=None)
    with pytest.raises(LLMRateLimited):
        await ask(llm_with(StubMessages(error=rl)))
    conn = anthropic.APIConnectionError(request=req)
    with pytest.raises(LLMUnavailable):
        await ask(llm_with(StubMessages(error=conn)))


def test_split_tiers_handles_markdown_bullets_and_headings():
    mn, rec = split_tiers(ANSWER)
    assert mn.startswith("OS: Windows 10") and "GTX 960" in mn and "i7-9700K" not in mn
    assert rec.startswith("OS: Windows 11") and "RTX 2060" in rec


def test_parse_answer_reads_labelled_text_like_steam():
    p = parse_answer(ANSWER)
    mn, rec = p.minimum.requirements, p.recommended.requirements
    assert mn.cpu == ["Intel Core i5-8400", "AMD Ryzen 3 1200"]
    assert mn.gpu == ["NVIDIA GeForce GTX 960 4GB", "AMD Radeon RX 470"]
    assert mn.ram_gb == 8 and mn.storage_gb == 50 and mn.directx == "12" and mn.vram_gb == 4
    assert rec.ram_gb == 16 and rec.gpu == ["NVIDIA GeForce RTX 2060"]


def test_parse_answer_not_found_and_garbage():
    assert parse_answer("NOT_FOUND").minimum is None
    assert parse_answer("I could not find anything useful, sorry.").minimum is None


def finder(tmp_path, *responses):
    msgs = StubMessages(*responses)
    return WebRequirementsFinder(llm_with(msgs), "claude-haiku-4-5", TTLCache(tmp_path, 24)), msgs


async def test_finder_caches_and_raises_when_not_found(tmp_path):
    f, msgs = finder(tmp_path, resp([text(ANSWER, ["https://pub.example/req"])]))
    first = await f.find("Some Game")
    assert first.urls == ["https://pub.example/req"] and not first.unofficial
    again = await f.find("some game")  # case-insensitive cache hit: no second API call
    assert again.parsed.minimum is not None and len(msgs.calls) == 1
    f2, _ = finder(tmp_path / "b", resp([text("NOT_FOUND")]))
    with pytest.raises(WebRequirementsNotFound):
        await f2.find("Imaginary Game")


async def test_finder_flags_unofficial_sources(tmp_path):
    f, _ = finder(
        tmp_path,
        resp([text(ANSWER + "\nSource note: unofficial source", ["https://wiki.example/g"])]),
    )
    assert (await f.find("G")).unofficial


async def service(tmp_path, *responses):
    f, _ = finder(tmp_path, *responses)
    http = httpx.AsyncClient()
    steam = SteamClient(http, TTLCache(tmp_path / "s", 24))
    return GameService(steam, LLMRequirementsParser(llm_with(StubMessages()), "m"), f), http


async def test_service_builds_web_sourced_game(tmp_path):
    svc, http = await service(tmp_path, resp([text(ANSWER, ["https://pub.example/req"])]))
    async with http:
        g = await svc.web_game("Valorant")
    r = g.requirements
    assert g.appid == 0 and g.name == "Valorant" and g.store_url == "" and g.price is None
    assert (
        r.source == "web_search"
        and r.parse_method == "llm"
        and r.source_urls == ["https://pub.example/req"]
    )
    assert any("AI web search" in w for w in r.warnings)
    assert not any("unofficial" in w for w in r.warnings)


async def test_service_warns_when_no_sources_reported(tmp_path):
    svc, http = await service(tmp_path, resp([text(ANSWER)]))
    async with http:
        g = await svc.web_game("X")
    assert any("No source pages" in w for w in g.requirements.warnings)


@respx.mock
async def test_service_keeps_steam_details_when_appid_given(tmp_path):
    data = json.loads((FIX / "appdetails_1091500.json").read_text())
    data["1091500"]["data"]["pc_requirements"] = []  # Steam lists none; web fills in
    respx.get(DETAILS_URL).mock(return_value=httpx.Response(200, json=data))
    svc, http = await service(tmp_path, resp([text(ANSWER, ["https://pub.example/req"])]))
    async with http:
        g = await svc.web_game("Cyberpunk 2077", appid=1091500)
    assert (
        g.appid == 1091500 and g.price and g.header_image and g.requirements.source == "web_search"
    )


@respx.mock
def test_web_report_endpoint_and_not_found(tmp_path):
    st = Settings(anthropic_api_key="", whatcanmycomputerrun_cache_dir=str(tmp_path))
    finder_, _ = finder(
        tmp_path / "w", resp([text(ANSWER, ["https://pub.example/req"])]), resp([text("NOT_FOUND")])
    )
    games = GameService(
        SteamClient(httpx.AsyncClient(), TTLCache(tmp_path / "s", 24)), None, finder_
    )
    app = create_app(
        MockDetector("desktop_rtx3060"), st, games=games, resolver=StaticResolver(SCORES)
    )
    with TestClient(app) as client:
        r = client.get("/api/web-report", params={"name": "Indie Thing"})
        assert r.status_code == 200
        body = r.json()
        assert body["game"]["requirements"]["source"] == "web_search"
        assert body["game"]["requirements"]["source_urls"] == ["https://pub.example/req"]
        assert body["confidence"] != "high"  # AI-sourced requirements cap confidence
        assert body["settings"] is not None
        miss = client.get("/api/web-report", params={"name": "Nope Nope"})
        assert miss.status_code == 404 and miss.json()["code"] == "web_not_found"
        assert client.get("/api/web-report", params={"name": ""}).status_code == 422
