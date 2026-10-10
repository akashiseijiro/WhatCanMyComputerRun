import pytest

from canirunit.compare.models import Confidence
from canirunit.compare.normalize import igpu_from_cpu, normalize_cpu, normalize_gpu
from canirunit.compare.resolver import (
    ClaudeResolver,
    ComponentQuery,
    LLMComponentScore,
    LLMScoreBatch,
    StaticResolver,
)
from canirunit.config import Settings
from canirunit.llm.client import LLMClient, LLMRateLimited
from canirunit.sources.cache import TTLCache


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("NVIDIA GeForce RTX 3060", "geforce rtx 3060"),
        ("NVIDIA GeForce RTX 3060 Laptop GPU", "geforce rtx 3060"),
        ("GeForce GTX 1060 6GB", "geforce gtx 1060"),
        ("NVIDIA GEFORCE GTX 1060 3 GB", "geforce gtx 1060"),
        ("AMD Radeon RX 580 8GB", "radeon rx 580"),
        ("AMD Radeon(TM) Graphics", "radeon graphics"),
        ("Intel(R) UHD Graphics 620", "intel uhd graphics 620"),
        ("  GeForce   GTX 970 (4GB) ", "geforce gtx 970"),
    ],
)
def test_normalize_gpu(raw, expected):
    assert normalize_gpu(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Intel(R) Core(TM) i3-1115G4 @ 3.00GHz", "core i3-1115g4"),
        ("AMD Ryzen 5 5600X 6-Core Processor", "ryzen 5 5600x"),
        ("INTEL CORE I5-8400", "core i5-8400"),
        ("AMD Ryzen Z1 Extreme", "ryzen z1 extreme"),
    ],
)
def test_normalize_cpu(raw, expected):
    assert normalize_cpu(raw) == expected


def test_generic_igpu_resolved_from_cpu():
    assert igpu_from_cpu("radeon graphics", "AMD Ryzen Z1 Extreme") == "radeon 780m"
    assert igpu_from_cpu("radeon graphics", "AMD Ryzen 7 7840U") == "radeon 780m"
    assert igpu_from_cpu("radeon graphics", "AMD Ryzen 7 6800U") == "radeon 680m"
    assert igpu_from_cpu("radeon graphics", "Some Unknown CPU") is None
    assert igpu_from_cpu("geforce rtx 3060", "AMD Ryzen Z1 Extreme") is None


def test_query_keys():
    q = ComponentQuery("gpu", "AMD Radeon(TM) Graphics", hint="AMD Ryzen Z1 Extreme")
    assert q.key == "gpu:radeon 780m"
    unknown = ComponentQuery("gpu", "AMD Radeon(TM) Graphics", hint="Mystery CPU 9000")
    assert unknown.key == "gpu:radeon graphics@mystery 9000"
    assert (
        ComponentQuery("gpu", "GeForce GTX 1060 6GB").key
        == ComponentQuery("gpu", "NVIDIA GeForce GTX 1060").key
    )


class StubMessages:
    def __init__(self, batch=None, error=None):
        self.batch, self.error, self.calls = batch, error, []

    async def parse(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return type("R", (), {"parsed_output": self.batch})()


def make(tmp_path, batch=None, error=None, key="k"):
    msgs = StubMessages(batch, error)
    llm = LLMClient(Settings(anthropic_api_key=key), client=type("C", (), {"messages": msgs})())
    return ClaudeResolver(llm, "claude-haiku-4-5", TTLCache(tmp_path, 24)), msgs


async def test_claude_resolver_batches_and_caches(tmp_path):
    batch = LLMScoreBatch(
        results=[
            LLMComponentScore(
                id=0, score=2900, confidence=Confidence.MEDIUM, matched_name="Radeon 780M"
            ),
            LLMComponentScore(id=1, score=None, notes="too generic"),
            LLMComponentScore(id=7, score=1),  # bogus id is ignored
        ]
    )
    r, msgs = make(tmp_path, batch)
    qs = [
        ComponentQuery("gpu", "AMD Radeon Graphics", hint="AMD Ryzen Z1 Extreme"),
        ComponentQuery("cpu", "Intel Core i5"),
        ComponentQuery("cpu", "Intel Core i5"),  # duplicate
    ]
    res = await r.resolve(qs)
    assert len(msgs.calls) == 1
    assert msgs.calls[0]["model"] == "claude-haiku-4-5"
    assert (
        "Radeon Graphics" in msgs.calls[0]["messages"][0]["content"]
        and "Z1 Extreme" in msgs.calls[0]["messages"][0]["content"]
    )
    gpu = res.get(qs[0])
    assert gpu and gpu.score == 2900 and gpu.benchmark == "PassMark G3D Mark"
    assert res.get(qs[1]) is None  # generic name -> unresolved, never a guess
    res2 = await r.resolve(qs)  # all from cache now
    assert len(msgs.calls) == 1 and res2.get(qs[0]).score == 2900


async def test_resolver_degrades_without_key_and_on_errors(tmp_path):
    r, msgs = make(tmp_path, key="")
    r.llm._client = None
    res = await r.resolve([ComponentQuery("gpu", "GTX 1060")])
    assert not res.scores and "ANTHROPIC_API_KEY" in res.warnings[0]
    r2, _ = make(tmp_path / "b", error=LLMRateLimited("slow"))
    res = await r2.resolve([ComponentQuery("gpu", "GTX 1060")])
    assert not res.scores and "slow" in res.warnings[0]


async def test_static_resolver_is_pluggable():
    res = await StaticResolver({"gpu:geforce gtx 1060": 10000}).resolve(
        [ComponentQuery("gpu", "GeForce GTX 1060 6GB"), ComponentQuery("gpu", "Unknown")]
    )
    assert res.get(ComponentQuery("gpu", "NVIDIA GeForce GTX 1060")).score == 10000
    assert res.get(ComponentQuery("gpu", "Unknown")) is None
