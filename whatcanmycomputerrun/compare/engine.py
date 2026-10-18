"""Compare a HardwareProfile against a game's requirements and decide whether to buy."""

from __future__ import annotations

import re
from dataclasses import dataclass

from whatcanmycomputerrun.compare.models import (
    CONFIDENCE_RANK,
    RECOMMENDATION_TEXT,
    VERDICT_RANK,
    Confidence,
    PerformanceScore,
    Recommendation,
    Report,
    RowResult,
    Verdict,
)
from whatcanmycomputerrun.compare.resolver import (
    ComponentQuery,
    PerformanceResolver,
    ResolveResult,
)
from whatcanmycomputerrun.hardware.base import GpuInfo, GpuKind, HardwareProfile, MediaType
from whatcanmycomputerrun.parsing.schemas import GameDetails, Requirements

# Scores come from an approximate source, so allow a small margin around each threshold.
PERF_BORDER = 0.95
RAM_BORDER = 0.92  # Windows reports e.g. 15.3 GB for a 16 GB kit
VRAM_BORDER = 0.9
EXCEED_MULT = 1.5
NO_REC_MULT = 2.0
HOPELESS_RATIO = 0.5

ROW_PRIORITY = ["gpu", "cpu", "ram", "vram", "storage", "os", "directx"]


def tier_verdict(
    mine: float,
    mn: float | None,
    rec: float | None,
    *,
    border: float = PERF_BORDER,
    can_exceed: bool = True,
) -> tuple[Verdict, str | None]:
    """Compare one number against optional minimum/recommended thresholds."""
    if mn is None and rec is None:
        return Verdict.UNKNOWN, None
    if rec is not None and mn is not None and rec < mn:
        rec = mn
    if mn is None:
        assert rec is not None
        if mine >= rec * border:
            return _above_rec(mine, rec, can_exceed), None
        return Verdict.UNKNOWN, "Minimum requirement unavailable; below the recommended level."
    if mine < mn * border:
        return Verdict.BELOW_MIN, None
    note = "Borderline: within the margin of error of the minimum." if mine < mn else None
    if rec is None:
        if mine >= mn * NO_REC_MULT:
            return (
                Verdict.MEETS_RECOMMENDED,
                "No recommended spec published; at least 2x the minimum.",
            )
        return Verdict.MEETS_MIN, note
    if mine < rec * border:
        return Verdict.MEETS_MIN, note
    return _above_rec(mine, rec, can_exceed), None


def _above_rec(mine: float, rec: float, can_exceed: bool) -> Verdict:
    if can_exceed and mine >= rec * EXCEED_MULT:
        return Verdict.EXCEEDS_RECOMMENDED
    return Verdict.MEETS_RECOMMENDED


def _fmt_list(items: list[str]) -> str | None:
    return " or ".join(items) if items else None


def _fmt_gb(v: float | None) -> str | None:
    if v is None:
        return None
    return f"{v:g} GB"


@dataclass
class _TierScores:
    score: float | None  # weakest resolved alternative
    name: str | None
    confidence: Confidence
    unresolved: int
    benchmark: str | None


def _weakest(alts: list[str], kind: str, result: ResolveResult) -> _TierScores:
    best: tuple[float, str, PerformanceScore] | None = None
    unresolved = 0
    confidence = Confidence.HIGH
    for alt in alts:
        q = ComponentQuery(kind, alt)  # type: ignore[arg-type]
        s = result.get(q)
        if s is None or s.score is None:
            unresolved += 1
            continue
        confidence = _min_conf(confidence, s.confidence)
        if best is None or s.score < best[0]:
            best = (s.score, alt, s)
    if best is None:
        return _TierScores(None, None, Confidence.LOW, unresolved, None)
    if unresolved:
        confidence = Confidence.LOW  # an unresolved alternative might be even weaker
    return _TierScores(best[0], best[1], confidence, unresolved, best[2].benchmark)


def _min_conf(a: Confidence, b: Confidence) -> Confidence:
    return a if CONFIDENCE_RANK[a] <= CONFIDENCE_RANK[b] else b


def _gpu_display(g: GpuInfo) -> str:
    kind = "integrated" if g.kind == GpuKind.INTEGRATED else "discrete"
    vram = f", {g.vram_mb / 1024:g} GB {'shared' if g.vram_shared else 'VRAM'}" if g.vram_mb else ""
    return f"{g.name} ({kind}{vram})"


def collect_queries(
    hw: HardwareProfile, req: Requirements | None, rec: Requirements | None
) -> list[ComponentQuery]:
    queries: list[ComponentQuery] = []
    cpu_name = hw.cpu.model if hw.cpu else None
    if cpu_name:
        queries.append(ComponentQuery("cpu", cpu_name))
    gpu = hw.primary_gpu
    if gpu:
        queries.append(ComponentQuery("gpu", gpu.name, hint=cpu_name))
    for tier in (req, rec):
        if tier:
            queries += [ComponentQuery("cpu", c) for c in tier.cpu]
            queries += [ComponentQuery("gpu", g) for g in tier.gpu]
    return queries


def _perf_row(
    kind: str,
    label: str,
    yours: str | None,
    mine_q: ComponentQuery | None,
    mn: Requirements | None,
    rec: Requirements | None,
    result: ResolveResult,
    extra_note: str | None = None,
) -> RowResult:
    mn_alts = getattr(mn, kind) if mn else []
    rec_alts = getattr(rec, kind) if rec else []
    row = RowResult(
        key=kind,
        label=label,
        yours=yours or "Not detected",
        minimum=_fmt_list(mn_alts),
        recommended=_fmt_list(rec_alts),
        verdict=Verdict.UNKNOWN,
        confidence=Confidence.LOW,
    )
    if not mn_alts and not rec_alts:
        row.specified = False
        row.note = "Not specified by the publisher."
        row.confidence = Confidence.HIGH
        return row
    mine = result.get(mine_q) if mine_q else None
    if mine is None or mine.score is None:
        row.note = f"Could not determine the performance of your {label}."
        return row
    mn_s = _weakest(mn_alts, kind, result)
    rec_s = _weakest(rec_alts, kind, result)
    verdict, note = tier_verdict(mine.score, mn_s.score, rec_s.score)
    conf = mine.confidence
    for t, alts in ((mn_s, mn_alts), (rec_s, rec_alts)):
        if alts:
            conf = _min_conf(conf, t.confidence)
    notes = [n for n in (note, extra_note) if n]
    if verdict == Verdict.UNKNOWN and not notes:
        notes.append("The game's listed parts could not be scored.")
    if mn_s.name and len(mn_alts) > 1:
        notes.append(f"Compared against the weakest listed option: {mn_s.name}.")
    if mn_s.unresolved or rec_s.unresolved:
        notes.append("Some listed alternatives could not be scored, so confidence is reduced.")
    row.verdict = verdict
    row.confidence = conf
    row.note = " ".join(notes) or None
    row.your_score, row.min_score, row.rec_score = mine.score, mn_s.score, rec_s.score
    row.benchmark = mine.benchmark
    return row


def _numeric_row(
    key: str,
    label: str,
    yours: str,
    mine: float | None,
    mn: float | None,
    rec: float | None,
    *,
    border: float,
    can_exceed: bool,
    note: str | None = None,
) -> RowResult:
    row = RowResult(
        key=key,
        label=label,
        yours=yours,
        minimum=_fmt_gb(mn),
        recommended=_fmt_gb(rec),
        verdict=Verdict.UNKNOWN,
        note=note,
    )
    if mn is None and rec is None:
        row.specified = False
        row.note = " ".join(x for x in (note, "Not specified by the publisher.") if x)
        return row
    if mine is None:
        row.note = " ".join(x for x in (note, "Not detected on your system.") if x)
        row.confidence = Confidence.LOW
        return row
    verdict, vnote = tier_verdict(mine, mn, rec, border=border, can_exceed=can_exceed)
    row.verdict = verdict
    row.note = " ".join(x for x in (note, vnote) if x) or None
    return row


def _effective_ram(hw: HardwareProfile) -> tuple[float | None, str | None]:
    if not hw.ram or hw.ram.total_gb is None:
        return None, None
    if hw.ram.installed_gb:  # exact physical RAM (manual selection): nothing to add back
        return hw.ram.installed_gb, None
    gpu = hw.primary_gpu
    reserved_mb = (gpu.vram_detected_mb or gpu.vram_mb) if gpu and gpu.vram_shared else None
    if reserved_mb and reserved_mb >= 1024:
        total = hw.ram.total_gb + reserved_mb / 1024
        return total, (
            f"Windows reports {hw.ram.total_gb:g} GB because {reserved_mb / 1024:g} GB is "
            "reserved for the integrated GPU; the combined pool is counted here."
        )
    return hw.ram.total_gb, None


def _vram_row(hw: HardwareProfile, mn: Requirements | None, rec: Requirements | None) -> RowResult:
    gpu = hw.primary_gpu
    mn_v, rec_v = (mn.vram_gb if mn else None), (rec.vram_gb if rec else None)
    if gpu is None or gpu.vram_mb is None:
        return _numeric_row(
            "vram",
            "VRAM",
            "Not detected",
            None,
            mn_v,
            rec_v,
            border=VRAM_BORDER,
            can_exceed=True,
        )
    mine = gpu.vram_mb / 1024
    if not gpu.vram_shared:
        return _numeric_row(
            "vram",
            "VRAM",
            f"{mine:g} GB",
            mine,
            mn_v,
            rec_v,
            border=VRAM_BORDER,
            can_exceed=True,
        )
    # Integrated GPU: "VRAM" is a BIOS-adjustable slice of system RAM, never a hard fail.
    yours = f"{mine:g} GB (shared with system RAM)"
    if gpu.vram_assumed:
        yours = f"{mine:g} GB (assumed; shared with system RAM)"
    row = _numeric_row(
        "vram", "VRAM", yours, mine, mn_v, rec_v, border=VRAM_BORDER, can_exceed=False
    )
    ram_total, _ = _effective_ram(hw)
    if row.verdict == Verdict.BELOW_MIN and mn_v is not None:
        tip = (
            "Shared memory: this is only the current allocation and can be raised in the "
            "BIOS or Armoury Crate (handhelds)."
        )
        if ram_total is not None and ram_total >= mn_v + 8:
            row.verdict = Verdict.MEETS_MIN
            row.confidence = Confidence.MEDIUM
            row.note = f"{tip} Your system has enough RAM to allocate {mn_v:g} GB."
        else:
            row.note = f"{tip} Your total RAM is too small to allocate {mn_v:g} GB comfortably."
    elif row.verdict != Verdict.UNKNOWN:
        row.note = " ".join(x for x in (row.note, "Shared memory with system RAM.") if x)
    if gpu.vram_assumed:
        det = f"{gpu.vram_detected_mb / 1024:g} GB" if gpu.vram_detected_mb else "unknown"
        when = "usually" if gpu.vram_source == "manual" else "currently"
        where = "Armoury Crate" if hw.handheld_name and "ROG" in hw.handheld_name else "your BIOS"
        row.note = " ".join(
            x
            for x in (
                row.note,
                f"Assumes you set graphics memory to {mine:g} GB in {where} ({when} {det}).",
            )
            if x
        )
    return row


def _storage_row(
    hw: HardwareProfile, mn: Requirements | None, rec: Requirements | None
) -> RowResult:
    drives = [d for d in hw.storage if d.free_gb is not None]
    mn_v, rec_v = (mn.storage_gb if mn else None), (rec.storage_gb if rec else None)
    if not drives:
        return _numeric_row(
            "storage",
            "Storage",
            "Not detected",
            None,
            mn_v,
            rec_v,
            border=1.0,
            can_exceed=False,
        )
    roomy = [d for d in drives if (d.free_gb or 0) >= (mn_v or 0)]
    ssd_roomy = [d for d in roomy if d.media_type == MediaType.SSD]
    best = max(ssd_roomy or drives, key=lambda d: d.free_gb or 0)
    media = "" if best.media_type == MediaType.UNKNOWN else f", {best.media_type.value.upper()}"
    yours = f"{best.free_gb:g} GB free on {best.letter}{media}"
    row = _numeric_row(
        "storage", "Storage", yours, best.free_gb, mn_v, rec_v, border=1.0, can_exceed=False
    )
    notes_text = " ".join(t.notes or "" for t in (mn, rec) if t)
    if "ssd" in notes_text.lower() and row.verdict != Verdict.BELOW_MIN:
        ssds = [
            d for d in drives if d.media_type == MediaType.SSD and (d.free_gb or 0) >= (mn_v or 0)
        ]
        if ssds:
            row.note = " ".join(
                x for x in (row.note, "SSD required: you have a suitable SSD.") if x
            )
        elif all(
            d.media_type == MediaType.HDD for d in drives if (d.free_gb or 0) >= (mn_v or 0)
        ) and any(d.media_type == MediaType.HDD for d in drives):
            row.verdict = Verdict.BELOW_MIN
            row.note = "The game requires an SSD but only a hard drive has enough free space."
        else:
            row.note = " ".join(
                x for x in (row.note, "SSD required; could not confirm your drive type.") if x
            )
            row.confidence = Confidence.MEDIUM
    return row


_WIN_TOKEN = re.compile(r"\b(xp|vista|7|8\.1|8|10|11)\b", re.I)
_WIN_NUM = {"xp": 5.0, "vista": 6.0, "7": 7.0, "8": 8.0, "8.1": 8.1, "10": 10.0, "11": 11.0}


def _win_versions(text: str | None) -> list[float]:
    if not text or "windows" not in text.lower():
        return []
    return [_WIN_NUM[t.lower()] for t in _WIN_TOKEN.findall(text)]


def _os_row(hw: HardwareProfile, mn: Requirements | None, rec: Requirements | None) -> RowResult:
    build = int(hw.os.build) if hw.os and hw.os.build and hw.os.build.isdigit() else None
    mine = None if build is None else 11.0 if build >= 22000 else 10.0 if build >= 10240 else 8.1
    yours = (hw.os.name or f"Windows build {build}") if hw.os else "Not detected"
    mn_o, rec_o = (mn.os if mn else None), (rec.os if rec else None)
    row = RowResult(
        key="os", label="OS", yours=yours, minimum=mn_o, recommended=rec_o, verdict=Verdict.UNKNOWN
    )
    if not mn_o and not rec_o:
        row.specified = False
        row.note = "Not specified by the publisher."
        return row
    mn_v = min(_win_versions(mn_o), default=None)
    rec_v = min(_win_versions(rec_o), default=None)
    if mine is None or (mn_v is None and rec_v is None):
        row.note = "Could not compare the operating system."
        row.confidence = Confidence.LOW
        return row
    base = mn_v if mn_v is not None else rec_v
    assert base is not None
    if mine < base:
        row.verdict = Verdict.BELOW_MIN
    elif rec_v is not None and mine < rec_v:
        row.verdict = Verdict.MEETS_MIN
    else:
        row.verdict = Verdict.MEETS_RECOMMENDED
    return row


def _dx_row(hw: HardwareProfile, mn: Requirements | None, rec: Requirements | None) -> RowResult:
    def num(s: str | None) -> float | None:
        m = re.search(r"\d+(?:\.\d+)?", s or "")
        return float(m.group(0)) if m else None

    mine = num(hw.os.directx) if hw.os else None
    mn_d, rec_d = (mn.directx if mn else None), (rec.directx if rec else None)
    row = RowResult(
        key="directx",
        label="DirectX",
        yours=(hw.os.directx if hw.os and hw.os.directx else "Not detected"),
        minimum=f"DirectX {mn_d}" if mn_d else None,
        recommended=f"DirectX {rec_d}" if rec_d else None,
        verdict=Verdict.UNKNOWN,
    )
    need_mn, need_rec = num(mn_d), num(rec_d)
    if need_mn is None and need_rec is None:
        row.specified = False
        row.note = "Not specified by the publisher."
        return row
    if mine is None:
        row.note = "DirectX version could not be detected."
        row.confidence = Confidence.LOW
        return row
    base = need_mn if need_mn is not None else need_rec
    assert base is not None
    if mine < base:
        row.verdict = Verdict.BELOW_MIN
    elif need_rec is not None and mine < need_rec:
        row.verdict = Verdict.MEETS_MIN
    else:
        row.verdict = Verdict.MEETS_RECOMMENDED
    if base >= 12 and row.verdict != Verdict.BELOW_MIN:
        row.confidence = Confidence.MEDIUM
        row.note = "Windows provides DirectX 12; your GPU's feature level is not probed."
    return row


def _ratio(r: RowResult) -> float | None:
    if r.your_score and r.min_score:
        return r.your_score / r.min_score
    return None


def decide(
    rows: list[RowResult], windows_supported: bool = True
) -> tuple[Recommendation, Verdict, str | None, list[str]]:
    """Return (recommendation, overall verdict, bottleneck row key, reasons)."""
    reasons: list[str] = []
    specified = [r for r in rows if r.specified]
    known = [r for r in specified if r.verdict != Verdict.UNKNOWN]
    if not known:
        overall = Verdict.UNKNOWN
        bottleneck = None
    else:
        lowest = min(VERDICT_RANK[r.verdict] for r in known)
        worst = [r for r in known if VERDICT_RANK[r.verdict] == lowest]
        worst.sort(key=lambda r: ROW_PRIORITY.index(r.key))
        overall, bottleneck = worst[0].verdict, worst[0].key

    if not windows_supported:
        return (
            Recommendation.DONT_BUY,
            overall,
            bottleneck,
            ["Steam lists no Windows version of this game."],
        )

    below = [r for r in known if r.verdict == Verdict.BELOW_MIN]
    unknown_core = [
        r for r in specified if r.key in ("cpu", "gpu") and r.verdict == Verdict.UNKNOWN
    ]

    for r in below:
        ratio = _ratio(r)
        pct = f" (about {ratio:.0%} of the minimum)" if ratio else ""
        reasons.append(
            f"{r.label} is below the minimum requirement{pct}: yours {r.yours}, needs {r.minimum}."
        )
    for r in unknown_core:
        reasons.append(f"Your {r.label} could not be compared, so this result is not confirmed.")
    for r in known:
        if r.verdict == Verdict.MEETS_MIN:
            reasons.append(f"{r.label} only meets the minimum; expect low settings.")

    if below:
        severe = any(
            r.key == "os" or (r.key in ("gpu", "cpu") and (_ratio(r) or 1) < HOPELESS_RATIO)
            for r in below
        )
        return (
            (Recommendation.DONT_BUY if severe else Recommendation.RISKY),
            overall,
            bottleneck,
            reasons,
        )
    if unknown_core:
        return Recommendation.INSUFFICIENT_DATA, overall, bottleneck, reasons
    if overall == Verdict.MEETS_MIN:
        return Recommendation.BUY_WITH_COMPROMISES, overall, bottleneck, reasons
    if not known:
        reasons.append("No comparable requirements were found.")
        return Recommendation.INSUFFICIENT_DATA, overall, bottleneck, reasons
    reasons.append("Your system meets or exceeds the recommended requirements.")
    return Recommendation.BUY, overall, bottleneck, reasons


def _yours_cpu(hw: HardwareProfile) -> str | None:
    if not hw.cpu:
        return None
    parts = f" ({hw.cpu.cores}C/{hw.cpu.threads}T)" if hw.cpu.cores and hw.cpu.threads else ""
    return f"{hw.cpu.model}{parts}"


async def build_report(
    hw: HardwareProfile, game: GameDetails, resolver: PerformanceResolver
) -> Report:
    warnings: list[str] = []
    if game.coming_soon:
        warnings.append("This game is not released yet; requirements may change.")

    reqs = game.requirements
    if reqs is None or (reqs.minimum is None and reqs.recommended is None):
        return Report(
            game=game,
            rows=[],
            overall_verdict=Verdict.UNKNOWN,
            recommendation=Recommendation.INSUFFICIENT_DATA,
            headline=RECOMMENDATION_TEXT[Recommendation.INSUFFICIENT_DATA],
            reasons=["No system requirements could be found for this game."],
            confidence=Confidence.LOW,
            warnings=warnings,
        )
    warnings += reqs.warnings
    mn, rec = reqs.minimum, reqs.recommended

    result = await resolver.resolve(collect_queries(hw, mn, rec))
    warnings += result.warnings

    cpu_name = hw.cpu.model if hw.cpu else None
    gpu = hw.primary_gpu
    gpu_note = None
    others = [g for g in hw.gpus if g is not gpu]
    if others:
        gpu_note = "Also present: " + "; ".join(_gpu_display(g) for g in others) + "."

    ram_eff, ram_note = _effective_ram(hw)
    rows = [
        _perf_row(
            "gpu",
            "GPU",
            _gpu_display(gpu) if gpu else None,
            ComponentQuery("gpu", gpu.name, hint=cpu_name) if gpu else None,
            mn,
            rec,
            result,
            gpu_note,
        ),
        _perf_row(
            "cpu",
            "CPU",
            _yours_cpu(hw),
            ComponentQuery("cpu", cpu_name) if cpu_name else None,
            mn,
            rec,
            result,
        ),
        _numeric_row(
            "ram",
            "RAM",
            f"{hw.ram.total_gb:g} GB" if hw.ram and hw.ram.total_gb is not None else "Not detected",
            ram_eff,
            mn.ram_gb if mn else None,
            rec.ram_gb if rec else None,
            border=RAM_BORDER,
            can_exceed=True,
            note=ram_note,
        ),
        _vram_row(hw, mn, rec),
        _storage_row(hw, mn, rec),
        _os_row(hw, mn, rec),
        _dx_row(hw, mn, rec),
    ]

    recommendation, overall, bottleneck, reasons = decide(rows, game.windows_supported)
    core = [r for r in rows if r.key in ("cpu", "gpu") and r.specified]
    confidence = Confidence.HIGH
    for r in core:
        confidence = _min_conf(confidence, r.confidence)
    if reqs.parse_method != "deterministic":
        confidence = _min_conf(confidence, Confidence.MEDIUM)
        warnings.append("Some requirement fields were read with AI assistance.")
    return Report(
        game=game,
        rows=rows,
        overall_verdict=overall,
        recommendation=recommendation,
        headline=RECOMMENDATION_TEXT[recommendation],
        reasons=reasons,
        confidence=confidence,
        bottleneck=bottleneck,
        warnings=warnings,
    )
