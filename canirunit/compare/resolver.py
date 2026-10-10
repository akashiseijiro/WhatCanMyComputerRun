"""Maps CPU/GPU names to relative performance scores on one consistent benchmark scale."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel

from canirunit.compare.models import Confidence, PerformanceScore
from canirunit.compare.normalize import (
    GENERIC_IGPU,
    igpu_from_cpu,
    normalize_cpu,
    normalize_gpu,
)
from canirunit.llm.client import LLMClient, LLMError
from canirunit.sources.cache import TTLCache

GPU_BENCHMARK = "PassMark G3D Mark"
CPU_BENCHMARK = "PassMark CPU Mark"
SCORE_CACHE_TTL_HOURS = 24 * 30


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
        return f"perf:v1:{self.model}:{q.key}"

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
        lines = []
        for i, q in enumerate(items):
            hint = f' | hint: built into "{q.hint}"' if q.hint and q.kind == "gpu" else ""
            lines.append(f'{i}. {q.kind.upper()}: "{q.name}"{hint}')
        try:
            batch = await self.llm.parse(
                model=self.model,
                system=SYSTEM,
                user="\n".join(lines),
                schema=LLMScoreBatch,
                max_tokens=4096,
            )
        except LLMError as exc:
            out.warnings.append(f"Performance lookup failed: {exc}")
            return out

        for r in batch.results:
            if not 0 <= r.id < len(items):
                continue
            q = items[r.id]
            bench = GPU_BENCHMARK if q.kind == "gpu" else CPU_BENCHMARK
            score = r.score if r.score is not None and r.score > 0 else None
            result = PerformanceScore(
                score=score,
                benchmark=bench,
                confidence=r.confidence if score is not None else Confidence.LOW,
                matched_name=r.matched_name,
                notes=r.notes,
            )
            out.scores[q.key] = result
            self.cache.set(self._cache_key(q), result.model_dump(mode="json"))
        return out
