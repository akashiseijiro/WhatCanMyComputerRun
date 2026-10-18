"""Optional game-specific tips from the LLM. Never required, never blocks a report."""

from __future__ import annotations

from pydantic import BaseModel

from whatcanmycomputerrun.llm.client import LLMClient, LLMError
from whatcanmycomputerrun.settings.models import GameTip, SettingsRecommendation
from whatcanmycomputerrun.sources.cache import TTLCache

TIPS_CACHE_TTL_HOURS = 24 * 30

SYSTEM = """You give PC graphics-settings advice for one specific game.
Rules:
- Name concrete in-game settings (e.g. "Ray tracing", "Crowd density", "Texture quality").
- Say which settings cost the most performance in THIS game and which can be raised cheaply.
- Only include tips you are confident are true for this game. If you are not sure the game
  has a setting, do not mention it. If you don't know the game well, return an empty list.
- Do not give FPS numbers. Do not mention upscalers (DLSS/FSR/XeSS), frame generation or
  generic advice like lowering the preset; those are handled elsewhere.
- Only name features the stated GPU actually supports.
- At most 5 tips, each one or two sentences."""


class _Tips(BaseModel):
    tips: list[GameTip]


class GameTipsProvider:
    def __init__(self, llm: LLMClient, model: str, cache: TTLCache) -> None:
        self.llm = llm
        self.model = model
        self.cache = cache

    async def tips(
        self, appid: int, game_name: str, rec: SettingsRecommendation, device: str, gpu: str
    ) -> tuple[list[GameTip], str | None]:
        """Return (tips, warning). A failure yields no tips and a warning, never an exception."""
        if rec.preset is None:
            return [], None
        key = f"tips:v1:{self.model}:{appid}:{rec.preset.value}:{device}"
        cached = self.cache.get(key, TIPS_CACHE_TTL_HOURS)
        if cached is not None:
            return [GameTip.model_validate(t) for t in cached], None
        if not self.llm.available:
            return [], "Game-specific tips need an ANTHROPIC_API_KEY."
        user = (
            f"Game: {game_name}\nDevice type: {device}\nGPU: {gpu}\n"
            f"Planned preset: {rec.preset.value} at {rec.render_resolution}"
        )
        try:
            out = await self.llm.parse(
                model=self.model, system=SYSTEM, user=user, schema=_Tips, max_tokens=1024
            )
        except LLMError as exc:
            return [], f"Game-specific tips unavailable: {exc}"
        tips = out.tips[:5]
        self.cache.set(key, [t.model_dump() for t in tips])
        return tips, None
