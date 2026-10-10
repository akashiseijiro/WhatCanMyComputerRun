"""LLM fallback for requirement text the deterministic parser could not fully read."""

from __future__ import annotations

from canirunit.llm.client import LLMClient
from canirunit.parsing.requirements_parser import ParsedPcRequirements, vram_from_gpus
from canirunit.parsing.schemas import LLMParsedRequirements, Requirements

SYSTEM = """You extract PC game system requirements into a strict schema.
Rules:
- Use only information present in the text. Never guess or fill in typical values.
- Use null (or an empty list) for anything not stated.
- cpu and gpu are lists: keep EVERY alternative the text lists
  (e.g. "GTX 1060 / RX 580" is two entries). Drop phrases like "or equivalent".
- ram_gb, vram_gb and storage_gb are numbers in gigabytes (convert MB and TB).
- directx is just the version number as text, e.g. "12".
- minimum and recommended are separate tiers; use null for a tier that is absent."""


def _merge(base: Requirements, extra: Requirements | None) -> Requirements:
    if extra is None:
        return base
    merged = base.model_copy()
    for name in ("cpu", "gpu"):
        if not getattr(merged, name):
            setattr(merged, name, getattr(extra, name))
    for name in ("ram_gb", "vram_gb", "storage_gb", "os", "directx", "notes"):
        if getattr(merged, name) is None:
            setattr(merged, name, getattr(extra, name))
    if merged.vram_gb is None:
        merged.vram_gb = vram_from_gpus(merged.gpu)
    return merged


class LLMRequirementsParser:
    def __init__(self, llm: LLMClient, model: str) -> None:
        self.llm = llm
        self.model = model

    async def fill_gaps(
        self, parsed: ParsedPcRequirements
    ) -> tuple[Requirements | None, Requirements | None]:
        """Return (minimum, recommended) with gaps filled; deterministic values always win."""
        sections = []
        for label, tier in (("MINIMUM", parsed.minimum), ("RECOMMENDED", parsed.recommended)):
            if tier is not None and tier.raw_text:
                sections.append(f"{label}:\n{tier.raw_text}")
        extra = await self.llm.parse(
            model=self.model,
            system=SYSTEM,
            user="\n\n".join(sections),
            schema=LLMParsedRequirements,
        )
        mn = _merge(parsed.minimum.requirements, extra.minimum) if parsed.minimum else None
        rec = (
            _merge(parsed.recommended.requirements, extra.recommended)
            if parsed.recommended
            else None
        )
        return mn, rec
