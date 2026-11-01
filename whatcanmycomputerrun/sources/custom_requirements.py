"""Requirements the user supplies for a non-Steam game: a link to a page, or pasted text.

Works without any web-search tool, so it also works on a free AI key. The text (a fetched page or
whatever was pasted) goes to the LLM parser, which only extracts what is written there.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

MAX_PAGE_BYTES = 2_000_000
MAX_TEXT_CHARS = 12_000
MAX_REDIRECTS = 3
FETCH_TIMEOUT_S = 15.0
USER_AGENT = "Mozilla/5.0 (compatible; WhatCanMyComputerRun/0.1)"
_KEYWORDS = re.compile(
    r"minimum|recommended|processor|graphics|\bgpu\b|\bcpu\b|memory|\bram\b|directx", re.I
)
_ANCHOR = re.compile(r"system requirements|minimum|recommended", re.I)


class CustomRequirementsError(Exception):
    code = "custom_requirements_failed"


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def check_public_url(url: str) -> None:
    """Allow only http(s) URLs that resolve to public addresses (no localhost/LAN)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise CustomRequirementsError("Enter a full link starting with http:// or https://.")
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, parts.hostname, None)
    except OSError as exc:
        raise CustomRequirementsError(f"Could not find the site {parts.hostname}.") from exc
    if not infos or not all(_is_public(str(i[4][0])) for i in infos):
        raise CustomRequirementsError("That link points to a private or local address.")


async def fetch_page(http: httpx.AsyncClient, url: str) -> str:
    """Download a page (following a few checked redirects) and return its HTML."""
    current = url.strip()
    for _ in range(MAX_REDIRECTS + 1):
        await check_public_url(current)
        try:
            async with http.stream(
                "GET",
                current,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"},
                timeout=FETCH_TIMEOUT_S,
                follow_redirects=False,
            ) as resp:
                if resp.is_redirect and resp.headers.get("location"):
                    current = urljoin(current, resp.headers["location"])
                    continue
                if resp.status_code != 200:
                    raise CustomRequirementsError(
                        f"The site answered with an error ({resp.status_code}). "
                        "Paste the requirements text instead."
                    )
                kind = resp.headers.get("content-type", "").lower()
                if kind and not kind.startswith(("text/", "application/xhtml")):
                    raise CustomRequirementsError("That link is not a web page. Paste the text.")
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_PAGE_BYTES:
                        break
                return bytes(body).decode(resp.encoding or "utf-8", errors="replace")
        except httpx.HTTPError as exc:
            raise CustomRequirementsError(
                "Could not download that page. Check the link, or paste the requirements text."
            ) from exc
    raise CustomRequirementsError("The link redirects too many times.")


def extract_requirements_text(html: str) -> str:
    """Visible page text, trimmed to the stretch around 'system requirements'."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]):
        tag.decompose()
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in soup.get_text("\n").splitlines()]
    text = "\n".join(ln for ln in lines if ln)
    anchor = _ANCHOR.search(text)
    start = max(0, anchor.start() - 200) if anchor else 0
    return text[start : start + MAX_TEXT_CHARS]


def looks_like_requirements(text: str) -> bool:
    return len(_KEYWORDS.findall(text)) >= 3
