import httpx
import pytest
import respx

from whatcanmycomputerrun.compare.resolver import LLMScoreBatch
from whatcanmycomputerrun.config import Settings
from whatcanmycomputerrun.llm.client import LLMClient, LLMError, LLMRateLimited, LLMUnavailable

URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"
)


def gemini_settings(**kw):
    return Settings(anthropic_api_key="", gemini_api_key="g-key", **kw)


def reply(text, **extra):
    return {"candidates": [{"content": {"parts": [{"text": text}]}, **extra}]}


def test_provider_selection():
    assert Settings(anthropic_api_key="a", gemini_api_key="g").provider == "anthropic"
    assert Settings(anthropic_api_key="", gemini_api_key="g").provider == "gemini"
    assert Settings(anthropic_api_key="", gemini_api_key="").provider == "anthropic"  # none set
    forced = Settings(
        anthropic_api_key="a", gemini_api_key="g", whatcanmycomputerrun_llm_provider="gemini"
    )
    assert forced.provider == "gemini" and forced.llm_available
    assert not Settings(anthropic_api_key="", gemini_api_key="").llm_available


def test_models_follow_the_provider():
    g = gemini_settings()
    assert g.resolver_model == g.search_model == "gemini-3.5-flash-lite"
    assert Settings(anthropic_api_key="a").resolver_model == "claude-haiku-4-5"


def test_embedded_key_is_used_when_no_own_key(monkeypatch):
    import whatcanmycomputerrun.config as config

    monkeypatch.setattr(config, "embedded_gemini_key", lambda: "baked")
    s = Settings(anthropic_api_key="", gemini_api_key="")
    assert s.gemini_key == "baked" and s.provider == "gemini" and s.llm_available
    assert Settings(anthropic_api_key="", gemini_api_key="mine").gemini_key == "mine"


@respx.mock
async def test_parse_sends_schema_and_validates():
    body = (
        '{"results": [{"id": 0, "matched_name": "RTX 3060", "score": 16883, "confidence": "high"}]}'
    )
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=reply(body)))
    llm = LLMClient(gemini_settings())
    out = await llm.parse(model="ignored", system="sys", user="u", schema=LLMScoreBatch)
    assert out.results[0].score == 16883
    req = route.calls.last.request
    assert req.headers["x-goog-api-key"] == "g-key"
    sent = req.read().decode()
    assert "responseJsonSchema" in sent and "application/json" in sent and "sys" in sent


@respx.mock
async def test_parse_ignores_thought_parts_and_rejects_bad_output():
    thought = {
        "candidates": [
            {"content": {"parts": [{"text": "hmm", "thought": True}, {"text": '{"results": []}'}]}}
        ]
    }
    respx.post(URL).mock(return_value=httpx.Response(200, json=thought))
    llm = LLMClient(gemini_settings())
    assert (await llm.parse(model="m", system="s", user="u", schema=LLMScoreBatch)).results == []

    respx.post(URL).mock(return_value=httpx.Response(200, json=reply("not json")))
    with pytest.raises(LLMError, match="expected shape"):
        await llm.parse(model="m", system="s", user="u", schema=LLMScoreBatch)
    respx.post(URL).mock(return_value=httpx.Response(200, json={"candidates": []}))
    with pytest.raises(LLMError, match="no structured output"):
        await llm.parse(model="m", system="s", user="u", schema=LLMScoreBatch)


@respx.mock
async def test_error_translation():
    llm = LLMClient(gemini_settings())

    async def call():
        return await llm.parse(model="m", system="s", user="u", schema=LLMScoreBatch)

    respx.post(URL).mock(return_value=httpx.Response(429, json={"error": {"message": "quota"}}))
    with pytest.raises(LLMRateLimited):
        await call()
    bad_key = {"error": {"message": "API key not valid. Please pass a valid API key."}}
    respx.post(URL).mock(return_value=httpx.Response(400, json=bad_key))
    with pytest.raises(LLMUnavailable, match="rejected"):
        await call()
    respx.post(URL).mock(return_value=httpx.Response(500, json={"error": {"message": "boom"}}))
    with pytest.raises(LLMError, match="500"):
        await call()
    respx.post(URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(LLMUnavailable, match="reach"):
        await call()


@respx.mock
async def test_web_search_returns_text_and_grounded_urls():
    data = reply(
        "Min: GTX 1060",
        groundingMetadata={
            "groundingChunks": [
                {"web": {"uri": "https://store.steampowered.com/app/1", "title": "Steam"}},
                {"web": {"uri": "javascript:alert(1)"}},
                {"web": {"uri": "https://store.steampowered.com/app/1"}},
            ]
        },
    )
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=data))
    text, urls = await LLMClient(gemini_settings()).web_search(model="m", system="s", user="u")
    assert text == "Min: GTX 1060" and urls == ["https://store.steampowered.com/app/1"]
    assert "google_search" in route.calls.last.request.read().decode()


@respx.mock
async def test_web_search_on_free_tier_explains_itself():
    respx.post(URL).mock(return_value=httpx.Response(429, json={"error": {"message": "quota"}}))
    with pytest.raises(LLMUnavailable, match="free"):
        await LLMClient(gemini_settings()).web_search(model="m", system="s", user="u")
