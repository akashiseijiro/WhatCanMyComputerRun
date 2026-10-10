from __future__ import annotations

from typing import Any

import httpx

from canirunit.parsing.schemas import GameDetails, Price, SearchResult
from canirunit.sources.cache import TTLCache

SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
DETAILS_URL = "https://store.steampowered.com/api/appdetails"
STORE_APP_URL = "https://store.steampowered.com/app/{appid}"
REQUEST_TIMEOUT = 15.0


class SteamError(Exception):
    code = "steam_error"


class SteamUnavailable(SteamError):
    code = "steam_unavailable"


class SteamRateLimited(SteamError):
    code = "steam_rate_limited"


class GameNotFound(SteamError):
    code = "game_not_found"


class SteamClient:
    def __init__(self, http: httpx.AsyncClient, cache: TTLCache) -> None:
        self.http = http
        self.cache = cache

    async def _get_json(self, url: str, params: dict[str, Any], cache_key: str) -> Any:
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            resp = await self.http.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except httpx.TimeoutException as exc:
            raise SteamUnavailable("Steam did not respond in time.") from exc
        except httpx.HTTPError as exc:
            raise SteamUnavailable(
                "Could not reach Steam. Check your internet connection."
            ) from exc
        if resp.status_code in (403, 429):
            raise SteamRateLimited("Steam is rate limiting requests. Try again in a minute.")
        if resp.status_code >= 400:
            raise SteamUnavailable(f"Steam returned HTTP {resp.status_code}.")
        try:
            data = resp.json()
        except ValueError as exc:
            raise SteamUnavailable("Steam returned an unreadable response.") from exc
        self.cache.set(cache_key, data)
        return data

    async def search(self, term: str) -> list[SearchResult]:
        term = term.strip()
        if not term:
            return []
        data = await self._get_json(
            SEARCH_URL,
            {"term": term, "l": "english", "cc": "US"},
            f"steam:search:{term.lower()}",
        )
        results: list[SearchResult] = []
        for item in data.get("items", []):
            if item.get("type") not in (None, "app"):
                continue
            price = item.get("price") or {}
            final = price.get("final")
            results.append(
                SearchResult(
                    appid=int(item["id"]),
                    name=str(item["name"]),
                    image=item.get("tiny_image"),
                    price=f"{final / 100:.2f} {price.get('currency', '')}".strip()
                    if isinstance(final, int)
                    else None,
                )
            )
        return results

    async def app_details(self, appid: int) -> tuple[GameDetails, Any]:
        """Return the game info plus the raw pc_requirements block (parsed elsewhere)."""
        data = await self._get_json(
            DETAILS_URL,
            {"appids": appid, "cc": "US", "l": "english"},
            f"steam:app:{appid}",
        )
        entry = data.get(str(appid)) if isinstance(data, dict) else None
        if not entry or not entry.get("success") or not entry.get("data"):
            raise GameNotFound(f"Steam has no store page data for app {appid}.")
        return parse_app_data(appid, entry["data"]), entry["data"].get("pc_requirements")


def parse_app_data(appid: int, d: dict[str, Any]) -> GameDetails:
    po = d.get("price_overview")
    price = (
        Price(
            currency=str(po.get("currency", "USD")),
            initial_cents=int(po.get("initial", 0)),
            final_cents=int(po.get("final", 0)),
            discount_percent=int(po.get("discount_percent", 0)),
            formatted=po.get("final_formatted") or None,
        )
        if isinstance(po, dict)
        else None
    )
    release = d.get("release_date") or {}
    platforms = d.get("platforms") or {}
    return GameDetails(
        appid=appid,
        name=str(d.get("name", f"App {appid}")),
        type=str(d.get("type", "game")),
        header_image=d.get("header_image"),
        store_url=STORE_APP_URL.format(appid=appid),
        is_free=bool(d.get("is_free", False)),
        price=price,
        release_date=release.get("date") or None,
        coming_soon=bool(release.get("coming_soon", False)),
        windows_supported=bool(platforms.get("windows", True)),
    )
