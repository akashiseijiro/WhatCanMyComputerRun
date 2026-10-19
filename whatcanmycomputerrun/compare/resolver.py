"""Maps CPU/GPU names to relative performance scores on one consistent benchmark scale."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel

from whatcanmycomputerrun.compare.models import Confidence, PerformanceScore
from whatcanmycomputerrun.compare.normalize import (
    GENERIC_IGPU,
    igpu_from_cpu,
    normalize_cpu,
    normalize_gpu,
)
from whatcanmycomputerrun.llm.client import LLMClient, LLMError
from whatcanmycomputerrun.sources.cache import TTLCache

GPU_BENCHMARK = "PassMark G3D Mark"
CPU_BENCHMARK = "PassMark CPU Mark"
SCORE_CACHE_TTL_HOURS = 24 * 30
SCORE_BOUNDS = {"gpu": (200.0, 80000.0), "cpu": (500.0, 150000.0)}
IGPU_NAME = re.compile(
    r"radeon \d{3}m\b|radeon graphics|\buhd\b|\biris\b|(?<!rx )vega (?!56\b|64\b)\d{1,2}\b|intel hd|\bxe graphics",
    re.I,
)
IGPU_MAX_SCORE = 12000.0


def plausible(kind: str, normalized: str, score: float | None) -> bool:
    """Reject numbers no real part could have (the model sometimes hallucinates scale)."""
    if score is None:
        return False
    lo, hi = SCORE_BOUNDS[kind]
    if not lo <= score <= hi:
        return False
    return not (kind == "gpu" and IGPU_NAME.search(normalized) and score > IGPU_MAX_SCORE)


@dataclass(frozen=True)
class ComponentQuery:
    kind: Literal["cpu", "gpu"]
    name: str
    hint: str | None = None  # e.g. the CPU model, to identify a generic iGPU name

    @property
    def normalized(self) -> str:
        norm = normalize_gpu(self.name) if self.kind == "gpu" else normalize_cpu(self.name)
        if self.kind == "gpu":
            alias = igpu_from_cpu(norm, self.hint)
            if alias:
                return alias
        return norm

    @property
    def key(self) -> str:
        norm = self.normalized
        if self.kind == "gpu" and norm in GENERIC_IGPU and self.hint:
            return f"gpu:{norm}@{normalize_cpu(self.hint)}"
        return f"{self.kind}:{norm}"


@dataclass
class ResolveResult:
    scores: dict[str, PerformanceScore] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def get(self, q: ComponentQuery) -> PerformanceScore | None:
        s = self.scores.get(q.key)
        return s if s is not None and s.score is not None else None


class PerformanceResolver(Protocol):
    """Swap implementations (Claude, a benchmark API, a static table) behind this."""

    async def resolve(self, queries: list[ComponentQuery]) -> ResolveResult: ...


class StaticResolver:
    """Dict-backed resolver for tests and offline demos: {"gpu:radeon 780m": 2200.0}."""

    def __init__(self, scores: dict[str, float], confidence: Confidence = Confidence.HIGH) -> None:
        self.scores = scores
        self.confidence = confidence

    async def resolve(self, queries: list[ComponentQuery]) -> ResolveResult:
        out = ResolveResult()
        for q in queries:
            value = self.scores.get(q.key)
            if value is not None:
                bench = GPU_BENCHMARK if q.kind == "gpu" else CPU_BENCHMARK
                out.scores[q.key] = PerformanceScore(
                    score=value, benchmark=bench, confidence=self.confidence, matched_name=q.name
                )
        return out


class LLMComponentScore(BaseModel):
    id: int
    matched_name: str | None = None
    score: float | None = None
    confidence: Confidence = Confidence.LOW
    notes: str | None = None


class LLMScoreBatch(BaseModel):
    results: list[LLMComponentScore]


SYSTEM = f"""You convert PC component names into relative performance scores.
Scales (use exactly these, so scores are comparable across calls):
- GPUs: {GPU_BENCHMARK} (the "average G3D Mark" shown on videocardbenchmark.net).
- CPUs: {CPU_BENCHMARK} (the "average CPU Mark" shown on cpubenchmark.net).
Calibration anchors (approximate averages; keep your answers consistent with them):
- GPU G3D, newer: RTX 4090 ~38000, RTX 3060 ~17000, RTX 2060 SUPER ~16000, RX 5700 XT ~17000,
  GTX 1660 ~11000, GTX 1060 6GB ~10000, RX 580 ~9500, RX 480 ~9000, RX 570 ~8300, GTX 1650 ~7800,
  Arc A380 ~6000, GTX 1050 Ti ~6000, GTX 1050 ~5000, GT 1030 ~2500.
- GPU G3D, older (games often list these as minimum specs; they are MUCH slower than a GTX 1060):
  GTX 980 ~9500, GTX 970 ~8500, GTX 960 ~5000, GTX 950 ~4300, GTX 780 ~5200, GTX 770 ~4500,
  GTX 760 ~3700, GTX 750 Ti ~3800, GTX 660 ~3000, GTX 650 ~1500, Radeon R9 290 ~6500,
  R9 380 ~5000, R9 270 ~4600, R7 370 ~4500, R7 260X ~3500, R7 250 ~1300, RX 560 ~4000,
  RX 470 ~7600, RX 460 ~4400.
- Integrated GPUs (user-verified equivalences, treat as ground truth): Radeon 780M ~7500
  (equal to a desktop GTX 1650 and a laptop RTX 2050 ~7500), Radeon 680M ~5500,
  Radeon 890M ~9500, Radeon 760M ~5500, Radeon 740M ~3500, Radeon Vega 8 ~2000,
  Intel Iris Xe ~2500, Intel UHD 620 ~1000.
- CPU Mark, newer: Ryzen 9 7950X3D ~62000, Ryzen 7 7800X3D ~35000, Core i7-12700 ~30000,
  Ryzen 5 5600X ~22000, Ryzen Z1 Extreme ~20000, Core i3-1115G4 ~7000, Ryzen 5 1600 ~12000,
  Core i5-8400 ~9500, Core i7-6700 ~9000, Ryzen 3 1200 ~6000.
- CPU Mark, older (often listed as minimum specs): Core i7-4790K ~10000, Core i7-4770 ~8000,
  Core i5-6600K ~7000, Core i5-4690K ~6500, Core i5-4430 ~5200, Core i5-3470 ~4800,
  Core i5-2500K ~4800, AMD FX-8350 ~6500, FX-6300 ~4800, Core i3-540 ~1800.
- Integrated GPUs are slower than mid-range discrete cards; an iGPU never scores above ~12000.
Rules:
- Mobile/laptop variants are different parts from desktop ones (RTX 3060 Laptop vs RTX 3060). Use the variant named.
- For integrated GPUs, a "hint" gives the CPU the GPU is built into; use it to identify the exact iGPU (e.g. generic "AMD Radeon Graphics" in a Ryzen Z1 Extreme is the Radeon 780M).
- Names may include a VRAM size or vendor prefix; ignore those when identifying the part.
- If you recall the benchmark value only approximately, still give your best estimate but set confidence to "medium" or "low". Use "high" only when you are sure of the part and its approximate score.
- If a name is too generic to identify one part (e.g. "Intel Core i5", "Quad core CPU"), set score to null.
- Never invent a part. If you do not know it, score is null.
Return one result per input id."""


class ClaudeResolver:
    def __init__(self, llm: LLMClient, model: str, cache: TTLCache) -> None:
        self.llm = llm
        self.model = model
        self.cache = cache

    def _cache_key(self, q: ComponentQuery) -> str:
        return f"perf:v4:{self.model}:{q.key}"

    async def resolve(self, queries: list[ComponentQuery]) -> ResolveResult:
        out = ResolveResult()
        pending: dict[str, ComponentQuery] = {}
        for q in queries:
            if q.key in out.scores or q.key in pending:
                continue
            cached = self.cache.get(self._cache_key(q), SCORE_CACHE_TTL_HOURS)
            if cached is not None:
                out.scores[q.key] = PerformanceScore.model_validate(cached)
            else:
                pending[q.key] = q
        if not pending:
            return out
        if not self.llm.available:
            out.warnings.append(
                "No ANTHROPIC_API_KEY is set, so CPU/GPU performance could not be compared. "
                "Add one to your .env file."
            )
            return out

        items = list(pending.values())
        for _attempt in range(2):  # the model sometimes skips items in a big batch; retry once
            if not items:
                break
            try:
                await self._score_batch(items, out)
            except LLMError as exc:
                out.warnings.append(f"Performance lookup failed: {exc}")
                break
            items = [q for q in items if out.get(q) is None]
        return out

    async def _score_batch(self, items: list[ComponentQuery], out: ResolveResult) -> None:
        lines = []
        for i, q in enumerate(items):
            hint = f' | hint: built into "{q.hint}"' if q.hint and q.kind == "gpu" else ""
            lines.append(f'{i}. {q.kind.upper()}: "{q.name}"{hint}')
        batch = await self.llm.parse(
            model=self.model,
            system=SYSTEM,
            user="\n".join(lines),
            schema=LLMScoreBatch,
            max_tokens=4096,
        )
        for r in batch.results:
            if not 0 <= r.id < len(items):
                continue
            q = items[r.id]
            bench = GPU_BENCHMARK if q.kind == "gpu" else CPU_BENCHMARK
            score = r.score if plausible(q.kind, q.normalized, r.score) else None
            result = PerformanceScore(
                score=score,
                benchmark=bench,
                confidence=r.confidence if score is not None else Confidence.LOW,
                matched_name=r.matched_name,
                notes=r.notes,
            )
            out.scores[q.key] = result
            if score is not None:  # never cache a failed lookup
                self.cache.set(self._cache_key(q), result.model_dump(mode="json"))
