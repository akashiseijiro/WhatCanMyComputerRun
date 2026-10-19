"""Thin wrapper over the Anthropic SDK: one place for missing-key / rate-limit handling."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
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


@contextmanager
def _translate_errors() -> Iterator[None]:
    try:
        yield
    except anthropic.AuthenticationError as exc:
        raise LLMUnavailable("The Anthropic API key was rejected.") from exc
    except anthropic.RateLimitError as exc:
        raise LLMRateLimited("The Anthropic API is rate limiting requests.") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMUnavailable("Could not reach the Anthropic API.") from exc
    except anthropic.APIError as exc:
        raise LLMError(f"Anthropic API error: {exc}") from exc


WEB_SEARCH_TOOL = "web_search_20250305"
MAX_CONTINUATIONS = 3


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
        with _translate_errors():
            response = await client.messages.parse(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
            )
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError("The model returned no structured output (it may have refused).")
        if not isinstance(parsed, schema):
            raise LLMError("The model returned unexpected output.")
        return parsed

    async def web_search(
        self, *, model: str, system: str, user: str, max_uses: int = 3, max_tokens: int = 2048
    ) -> tuple[str, list[str]]:
        """Run one web-search-enabled request. Returns (answer text, source URLs).

        Source URLs prefer the pages the answer actually cited; only http(s) URLs are kept.
        """
        client = self._get()
        tools = [{"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": max_uses}]
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        cited: dict[str, None] = {}
        found: dict[str, None] = {}
        errors: list[str] = []
        text = ""
        with _translate_errors():
            for _ in range(MAX_CONTINUATIONS + 1):
                resp = await client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    tools=tools,
                    messages=messages,
                )
                text = _collect(resp.content, cited, found, errors)
                if resp.stop_reason != "pause_turn":
                    break
                # Server-side loop paused: send the assistant turn back unchanged to resume.
                messages = [messages[0], {"role": "assistant", "content": resp.content}]
        if not text.strip() and errors:
            raise LLMUnavailable(f"Web search failed ({', '.join(sorted(set(errors)))}).")
        urls = list(cited) or list(found)[:5]
        return text, [u for u in urls if _is_http(u)][:6]


def _is_http(url: str) -> bool:
    return url.lower().startswith(("http://", "https://"))


def _collect(
    content: list[Any], cited: dict[str, None], found: dict[str, None], errors: list[str]
) -> str:
    """Gather the answer text and source URLs from one response's content blocks."""
    parts: list[str] = []
    for block in content:
        kind = getattr(block, "type", None)
        if kind == "text":
            parts.append(getattr(block, "text", "") or "")
            for cite in getattr(block, "citations", None) or []:
                url = getattr(cite, "url", None)
                if isinstance(url, str):
                    cited.setdefault(url)
        elif kind == "web_search_tool_result":
            result = getattr(block, "content", None)
            if isinstance(result, list):
                for item in result:
                    url = getattr(item, "url", None)
                    if isinstance(url, str):
                        found.setdefault(url)
            else:
                code = getattr(result, "error_code", None)
                if code:
                    errors.append(str(code))
    return "".join(parts)
