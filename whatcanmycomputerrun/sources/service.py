from __future__ import annotations

import contextlib

import httpx

from whatcanmycomputerrun.config import Settings
from whatcanmycomputerrun.llm.client import LLMClient, LLMError, LLMUnavailable
from whatcanmycomputerrun.parsing.llm_parser import LLMRequirementsParser
from whatcanmycomputerrun.parsing.requirements_parser import (
    ParsedPcRequirements,
    parse_pc_requirements,
)
from whatcanmycomputerrun.parsing.schemas import GameDetails, RequirementsSet, SearchResult
from whatcanmycomputerrun.sources.cache import TTLCache
from whatcanmycomputerrun.sources.custom_requirements import (
    MAX_TEXT_CHARS,
    CustomRequirementsError,
    extract_requirements_text,
    fetch_page,
    looks_like_requirements,
)
from whatcanmycomputerrun.sources.steam import GameNotFound, SteamClient
from whatcanmycomputerrun.sources.web_fallback import (
    WebRequirementsFinder,
    WebRequirementsNotFound,
)


class GameService:
    """Steam lookup + requirement parsing (deterministic first, LLM for gaps)."""

    def __init__(
        self,
        steam: SteamClient,
        llm_parser: LLMRequirementsParser | None,
        web: WebRequirementsFinder | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.steam = steam
        self.llm_parser = llm_parser
        self.web = web
        self.http = http

    @classmethod
    def create(cls, settings: Settings, http: httpx.AsyncClient) -> GameService:
        cache = TTLCache(settings.cache_dir, settings.whatcanmycomputerrun_cache_ttl_hours)
        llm = LLMClient(settings)
        parser = LLMRequirementsParser(llm, settings.parser_model)
        finder = WebRequirementsFinder(llm, settings.search_model, cache)
        return cls(SteamClient(http, cache), parser, finder, http)

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

    async def custom_game(
        self,
        name: str,
        *,
        url: str | None = None,
        text: str | None = None,
        appid: int | None = None,
    ) -> GameDetails:
        """Requirements from a page the user linked to, or text they pasted.

        Needs only the plain LLM parser (no web-search tool), so it works on a free AI key.
        """
        if self.llm_parser is None or not self.llm_parser.llm.available:
            raise LLMUnavailable("Reading requirements needs an AI key (see your .env file).")
        source_urls: list[str] = []
        if url and url.strip():
            if self.http is None:
                raise CustomRequirementsError("Fetching links is not configured.")
            page = extract_requirements_text(await fetch_page(self.http, url))
            if not looks_like_requirements(page):
                raise CustomRequirementsError(
                    "That page doesn't seem to list system requirements (some sites load them "
                    "with JavaScript). Open the page, copy the requirements and paste them."
                )
            text, source_urls = page, [url.strip()]
        elif text and text.strip():
            text = text.strip()[:MAX_TEXT_CHARS]
        else:
            raise CustomRequirementsError("Paste the requirements text or a link to the page.")

        details = GameDetails(name=name.strip())
        if appid:
            with contextlib.suppress(GameNotFound):
                details, _ = await self.steam.app_details(appid)
        try:
            mn, rec = await self.llm_parser.parse_text(details.name, text)
        except LLMError as exc:
            raise CustomRequirementsError(f"Could not read the requirements: {exc}") from exc
        if mn is None and rec is None:
            raise CustomRequirementsError(
                "No system requirements were found in that text. Include the Minimum and "
                "Recommended lines (processor, graphics, memory, storage)."
            )
        what = "a page you linked to" if source_urls else "text you pasted"
        details.requirements = RequirementsSet(
            minimum=mn,
            recommended=rec,
            source="user_provided",
            parse_method="llm",
            source_urls=source_urls,
            warnings=[
                f"Requirements were read by AI from {what}, not from a store listing. "
                "Check the result against the original."
            ],
        )
        details.requirements_status = "ok"
        return details

    async def web_game(self, name: str, appid: int | None = None) -> GameDetails:
        """Requirements for a game found by web search (not on Steam, or Steam lists none).

        With an appid, the Steam store details (image, price, release date) are kept.
        """
        if self.web is None:
            raise WebRequirementsNotFound("Web lookup is not configured.")
        details = GameDetails(name=name.strip())
        if appid:
            with contextlib.suppress(GameNotFound):
                details, _ = await self.steam.app_details(appid)
        found = await self.web.find(details.name)
        parsed, urls = found.parsed, found.urls
        req = RequirementsSet(
            minimum=parsed.minimum.requirements if parsed.minimum else None,
            recommended=parsed.recommended.requirements if parsed.recommended else None,
            source="web_search",
            parse_method="llm",
            source_urls=urls,
            warnings=[
                "Requirements came from an AI web search, not a store listing. "
                "Double-check them on the publisher's official page."
            ],
        )
        if found.unofficial or not urls:
            req.warnings.append(
                "Only unofficial or unidentified sources were found, so these numbers are less "
                "trustworthy."
                if urls
                else "No source pages were reported, so these numbers can't be checked."
            )
        if parsed.needs_llm:
            req = await self._fill_with_llm(parsed, req)
            req.parse_method = "llm"
        details.requirements = req
        details.requirements_status = "ok"
        return details
