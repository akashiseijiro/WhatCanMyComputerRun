"""Static PassMark score table, consulted before the AI resolver.

Parts found here get an exact, reproducible score (high confidence); everything else (older
parts, integrated GPUs, anything unusual) falls through to the wrapped resolver.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from whatcanmycomputerrun.compare.models import Confidence, PerformanceScore
from whatcanmycomputerrun.compare.normalize import normalize_cpu, normalize_gpu
from whatcanmycomputerrun.compare.passmark_data import CPU_DATA, GPU_DATA, PASSMARK_SNAPSHOT
from whatcanmycomputerrun.compare.resolver import (
    CPU_BENCHMARK,
    GPU_BENCHMARK,
    ComponentQuery,
    PerformanceResolver,
    ResolveResult,
)

_GEN_PREFIX = re.compile(r"\b\d{1,2}(?:st|nd|rd|th) gen\b")
_INTEL_I_SPACED = re.compile(r"\b(i[3579])[ -](\d{4,5}\w*)")
_GPU_PREFIX = re.compile(r"^(?:geforce|radeon|intel)\s+")


def gpu_key(name: str) -> str:
    """Lookup key: normalized name minus brand prefix, so "GTX 1060" == "GeForce GTX 1060"."""
    return _strip_prefix(normalize_gpu(name))


def _strip_prefix(normalized: str) -> str:
    return re.sub(r"\s+graphics$", "", _GPU_PREFIX.sub("", normalized))


def cpu_key(name: str) -> str:
    """Lookup key: tolerates "11th Gen ... Core i7-11800H", "Core i5 10400" and "i5-10400"."""
    text = _GEN_PREFIX.sub(" ", normalize_cpu(name).lower())
    text = re.sub(r"\bcore (?=i[3579]\b|i[3579]-)", "", text)
    text = _INTEL_I_SPACED.sub(r"\1-\2", text)
    return re.sub(r"^core\s+(?=i[3579]-)", "", re.sub(r"\s+", " ", text)).strip()


def _parse(data: str, key_fn: Callable[[str], str]) -> dict[str, tuple[str, float]]:
    table: dict[str, tuple[str, float]] = {}
    for line in data.strip().splitlines():
        name, _, score = line.rpartition("|")
        key = key_fn(name.strip())
        table.setdefault(key, (name.strip(), float(score)))  # first listing wins
    return table


GPU_TABLE = _parse(GPU_DATA, gpu_key)
CPU_TABLE = _parse(CPU_DATA, cpu_key)


def lookup(q: ComponentQuery) -> PerformanceScore | None:
    if q.kind == "gpu":
        hit, bench, key = (
            GPU_TABLE.get(_strip_prefix(q.normalized)),
            GPU_BENCHMARK,
            _strip_prefix(q.normalized),
        )
    else:
        hit, bench, key = CPU_TABLE.get(cpu_key(q.normalized)), CPU_BENCHMARK, cpu_key(q.normalized)
    if hit is None:
        return None
    matched, score = hit
    return PerformanceScore(
        score=score,
        benchmark=bench,
        confidence=Confidence.HIGH,
        matched_name=matched,
        notes=f"PassMark average ({PASSMARK_SNAPSHOT}), matched as '{key}'",
    )


class StaticTableResolver:
    """Answers from the PassMark table first; unknown parts go to `fallback` (if any)."""

    def __init__(self, fallback: PerformanceResolver | None = None) -> None:
        self.fallback = fallback

    async def resolve(self, queries: list[ComponentQuery]) -> ResolveResult:
        out = ResolveResult()
        rest: list[ComponentQuery] = []
        for q in queries:
            hit = lookup(q)
            if hit is not None:
                out.scores[q.key] = hit
            else:
                rest.append(q)
        if rest and self.fallback is not None:
            sub = await self.fallback.resolve(rest)
            out.scores.update(sub.scores)
            out.warnings.extend(sub.warnings)
        return out
