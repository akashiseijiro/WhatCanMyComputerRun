import ipaddress
from types import SimpleNamespace

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from whatcanmycomputerrun.api.app import create_app
from whatcanmycomputerrun.compare.static_scores import StaticTableResolver
from whatcanmycomputerrun.config import Settings
from whatcanmycomputerrun.hardware.mock import MockDetector
from whatcanmycomputerrun.llm.client import LLMError, LLMUnavailable
from whatcanmycomputerrun.parsing.schemas import Requirements
from whatcanmycomputerrun.sources import custom_requirements as cr
from whatcanmycomputerrun.sources.service import GameService

PAGE = """<html><head><script>var x='Minimum';</script></head><body>
<nav>Home Store Support</nav><h1>Hades II</h1><p>Buy now $29.99</p>
<h2>System Requirements</h2><h3>Minimum</h3>
<ul><li>OS: Windows 10</li><li>Processor: Core i5-6600</li><li>Memory: 8 GB RAM</li>
<li>Graphics: GTX 1060 6GB</li><li>Storage: 20 GB</li></ul>
<h3>Recommended</h3><ul><li>Processor: Core i7-8700</li><li>Memory: 16 GB RAM</li>
<li>Graphics: RTX 2060</li></ul><footer>Copyright</footer></body></html>"""

PUBLIC = [(2, 1, 6, "", ("93.184.216.34", 0))]
HTML = {"content-type": "text/html"}


@pytest.fixture
def public_dns(monkeypatch):
    def fake(host, *_a, **_k):
        if host == "localhost":
            return [(2, 1, 6, "", ("127.0.0.1", 0))]
        try:  # IP literals resolve to themselves, as in the real resolver
            ipaddress.ip_address(host)
        except ValueError:
            return PUBLIC
        return [(2, 1, 6, "", (host, 0))]

    monkeypatch.setattr(cr.socket, "getaddrinfo", fake)


def test_extract_keeps_requirements_and_drops_scripts_and_nav():
    text = cr.extract_requirements_text(PAGE)
    assert "System Requirements" in text and "GTX 1060" in text
    assert "var x" not in text and "Home Store Support" not in text and "Copyright" not in text
    assert cr.looks_like_requirements(text)
    assert not cr.looks_like_requirements("Buy Hades II today. Great reviews.")


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",
        "file:///etc/passwd",
        "http://127.0.0.1/a",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://localhost/",
        "http://[::1]/",
        "not a url",
    ],
)
async def test_check_public_url_rejects_unsafe_links(public_dns, url):
    with pytest.raises(cr.CustomRequirementsError):
        await cr.check_public_url(url)


@respx.mock
async def test_fetch_page_ok_and_failures(public_dns):
    async with httpx.AsyncClient() as http:
        respx.get("https://example.com/hades").mock(
            return_value=httpx.Response(200, text=PAGE, headers=HTML)
        )
        assert "System Requirements" in await cr.fetch_page(http, "https://example.com/hades")

        respx.get("https://example.com/404").mock(return_value=httpx.Response(404))
        with pytest.raises(cr.CustomRequirementsError, match="404"):
            await cr.fetch_page(http, "https://example.com/404")

        respx.get("https://example.com/pdf").mock(
            return_value=httpx.Response(
                200, content=b"%PDF", headers={"content-type": "application/pdf"}
            )
        )
        with pytest.raises(cr.CustomRequirementsError, match="not a web page"):
            await cr.fetch_page(http, "https://example.com/pdf")

        respx.get("https://example.com/down").mock(side_effect=httpx.ConnectError("x"))
        with pytest.raises(cr.CustomRequirementsError, match="Could not download"):
            await cr.fetch_page(http, "https://example.com/down")


@respx.mock
async def test_redirect_to_a_private_address_is_refused(public_dns):
    respx.get("https://example.com/r").mock(
        return_value=httpx.Response(302, headers={"location": "http://127.0.0.1:8000/admin"})
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(cr.CustomRequirementsError, match="private"):
            await cr.fetch_page(http, "https://example.com/r")


@respx.mock
async def test_redirect_loop_is_cut_off(public_dns):
    respx.get("https://example.com/loop").mock(
        return_value=httpx.Response(302, headers={"location": "https://example.com/loop"})
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(cr.CustomRequirementsError, match="too many"):
            await cr.fetch_page(http, "https://example.com/loop")


MIN = Requirements(
    os="Windows 10", cpu=["Core i5-6600"], gpu=["GTX 1060 6GB"], ram_gb=8, storage_gb=20
)
REC = Requirements(cpu=["Core i7-8700"], gpu=["RTX 2060"], ram_gb=16)


class FakeParser:
    def __init__(self, result=(MIN, REC), available=True, error=None):
        self.llm = SimpleNamespace(available=available)
        self.result, self.error, self.seen = result, error, []

    async def parse_text(self, name, text):
        self.seen.append((name, text))
        if self.error:
            raise self.error
        return self.result


def service(parser, http=None):
    return GameService(None, parser, None, http)  # type: ignore[arg-type]


async def test_custom_game_from_pasted_text():
    parser = FakeParser()
    game = await service(parser).custom_game("Hades II", text="  Minimum: GTX 1060  ")
    assert parser.seen == [("Hades II", "Minimum: GTX 1060")]
    req = game.requirements
    assert req and req.source == "user_provided" and req.parse_method == "llm"
    assert req.minimum and req.minimum.gpu == ["GTX 1060 6GB"] and req.source_urls == []
    assert "text you pasted" in req.warnings[0] and game.requirements_status == "ok"


@respx.mock
async def test_custom_game_from_a_link(public_dns):
    respx.get("https://example.com/hades").mock(
        return_value=httpx.Response(200, text=PAGE, headers=HTML)
    )
    parser = FakeParser()
    async with httpx.AsyncClient() as http:
        game = await service(parser, http).custom_game("Hades II", url="https://example.com/hades")
    assert "GTX 1060" in parser.seen[0][1] and "Home Store" not in parser.seen[0][1]
    assert game.requirements and game.requirements.source_urls == ["https://example.com/hades"]
    assert "page you linked" in game.requirements.warnings[0]


@respx.mock
async def test_page_without_requirements_asks_for_pasted_text(public_dns):
    respx.get("https://example.com/js").mock(
        return_value=httpx.Response(200, text="<html><body>Loading…</body></html>", headers=HTML)
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(cr.CustomRequirementsError, match="paste"):
            await service(FakeParser(), http).custom_game("X", url="https://example.com/js")


async def test_custom_game_errors():
    with pytest.raises(cr.CustomRequirementsError, match="Paste"):
        await service(FakeParser()).custom_game("X")
    with pytest.raises(cr.CustomRequirementsError, match="No system requirements"):
        await service(FakeParser(result=(None, None))).custom_game("X", text="hello")
    with pytest.raises(cr.CustomRequirementsError, match="Could not read"):
        await service(FakeParser(error=LLMError("bad"))).custom_game("X", text="hello")
    with pytest.raises(LLMUnavailable):
        await service(FakeParser(available=False)).custom_game("X", text="hello")


def client(parser):
    app = create_app(
        MockDetector("desktop_rtx3060"),
        Settings(anthropic_api_key="", gemini_api_key=""),
        games=service(parser),
        resolver=StaticTableResolver(),
    )
    return TestClient(app)


def test_custom_report_endpoint_builds_a_full_report():
    r = client(FakeParser()).post(
        "/api/custom-report", json={"name": "Hades II", "text": "Minimum: x"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["game"]["name"] == "Hades II" and body["game"]["appid"] == 0
    assert body["game"]["requirements"]["source"] == "user_provided"
    gpu = next(x for x in body["rows"] if x["key"] == "gpu")
    assert gpu["verdict"] in ("MEETS_MIN", "MEETS_RECOMMENDED", "EXCEEDS_RECOMMENDED")
    assert gpu["your_score"] == 16883 and gpu["min_score"] == 10013  # PassMark table, no AI


def test_custom_report_endpoint_errors():
    c = client(FakeParser())
    assert c.post("/api/custom-report", json={"name": "X"}).status_code == 422  # no link or text
    assert c.post("/api/custom-report", json={"text": "t"}).status_code == 422  # no name
    bad = client(FakeParser(result=(None, None))).post(
        "/api/custom-report", json={"name": "X", "text": "t"}
    )
    assert bad.status_code == 422 and bad.json()["code"] == "custom_requirements_failed"
    off = client(FakeParser(available=False)).post(
        "/api/custom-report", json={"name": "X", "text": "t"}
    )
    assert off.status_code == 503 and off.json()["code"] == "llm_unavailable"
