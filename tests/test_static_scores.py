import json
from pathlib import Path

import pytest

from tests.test_engine import SCORES, cyberpunk, row
from whatcanmycomputerrun.compare.engine import build_report
from whatcanmycomputerrun.compare.models import Verdict
from whatcanmycomputerrun.compare.resolver import SCORE_BOUNDS, ComponentQuery, StaticResolver
from whatcanmycomputerrun.compare.static_scores import (
    CPU_TABLE,
    GPU_TABLE,
    StaticTableResolver,
    cpu_key,
    gpu_key,
    lookup,
)
from whatcanmycomputerrun.hardware.windows_parse import build_profile

FIX = Path(__file__).parent / "fixtures" / "windows_raw"


def gpu(name):
    s = lookup(ComponentQuery("gpu", name))
    return s.score if s else None


def cpu(name):
    s = lookup(ComponentQuery("cpu", name))
    return s.score if s else None


def test_tables_are_populated_and_in_bounds():
    assert len(GPU_TABLE) > 140 and len(CPU_TABLE) > 280
    for kind, table in (("gpu", GPU_TABLE), ("cpu", CPU_TABLE)):
        lo, hi = SCORE_BOUNDS[kind]
        for key, (name, score) in table.items():
            assert lo <= score <= hi, f"{name} -> {score}"
            assert key == (gpu_key(name) if kind == "gpu" else cpu_key(name))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("NVIDIA GeForce RTX 3060 Laptop GPU", 13093),
        ("NVIDIA GeForce RTX 3060", 16883),
        ("GeForce GTX 1660(6GB)", 11609),  # Steam style
        ("Radeon RX 5500 XT(8GB)", 9042),
        ("GTX 1060", 10013),  # no "GeForce" prefix
        ("NVIDIA GeForce GTX 1060 6GB", 10013),
        ("AMD Radeon RX 6600", 15031),
        ("Intel(R) Arc(TM) A770 Graphics", 13380),  # real Windows name
        ("Intel Arc A770", 13380),
    ],
)
def test_gpu_lookup(name, expected):
    assert gpu(name) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("11th Gen Intel(R) Core(TM) i7-11800H @ 2.30GHz", 19547),  # real Windows string
        ("Intel Core i5-10400", 11956),
        ("Intel Core i5 10400F", 12090),
        ("i5-12400", 18833),
        ("AMD Ryzen 5 3600 6-Core Processor", 17646),
        ("AMD Ryzen 5 5600X 6-Core Processor", 21819),
        ("AMD Ryzen 7 7800X3D 8-Core Processor", 34279),
        ("Intel(R) Core(TM) Ultra 7 155H", 24414),
        ("AMD Ryzen Z1 Extreme", 24556),
        ("Intel Core i7-6700", None),  # pre-2019
    ],
)
def test_cpu_lookup(name, expected):
    assert cpu(name) == expected


GPU_ORDER = [  # (faster, slower): relationships that must hold on any sane benchmark scale
    ("NVIDIA GeForce RTX 3060 Laptop GPU", "GeForce GTX 1660"),
    ("NVIDIA GeForce RTX 3060 Laptop GPU", "Radeon RX 5500 XT"),
    ("GeForce RTX 3060", "NVIDIA GeForce RTX 3060 Laptop GPU"),
    ("GeForce RTX 4090", "GeForce RTX 4080"),
    ("GeForce RTX 4080", "GeForce RTX 4070"),
    ("GeForce RTX 4070", "GeForce RTX 4060"),
    ("GeForce RTX 3080", "GeForce RTX 3070"),
    ("GeForce RTX 3070", "GeForce RTX 3060 Ti"),
    ("GeForce RTX 3060 Ti", "GeForce RTX 3060"),
    ("GeForce RTX 2080 Ti", "GeForce RTX 2080"),
    ("GeForce RTX 2060 SUPER", "GeForce RTX 2060"),
    ("GeForce RTX 2060", "GeForce GTX 1660 Ti"),
    ("GeForce GTX 1660 Ti", "GeForce GTX 1660"),
    ("GeForce GTX 1660", "GeForce GTX 1650"),
    ("GeForce GTX 1060", "GeForce GTX 1050 Ti"),
    ("GeForce GTX 1050 Ti", "GeForce GTX 1050"),
    ("Radeon RX 7900 XTX", "Radeon RX 7800 XT"),
    ("Radeon RX 6800 XT", "Radeon RX 6700 XT"),
    ("Radeon RX 6600", "Radeon RX 5500 XT"),
    ("Radeon RX 5700 XT", "Radeon RX 5600 XT"),
    ("Radeon RX 580", "Radeon RX 560"),
    ("Intel Arc B580", "Intel Arc A750"),
    ("Intel Arc A750", "Intel Arc A380"),
    ("GeForce RTX 4060 Laptop GPU", "GeForce RTX 3050 Ti Laptop GPU"),
]

CPU_ORDER = [
    ("Intel Core i5-12400", "Intel Core i5-10400"),
    ("Intel Core i5-10400", "Intel Core i3-10100"),
    ("Intel Core i9-14900K", "Intel Core i7-14700K"),
    ("Intel Core i7-14700K", "Intel Core i5-14600K"),
    ("Intel Core i7-12700K", "Intel Core i5-12600K"),
    ("AMD Ryzen 5 5600X", "AMD Ryzen 5 3600"),
    ("AMD Ryzen 7 5800X", "AMD Ryzen 5 5600X"),
    ("AMD Ryzen 7 7800X3D", "AMD Ryzen 7 5800X3D"),
    ("AMD Ryzen 9 7950X", "AMD Ryzen 7 7700X"),
    ("AMD Ryzen 5 3600", "AMD Ryzen 3 3300X"),
    ("AMD Ryzen 9 7945HX", "AMD Ryzen 7 7840HS"),
    ("AMD Ryzen 7 7840HS", "AMD Ryzen Z1"),
    ("AMD Ryzen Z1", "AMD Ryzen Z2 Go"),
    ("Intel Core i7-11800H", "Intel Core i7-10750H"),
]


@pytest.mark.parametrize(("fast", "slow"), GPU_ORDER)
def test_gpu_ordering(fast, slow):
    assert gpu(fast) is not None and gpu(slow) is not None
    assert gpu(fast) > gpu(slow), f"{fast} should outscore {slow}"


@pytest.mark.parametrize(("fast", "slow"), CPU_ORDER)
def test_cpu_ordering(fast, slow):
    assert cpu(fast) is not None and cpu(slow) is not None
    assert cpu(fast) > cpu(slow), f"{fast} should outscore {slow}"


def test_laptop_variant_never_beats_same_named_desktop_card():
    checked = 0
    for key, (name, score) in GPU_TABLE.items():
        if key.endswith(" laptop") and key.removesuffix(" laptop") in GPU_TABLE:
            assert score <= GPU_TABLE[key.removesuffix(" laptop")][1], name
            checked += 1
    assert checked >= 8


async def test_unknown_parts_fall_through_to_the_fallback():
    fallback = StaticResolver({"cpu:core i7-6700": 7800.0})
    r = StaticTableResolver(fallback)
    qs = [ComponentQuery("cpu", "Intel Core i7-6700"), ComponentQuery("gpu", "GeForce GTX 1660")]
    out = await r.resolve(qs)
    assert out.get(qs[0]).score == 7800.0  # from the fallback
    hit = out.get(qs[1])
    assert (
        hit.score == 11609 and hit.confidence == "high" and hit.matched_name == "GeForce GTX 1660"
    )


async def test_without_fallback_unknown_parts_are_simply_missing():
    q = ComponentQuery("cpu", "Intel Core i7-6700")
    assert (await StaticTableResolver().resolve([q])).get(q) is None


async def test_real_laptop_is_not_below_cyberpunk_minimum():
    d = json.loads((FIX / "laptop_rtx3060.json").read_text(encoding="utf-8"))
    hw = build_profile(d["wmi"], d["registry"], d["dxgi"])
    old_cpus = {k: v for k, v in SCORES.items() if k.startswith("cpu:")}
    rep = await build_report(hw, cyberpunk(), StaticTableResolver(StaticResolver(old_cpus)))
    gpu_row = row(rep, "gpu")
    assert gpu_row.your_score == 13093
    assert gpu_row.verdict != Verdict.BELOW_MIN and gpu_row.verdict != Verdict.UNKNOWN
    assert row(rep, "cpu").your_score == 19547
