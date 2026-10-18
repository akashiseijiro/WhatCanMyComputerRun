"""Thin wrapper over the Anthropic SDK: one place for missing-key / rate-limit handling."""

from __future__ import annotations

from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from whatcanmycomputerrun.config import Settings

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    code = "llm_error"


class LLMUnavailable(LLMError):
    """No API key configured, or the API could not be reached."""

    code = "llm_unavailable"


class LLMRateLimited(LLMError):
    code = "llm_rate_limited"


class LLMClient:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self._client = client

    @property
    def available(self) -> bool:
        return self._client is not None or self.settings.has_api_key

    def _get(self) -> Any:
        if self._client is None:
            if not self.settings.has_api_key:
                raise LLMUnavailable(
                    "ANTHROPIC_API_KEY is not set. Add it to your .env file to enable AI features."
                )
            self._client = anthropic.AsyncAnthropic(api_key=self.settings.anthropic_api_key)
        return self._client

    async def parse(
        self, *, model: str, system: str, user: str, schema: type[T], max_tokens: int = 2048
    ) -> T:
        """Ask for output matching a Pydantic schema (validated by the SDK)."""
        client = self._get()
        try:
            response = await client.messages.parse(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
            )
        except anthropic.AuthenticationError as exc:
            raise LLMUnavailable("The Anthropic API key was rejected.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMRateLimited("The Anthropic API is rate limiting requests.") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailable("Could not reach the Anthropic API.") from exc
        except anthropic.APIError as exc:
            raise LLMError(f"Anthropic API error: {exc}") from exc
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError("The model returned no structured output (it may have refused).")
        if not isinstance(parsed, schema):
            raise LLMError("The model returned unexpected output.")
        return parsed
