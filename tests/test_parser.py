import json
from pathlib import Path

import pytest

from whatcanmycomputerrun.parsing.requirements_parser import (
    parse_pc_requirements,
    parse_size_gb,
    parse_tier,
    split_alternatives,
    vram_from_gpus,
)

FIX = Path(__file__).parent / "fixtures" / "steam"


def pc_req(appid):
    d = json.loads((FIX / f"appdetails_{appid}.json").read_text(encoding="utf-8"))
    return d[str(appid)]["data"]["pc_requirements"]


def test_cyberpunk_real_page():
    p = parse_pc_requirements(pc_req(1091500))
    mn, rec = p.minimum.requirements, p.recommended.requirements
    assert mn.cpu == ["Core i7-6700", "Ryzen 5 1600"]
    assert mn.gpu == ["GeForce GTX 1060 6GB", "Radeon RX 580 8GB", "Arc A380"]
    assert mn.ram_gb == 12 and mn.storage_gb == 70 and mn.directx == "12"
    assert mn.vram_gb == 6  # weakest listed alternative with a stated size
    assert mn.os == "64-bit Windows 10" and "SSD required" in (mn.notes or "")
    assert rec.ram_gb == 16 and "Arc A770" in rec.gpu
    assert not p.needs_llm


def test_elden_ring_real_page():
    p = parse_pc_requirements(pc_req(1245620))
    mn = p.minimum.requirements
    assert mn.gpu == ["NVIDIA GEFORCE GTX 1060 3 GB", "AMD RADEON RX 580 4 GB"]
    assert mn.vram_gb == 3
    assert p.recommended.requirements.vram_gb == 8
    assert not p.needs_llm


def test_no_requirements_listed():
    p = parse_pc_requirements([])
    assert p.minimum is None and p.recommended is None


def test_plain_br_format_without_list():
    html = "<strong>Minimum:</strong><br>OS: Windows 7<br>Processor: Intel Core 2 Duo<br>Memory: 2048 MB RAM<br>Graphics: GeForce 8800 GT<br>Storage: 8 GB available space"
    t = parse_tier(html)
    assert t.requirements.ram_gb == 2 and t.requirements.storage_gb == 8
    assert t.requirements.cpu == ["Intel Core 2 Duo"] and not t.missing


def test_missing_fields_flag_llm_fallback():
    t = parse_tier(
        "<ul><li><strong>OS:</strong> Windows 10</li><li><strong>Memory:</strong> 8 GB RAM</li></ul>"
    )
    assert set(t.missing) == {"cpu", "gpu"}
    assert parse_pc_requirements(
        {"minimum": "<ul><li><strong>OS:</strong> Windows</li></ul>"}
    ).needs_llm


def test_combined_min_and_recommended_blob_is_split():
    blob = (
        "<strong>Minimum:</strong><ul><li><strong>Processor:</strong> i5</li><li><strong>Memory:</strong> 4 GB RAM</li><li><strong>Graphics:</strong> GTX 750</li></ul>"
        "<strong>Recommended:</strong><ul><li><strong>Processor:</strong> i7</li><li><strong>Memory:</strong> 8 GB RAM</li><li><strong>Graphics:</strong> GTX 1060</li></ul>"
    )
    p = parse_pc_requirements({"minimum": blob})
    assert p.minimum.requirements.ram_gb == 4 and p.recommended.requirements.ram_gb == 8


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GTX 1060 / RX 580", ["GTX 1060", "RX 580"]),
        (
            "Intel Core i5-8400 or AMD Ryzen 3 3300X or equivalent",
            ["Intel Core i5-8400", "AMD Ryzen 3 3300X"],
        ),
        ("Intel Core i5 (or equivalent)", ["Intel Core i5"]),
        ("NVIDIA GTX 970, AMD Radeon R9 290", ["NVIDIA GTX 970", "AMD Radeon R9 290"]),
        ("AMD Ryzen 5 3600/3600X", ["AMD Ryzen 5 3600/3600X"]),
        ("Intel Core i5-2500K 3.3GHz", ["Intel Core i5-2500K 3.3GHz"]),
        ("2.4 GHz or better", ["2.4 GHz"]),
    ],
)
def test_split_alternatives(raw, expected):
    assert split_alternatives(raw) == expected


@pytest.mark.parametrize(
    ("raw", "gb"),
    [
        ("12 GB RAM", 12),
        ("2048 MB RAM", 2),
        ("1 TB", 1024),
        ("8GB", 8),
        ("lots", None),
        ("4,5 GB", 4.5),
    ],
)
def test_parse_size(raw, gb):
    assert parse_size_gb(raw) == gb


def test_vram_ignores_implausible_values():
    assert vram_from_gpus(["GTX 1060 6GB", "RX 580 4 GB"]) == 4
    assert vram_from_gpus(["Some GPU 512GB"]) is None
