"""Gemini backend for LLMClient (plain REST via httpx, so no extra dependency).

Structured output uses generationConfig.responseJsonSchema. Web search uses Google Search
grounding, which Google does not offer on the free tier (it answers 429), so web_search then
raises LLMUnavailable with an explanation instead of a generic rate-limit error.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from whatcanmycomputerrun.llm.client import LLMError, LLMRateLimited, LLMUnavailable

T = TypeVar("T", bound=BaseModel)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
TIMEOUT_S = 60.0
MIN_OUTPUT_TOKENS = 8192  # thinking tokens count against the limit; truncated JSON is useless


class GeminiBackend:
    def __init__(self, api_key: str, model: str, http: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self._http = http

    async def _generate(self, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{BASE_URL}/models/{self.model}:generateContent"
        headers = {"x-goog-api-key": self.api_key, "content-type": "application/json"}
        try:
            if self._http is not None:
                resp = await self._http.post(url, headers=headers, json=body, timeout=TIMEOUT_S)
            else:
                async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
                    resp = await http.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise LLMUnavailable("The Gemini API took too long to answer.") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable("Could not reach the Gemini API.") from exc
        if resp.status_code == 200:
            data = resp.json()
            return data if isinstance(data, dict) else {}
        message = _error_message(resp)
        if resp.status_code == 429:
            raise LLMRateLimited(f"The Gemini API is rate limiting requests ({message}).")
        if resp.status_code in (400, 401, 403) and "API key" in message:
            raise LLMUnavailable("The Gemini API key was rejected.")
        raise LLMError(f"Gemini API error {resp.status_code}: {message}")

    async def parse(self, *, system: str, user: str, schema: type[T], max_tokens: int = 2048) -> T:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": schema.model_json_schema(),
                "maxOutputTokens": max(max_tokens, MIN_OUTPUT_TOKENS),
            },
        }
        data = await self._generate(body)
        text, _ = _text_and_sources(data)
        if not text.strip():
            raise LLMError("The model returned no structured output (it may have refused).")
        try:
            return schema.model_validate(json.loads(text))
        except (ValueError, ValidationError) as exc:
            raise LLMError(
                "The model returned output that did not match the expected shape."
            ) from exc

    async def web_search(
        self, *, system: str, user: str, max_tokens: int = 2048
    ) -> tuple[str, list[str]]:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"maxOutputTokens": max(max_tokens, MIN_OUTPUT_TOKENS)},
        }
        try:
            data = await self._generate(body)
        except LLMRateLimited as exc:
            raise LLMUnavailable(
                "Web search for non-Steam games needs Google Search grounding, which the free "
                "Gemini tier does not include. Use a Steam game, or set ANTHROPIC_API_KEY."
            ) from exc
        text, urls = _text_and_sources(data)
        if not text.strip():
            raise LLMUnavailable("Web search returned no answer.")
        return text, urls[:6]


def _error_message(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("error", {}).get("message", resp.text))[:200]
    except ValueError:
        return resp.text[:200]


def _text_and_sources(data: dict[str, Any]) -> tuple[str, list[str]]:
    """Answer text (thought parts excluded) and the http(s) pages Google grounded it on."""
    candidates = data.get("candidates") or []
    if not candidates:
        return "", []
    cand = candidates[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    urls: dict[str, None] = {}
    for chunk in (cand.get("groundingMetadata") or {}).get("groundingChunks") or []:
        uri = (chunk.get("web") or {}).get("uri")
        if isinstance(uri, str) and uri.lower().startswith(("http://", "https://")):
            urls.setdefault(uri)
    return text, list(urls)
