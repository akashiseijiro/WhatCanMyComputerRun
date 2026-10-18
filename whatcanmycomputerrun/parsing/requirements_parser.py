"""Deterministic parser for Steam's pc_requirements HTML."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup

from whatcanmycomputerrun.parsing.schemas import Requirements

CORE_FIELDS = ("cpu", "gpu", "ram_gb")

_LABELS: dict[str, tuple[str, ...]] = {
    "cpu": ("processor", "cpu"),
    "gpu": ("graphics", "video card", "gpu", "video", "graphics card"),
    "ram": ("memory", "ram", "system memory"),
    "vram": ("video memory", "vram", "graphics memory"),
    "storage": ("storage", "hard drive", "hard disk", "hard disk space", "disk space", "space"),
    "os": ("os", "operating system"),
    "directx": ("directx", "direct x"),
    "notes": ("additional notes", "notes"),
}
_LABEL_TO_FIELD = {label: f for f, labels in _LABELS.items() for label in labels}

_EQUIV = r"(?:equivalent|better|higher|newer|faster|greater|above|equal|similar)"
_EQUIV_RE = re.compile(rf"\(?\s*\bor\s+{_EQUIV}\b[^)\n]*\)?", re.I)
_VENDOR = r"(?:NVIDIA|AMD|Intel|Radeon|GeForce|Ryzen|Core|GTX|RTX|RX|Arc|Apple|Qualcomm|Snapdragon)"
_SPLIT_RE = re.compile(rf"\s+or\s+|\s+/\s+|\s*;\s*|\s*\|\s*|,\s*(?=\(?{_VENDOR}\b)", re.I)
_SIZE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(TB|GB|GiB|MB|G)\b", re.I)
_LINE_RE = re.compile(r"^([^:]{2,30}):\s*(.*)$", re.S)


@dataclass
class ParsedTier:
    requirements: Requirements
    missing: list[str] = field(default_factory=list)
    raw_text: str = ""


@dataclass
class ParsedPcRequirements:
    minimum: ParsedTier | None
    recommended: ParsedTier | None

    @property
    def needs_llm(self) -> bool:
        return any(t.missing for t in (self.minimum, self.recommended) if t is not None)


def split_alternatives(value: str) -> list[str]:
    cleaned = _EQUIV_RE.sub(" ", value)
    parts = [p.strip(" ,.;-") for p in _SPLIT_RE.split(cleaned)]
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        key = p.lower()
        if p and re.search(r"[A-Za-z]", p) and key not in seen:
            seen.add(key)
            out.append(re.sub(r"\s+", " ", p))
    return out


def _to_gb(amount: str, unit: str) -> float:
    n = float(amount.replace(",", "."))
    u = unit.upper()
    if u == "MB":
        return n / 1024
    if u == "TB":
        return n * 1024
    return n


def parse_size_gb(value: str) -> float | None:
    m = _SIZE_RE.search(value)
    return round(_to_gb(m.group(1), m.group(2)), 2) if m else None


def vram_from_gpus(gpus: list[str]) -> float | None:
    """VRAM written inside GPU alternatives ("RX 580 8GB"); the weakest option wins."""
    found: list[float] = []
    for g in gpus:
        m = _SIZE_RE.search(g)
        if m:
            gb = _to_gb(m.group(1), m.group(2))
            if 0.25 <= gb <= 48:
                found.append(round(gb, 2))
    return min(found) if found else None


def _candidate_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    items = [li.get_text(" ", strip=True) for li in soup.find_all("li")]
    if items:
        return items
    for br in soup.find_all("br"):
        br.replace_with("\n")
    return [ln.strip() for ln in soup.get_text().split("\n") if ln.strip()]


def parse_tier(html: str) -> ParsedTier:
    req = Requirements()
    raw_lines: list[str] = []
    explicit_vram: float | None = None
    for line in _candidate_lines(html):
        m = _LINE_RE.match(line)
        if not m:
            continue
        label, value = m.group(1).strip().lower(), m.group(2).strip()
        fld = _LABEL_TO_FIELD.get(label)
        if not fld or not value:
            continue
        raw_lines.append(f"{m.group(1).strip()}: {value}")
        if fld == "cpu":
            req.cpu = split_alternatives(value)
        elif fld == "gpu":
            req.gpu = split_alternatives(value)
        elif fld == "ram":
            req.ram_gb = parse_size_gb(value)
        elif fld == "vram":
            explicit_vram = parse_size_gb(value)
        elif fld == "storage":
            req.storage_gb = parse_size_gb(value)
        elif fld == "os":
            req.os = value
        elif fld == "directx":
            d = re.search(r"\d+(?:\.\d+)?", value)
            req.directx = d.group(0) if d else value
        elif fld == "notes":
            req.notes = value
    req.vram_gb = explicit_vram if explicit_vram is not None else vram_from_gpus(req.gpu)
    missing = [f for f in CORE_FIELDS if not getattr(req, f)]
    return ParsedTier(requirements=req, missing=missing, raw_text="\n".join(raw_lines))


_REC_SPLIT = re.compile(r"<strong>\s*Recommended\s*:?\s*</strong>", re.I)


def parse_pc_requirements(pc_req: Any) -> ParsedPcRequirements:
    """Steam returns a dict, or an empty list when a game lists no PC requirements."""
    if not isinstance(pc_req, dict):
        return ParsedPcRequirements(None, None)
    min_html = str(pc_req.get("minimum") or "")
    rec_html = str(pc_req.get("recommended") or "")
    if min_html and not rec_html:
        parts = _REC_SPLIT.split(min_html, maxsplit=1)
        if len(parts) == 2:
            min_html, rec_html = parts
    return ParsedPcRequirements(
        minimum=parse_tier(min_html) if min_html.strip() else None,
        recommended=parse_tier(rec_html) if rec_html.strip() else None,
    )
