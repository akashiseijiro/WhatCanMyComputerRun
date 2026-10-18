"""Normalize CPU/GPU names so equal parts map to equal cache keys and resolver queries."""

from __future__ import annotations

import re

_TRADEMARKS = re.compile(r"\((?:R|TM|C)\)|[®™]", re.I)
_VENDORS = re.compile(
    r"\b(?:nvidia|amd|advanced micro devices,?(?: inc\.?)?|corporation|ati)\b", re.I
)
_GPU_NOISE = re.compile(
    r"\b(?:laptop gpu|notebook|with max-q design|max-q|mobile|graphics card|video card)\b", re.I
)
_MEMORY = re.compile(r"\(?\b\d+(?:\.\d+)?\s*(?:gb|mb)\b\)?(?:\s*(?:vram|gddr\d\w*))?", re.I)
_CPU_NOISE = re.compile(
    r"@\s*[\d.]+\s*ghz|\b\d+-core\b|\bprocessor\b|\bcpu\b|\bwith radeon graphics\b|"
    r"\b\d+(?:\.\d+)?\s*ghz\b",
    re.I,
)


def _clean(text: str) -> str:
    text = _TRADEMARKS.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip(" ,-/").lower()


_LAPTOP_WORD = re.compile(r"laptop|notebook|mobile|max-q", re.I)


def normalize_gpu(name: str) -> str:
    """Canonical GPU name; laptop variants keep a " laptop" tag (different, slower parts)."""
    text = _TRADEMARKS.sub(" ", name)
    text = _GPU_NOISE.sub(" ", text)
    text = _MEMORY.sub(" ", text)
    text = _VENDORS.sub(" ", text)
    norm = _clean(text)
    if _LAPTOP_WORD.search(name) and not re.search(r"\b\d{3,4}m\b", norm):
        norm += " laptop"
    return norm


def normalize_cpu(name: str) -> str:
    text = _TRADEMARKS.sub(" ", name)
    text = _CPU_NOISE.sub(" ", text)
    text = re.sub(r"\bintel\b|\bamd\b", " ", text, flags=re.I)
    return _clean(text)


def is_mobile_gpu(name: str) -> bool:
    return bool(re.search(r"laptop|notebook|mobile|max-q|\b\d{3,4}m\b", name, re.I))


def is_mobile_cpu(name: str) -> bool:
    return bool(
        re.search(r"\b[iI][3579]-\d{4,5}(?:U|P|H|HS|HX|G\d)\b|\bryzen\b.*\d(?:U|HS|HX|H)\b", name)
    )


GENERIC_IGPU = {"radeon graphics", "graphics", "radeon"}

# CPU pattern -> the integrated GPU it contains. Extend as new APUs ship.
# Used when Windows reports only "AMD Radeon Graphics" (no model number).
IGPU_BY_CPU: tuple[tuple[str, str], ...] = (
    (r"z2 extreme", "radeon 890m"),
    (r"z1 extreme", "radeon 780m"),
    (r"ryzen ai 9 hx 3\d\d|ryzen ai 9 3\d\d", "radeon 890m"),
    (r"ryzen ai 7 350|ryzen ai 5 340", "radeon 860m"),
    (r"ryzen \d 78[4-9]0|ryzen \d 79[4-9]\d|ryzen \d 88[4-9]0|ryzen \d 89[4-9]\d", "radeon 780m"),
    (r"ryzen 5 7[56]40|ryzen 5 8[56]40", "radeon 760m"),
    (r"ryzen [579] 6[6-9]\d0", "radeon 680m"),
    (r"ryzen 5 66\d0", "radeon 660m"),
    (r"\bz1\b", "radeon 740m"),
)


def igpu_from_cpu(gpu_norm: str, cpu_name: str | None) -> str | None:
    """Resolve a generic iGPU name using the CPU model; None if it can't be determined."""
    if gpu_norm not in GENERIC_IGPU or not cpu_name:
        return None
    cpu = normalize_cpu(cpu_name)
    for pattern, igpu in IGPU_BY_CPU:
        if re.search(pattern, cpu):
            return igpu
    return None
