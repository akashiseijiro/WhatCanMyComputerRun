from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from whatcanmycomputerrun import __version__
from whatcanmycomputerrun.compare.engine import build_report
from whatcanmycomputerrun.compare.models import Report
from whatcanmycomputerrun.compare.resolver import ClaudeResolver, PerformanceResolver
from whatcanmycomputerrun.config import Settings, get_settings
from whatcanmycomputerrun.hardware.base import HardwareDetector, HardwareProfile
from whatcanmycomputerrun.hardware.catalog import (
    CatalogError,
    ManualSelection,
    build_manual_profile,
    load_catalog,
)
from whatcanmycomputerrun.llm.client import LLMClient, LLMError
from whatcanmycomputerrun.parsing.schemas import GameDetails, SearchResult
from whatcanmycomputerrun.resources import resource_dir
from whatcanmycomputerrun.settings.llm_tips import GameTipsProvider
from whatcanmycomputerrun.settings.models import GameTip
from whatcanmycomputerrun.settings.rules import recommend_settings
from whatcanmycomputerrun.sources.cache import TTLCache
from whatcanmycomputerrun.sources.service import GameService
from whatcanmycomputerrun.sources.steam import GameNotFound, SteamError, SteamRateLimited
from whatcanmycomputerrun.sources.web_fallback import WebRequirementsNotFound


class TipsResponse(BaseModel):
    tips: list[GameTip]
    warning: str | None = None


def create_app(
    detector: HardwareDetector,
    settings: Settings | None = None,
    games: GameService | None = None,
    resolver: PerformanceResolver | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    http_holder: dict[str, httpx.AsyncClient] = {}
    service_holder_r: dict[str, PerformanceResolver] = {}
    service_holder: dict[str, GameService] = {"svc": games} if games else {}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if "http" in http_holder:
            await http_holder["http"].aclose()

    def get_games() -> GameService:
        if "svc" not in service_holder:
            http_holder["http"] = httpx.AsyncClient(follow_redirects=True)
            service_holder["svc"] = GameService.create(settings, http_holder["http"])
        return service_holder["svc"]

    def get_resolver() -> PerformanceResolver:
        if resolver is not None:
            return resolver
        if "resolver" not in service_holder_r:
            cache = TTLCache(settings.cache_dir, settings.whatcanmycomputerrun_cache_ttl_hours)
            service_holder_r["resolver"] = ClaudeResolver(
                LLMClient(settings), settings.whatcanmycomputerrun_resolver_model, cache
            )
        return service_holder_r["resolver"]

    app = FastAPI(title="WhatCanMyComputerRun", version=__version__, lifespan=lifespan)
    state: dict[str, HardwareProfile] = {}

    @app.exception_handler(SteamError)
    async def steam_error(_: Request, exc: SteamError) -> JSONResponse:
        status = (
            404
            if isinstance(exc, GameNotFound)
            else 429
            if isinstance(exc, SteamRateLimited)
            else 503
        )
        return JSONResponse({"code": exc.code, "detail": str(exc)}, status_code=status)

    @app.exception_handler(WebRequirementsNotFound)
    async def web_not_found(_: Request, exc: WebRequirementsNotFound) -> JSONResponse:
        return JSONResponse({"code": exc.code, "detail": str(exc)}, status_code=404)

    @app.exception_handler(LLMError)
    async def llm_error(_: Request, exc: LLMError) -> JSONResponse:
        status = 429 if exc.code == "llm_rate_limited" else 503
        return JSONResponse({"code": exc.code, "detail": str(exc)}, status_code=status)

    def scan() -> HardwareProfile:
        try:
            profile = detector.detect()
        except Exception as exc:  # detection failure must surface as a clean API error
            raise HTTPException(status_code=500, detail=f"Hardware scan failed: {exc}") from exc
        state["hw"] = profile
        return profile

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {"ok": True, "version": __version__, "has_api_key": settings.has_api_key}

    @app.get("/api/hardware")
    def hardware() -> HardwareProfile:
        return state.get("hw") or scan()

    @app.post("/api/hardware/rescan")
    def rescan() -> HardwareProfile:
        return scan()

    @app.get("/api/hardware/catalog")
    def catalog() -> dict[str, Any]:
        return load_catalog()

    @app.post("/api/hardware/manual")
    def manual_hardware(selection: ManualSelection) -> HardwareProfile:
        try:
            profile = build_manual_profile(selection)
        except CatalogError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        state["hw"] = profile
        return profile

    @app.get("/api/search")
    async def search(q: str = Query(min_length=1, max_length=100)) -> list[SearchResult]:
        return await get_games().search(q)

    @app.get("/api/game/{appid}")
    async def game(appid: int) -> GameDetails:
        return await get_games().game(appid)

    @app.get("/api/report/{appid}")
    async def report(appid: int) -> Report:
        hw = state.get("hw") or scan()
        game = await get_games().game(appid)
        rep = await build_report(hw, game, get_resolver())
        rep.settings = recommend_settings(hw, rep)
        return rep

    @app.get("/api/web-report")
    async def web_report(
        name: str = Query(min_length=1, max_length=100), appid: int | None = None
    ) -> Report:
        hw = state.get("hw") or scan()
        game = await get_games().web_game(name, appid)
        rep = await build_report(hw, game, get_resolver())
        rep.settings = recommend_settings(hw, rep)
        return rep

    @app.get("/api/tips/{appid}")
    async def tips(appid: int) -> TipsResponse:
        hw = state.get("hw") or scan()
        game = await get_games().game(appid)
        rep = await build_report(hw, game, get_resolver())
        rec = recommend_settings(hw, rep)
        gpu = hw.primary_gpu
        provider = GameTipsProvider(
            LLMClient(settings),
            settings.whatcanmycomputerrun_tips_model,
            TTLCache(settings.cache_dir, settings.whatcanmycomputerrun_cache_ttl_hours),
        )
        items, warning = await provider.tips(
            appid, game.name, rec, hw.device_type.value, gpu.name if gpu else "unknown"
        )
        return TipsResponse(tips=items, warning=warning)

    ui_dir = resource_dir("ui")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(ui_dir / "index.html")

    app.mount("/static", StaticFiles(directory=ui_dir), name="static")
    return app
