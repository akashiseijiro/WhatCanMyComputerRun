from __future__ import annotations

import httpx

from canirunit.config import Settings
from canirunit.llm.client import LLMClient, LLMError
from canirunit.parsing.llm_parser import LLMRequirementsParser
from canirunit.parsing.requirements_parser import ParsedPcRequirements, parse_pc_requirements
from canirunit.parsing.schemas import GameDetails, RequirementsSet, SearchResult
from canirunit.sources.cache import TTLCache
from canirunit.sources.steam import SteamClient


class GameService:
    """Steam lookup + requirement parsing (deterministic first, LLM for gaps)."""

    def __init__(self, steam: SteamClient, llm_parser: LLMRequirementsParser | None) -> None:
        self.steam = steam
        self.llm_parser = llm_parser

    @classmethod
    def create(cls, settings: Settings, http: httpx.AsyncClient) -> GameService:
        cache = TTLCache(settings.cache_dir, settings.canirunit_cache_ttl_hours)
        llm = LLMClient(settings)
        parser = LLMRequirementsParser(llm, settings.canirunit_parser_model)
        return cls(SteamClient(http, cache), parser)

    async def search(self, term: str) -> list[SearchResult]:
        return await self.steam.search(term)

    async def game(self, appid: int) -> GameDetails:
        details, raw_req = await self.steam.app_details(appid)
        parsed = parse_pc_requirements(raw_req)
        if parsed.minimum is None and parsed.recommended is None:
            details.requirements_status = "missing"
            return details

        req = RequirementsSet(
            minimum=parsed.minimum.requirements if parsed.minimum else None,
            recommended=parsed.recommended.requirements if parsed.recommended else None,
        )
        if parsed.needs_llm:
            req = await self._fill_with_llm(parsed, req)
        details.requirements = req
        return details

    async def _fill_with_llm(
        self, parsed: ParsedPcRequirements, req: RequirementsSet
    ) -> RequirementsSet:
        if self.llm_parser is None or not self.llm_parser.llm.available:
            req.warnings.append(
                "Some requirement fields could not be read and no ANTHROPIC_API_KEY is set "
                "to fill them in; those rows will show as unknown."
            )
            return req
        try:
            mn, rec = await self.llm_parser.fill_gaps(parsed)
        except LLMError as exc:
            req.warnings.append(f"AI parsing of incomplete requirements failed: {exc}")
            return req
        req.minimum, req.recommended = mn, rec
        req.parse_method = "mixed"
        return req
