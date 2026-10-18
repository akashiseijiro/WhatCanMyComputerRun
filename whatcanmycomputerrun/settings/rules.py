"""Deterministic settings recommendations from comparison results + hardware.

The FPS model is a transparent heuristic, not a benchmark. It is anchored on the publisher's
own specs: the recommended spec runs "High @ 1080p" at ~60 FPS and the minimum spec runs
"Low @ 1080p" at ~30 FPS; your score is interpolated between/beyond those anchors. All the
constants are at the top so they are easy to retune.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from whatcanmycomputerrun.compare.models import Confidence, Report, RowResult, Verdict
from whatcanmycomputerrun.hardware.base import DeviceType, GpuInfo, GpuVendor, HardwareProfile
from whatcanmycomputerrun.hardware.handhelds import (
    HANDHELD_VRAM,
    HandheldPower,
    PowerMode,
    power_profile,
)
from whatcanmycomputerrun.settings.models import (
    FpsEstimate,
    FrameGenAdvice,
    HandheldAdvice,
    Preset,
    SettingsRecommendation,
    UpscaleMode,
    UpscalerAdvice,
)

REF_PIXELS = 1920 * 1080
REC_FPS = 60.0  # High @ 1080p on the recommended spec
MIN_FPS = 30.0  # Low @ 1080p on the minimum spec
PRESET_MULT = {Preset.ULTRA: 0.7, Preset.HIGH: 1.0, Preset.MEDIUM: 1.4, Preset.LOW: 1.9}
RES_EXPONENT = 0.6  # FPS gain from fewer pixels is sub-linear
UPSCALER_OVERHEAD = 0.92
UPSCALE_AXIS = {  # per-axis render scale (FSR/DLSS/XeSS standard ratios)
    UpscaleMode.QUALITY: 1 / 1.5,
    UpscaleMode.BALANCED: 1 / 1.7,
    UpscaleMode.PERFORMANCE: 1 / 2.0,
}
PLAYABLE_FPS = 25
DESKTOP_TARGET_FPS = 60
HANDHELD_TARGET_FPS = 40

Candidate = tuple[Preset, UpscaleMode | None]
_Q, _B, _P = UpscaleMode.QUALITY, UpscaleMode.BALANCED, UpscaleMode.PERFORMANCE
DESKTOP_LADDER: list[Candidate] = [
    (Preset.ULTRA, None),
    (Preset.HIGH, None),
    (Preset.HIGH, _Q),
    (Preset.MEDIUM, _Q),
    (Preset.MEDIUM, _B),
    (Preset.LOW, _B),
    (Preset.LOW, _P),
]
HANDHELD_LADDER: list[Candidate] = [
    (Preset.HIGH, None),
    (Preset.HIGH, _Q),
    (Preset.MEDIUM, _Q),
    (Preset.MEDIUM, _B),
    (Preset.LOW, _B),
    (Preset.LOW, _P),
]
PRESET_ORDER = [Preset.LOW, Preset.MEDIUM, Preset.HIGH, Preset.ULTRA]


def interp_fps(
    score: float, min_s: float | None, rec_s: float | None, min_fps: float, rec_fps: float
) -> float:
    """FPS at the reference config for a given score, anchored on the min/rec specs."""
    if min_s and rec_s and rec_s > min_s:
        if score >= rec_s:
            return rec_fps * score / rec_s
        if score <= min_s:
            return min_fps * score / min_s
        t = math.log(score / min_s) / math.log(rec_s / min_s)
        return math.exp(math.log(min_fps) * (1 - t) + math.log(rec_fps) * t)
    if rec_s:
        return rec_fps * score / rec_s
    if min_s:
        return min_fps * score / min_s
    return math.inf


def gpu_fps_estimate(gpu_ref: float, preset: Preset, axis: float, out_w: int, out_h: int) -> float:
    render_px = out_w * out_h * axis * axis
    fps = float(gpu_ref * PRESET_MULT[preset] * (REF_PIXELS / render_px) ** RES_EXPONENT)
    return fps * UPSCALER_OVERHEAD if axis < 1 else fps


def _round5(x: float) -> int:
    return max(5, int(round(x / 5.0)) * 5)


def _row(report: Report, key: str) -> RowResult | None:
    return next((r for r in report.rows if r.key == key), None)


def _res(w: int, h: int) -> str:
    return f"{w}x{h}"


def upscaler_technology(gpu: GpuInfo | None) -> str:
    if gpu is None:
        return "FSR"
    if gpu.vendor == GpuVendor.NVIDIA and re.search(r"\bRTX\b", gpu.name, re.I):
        return "DLSS"
    if gpu.vendor == GpuVendor.INTEL and re.search(r"\barc\b", gpu.name, re.I):
        return "XeSS"
    return "FSR"  # AMD, GTX, other Intel: FSR runs on any GPU


def frame_generation(gpu: GpuInfo | None, base_fps: float, refresh: int | None) -> FrameGenAdvice:
    caveat = (
        "Frame generation adds input latency and only looks smooth when the game already "
        "runs at about 40+ FPS without it."
    )
    name = gpu.name if gpu else ""
    if gpu and gpu.vendor == GpuVendor.NVIDIA and re.search(r"RTX\s*[45]\d{3}", name, re.I):
        tech = "DLSS Frame Generation"
    elif gpu and gpu.vendor == GpuVendor.AMD:
        tech = "AMD Fluid Motion Frames (driver setting) or FSR 3 Frame Generation"
    else:
        tech = "FSR 3 Frame Generation (if the game supports it)"
    if base_fps < 40:
        return FrameGenAdvice(
            suggested=False,
            technology=tech,
            note=f"Not recommended: base frame rate (~{base_fps:.0f} FPS) is too low and it "
            "would feel laggy.",
            latency_caveat=caveat,
        )
    ceiling = min(75, refresh) if refresh else 75
    if base_fps >= ceiling:
        return FrameGenAdvice(
            suggested=False,
            technology=tech,
            note="Not needed: you already reach a high frame rate without it.",
            latency_caveat=caveat,
        )
    return FrameGenAdvice(
        suggested=True,
        technology=tech,
        note=f"Optional: could lift ~{base_fps:.0f} FPS toward your display's refresh rate.",
        latency_caveat=caveat,
    )


@dataclass
class _Pick:
    preset: Preset
    upscale: UpscaleMode | None
    mode: PowerMode | None
    fps: float
    gpu_fps: float
    cpu_cap: float
    reached: bool


def _choose(
    ladder: list[Candidate],
    gpu_ref: float,
    cpu_cap: float,
    out_w: int,
    out_h: int,
    target: float,
    modes: list[PowerMode] | None,
    max_watts: int,
) -> _Pick:
    """Best-quality config that reaches the target; within it, the lowest power mode."""
    effective_target = min(target, cpu_cap * 0.95)  # graphics settings can't beat a CPU limit
    best: _Pick | None = None
    for preset, up in ladder:
        axis = UPSCALE_AXIS[up] if up else 1.0
        g = gpu_fps_estimate(gpu_ref, preset, axis, out_w, out_h)
        for mode in modes or [None]:  # type: ignore[list-item]
            mult = math.sqrt(mode.watts / max_watts) if mode else 1.0
            fps = min(g, cpu_cap) * mult
            pick = _Pick(preset, up, mode, fps, g * mult, cpu_cap * mult, fps >= effective_target)
            if pick.reached:
                return pick
            best = pick  # last tried = lowest preset, highest power
    assert best is not None
    return best


def _vram_tip(report: Report, hw: HardwareProfile) -> str | None:
    gpu = hw.primary_gpu
    if not (gpu and gpu.vram_shared):
        return None
    where = "Armoury Crate" if hw.handheld_name and "ROG" in hw.handheld_name else "your BIOS"
    if gpu.vram_assumed and gpu.vram_mb:
        spec = HANDHELD_VRAM.get(hw.handheld_name or "")
        cap = f" (up to {spec.max_mb / 1024:g} GB is allowed)" if spec else ""
        det = f"{gpu.vram_detected_mb / 1024:g} GB" if gpu.vram_detected_mb else "an unknown amount"
        return (
            f"These results assume {gpu.vram_mb / 1024:g} GB of graphics memory{cap}. "
            f"It is {'usually' if gpu.vram_source == 'manual' else 'currently'} {det}: "
            f"set it in {where} (this leaves less RAM for Windows)."
        )
    row = _row(report, "vram")
    if not (row and row.specified and row.verdict in (Verdict.BELOW_MIN, Verdict.MEETS_MIN)):
        return None
    m = re.search(r"[\d.]+", row.minimum or "")
    need = f" (the game asks for {m.group(0)} GB)" if m else ""
    return (
        f"Graphics memory is shared with system RAM and currently set to "
        f"{(gpu.vram_mb or 0) / 1024:g} GB{need}. If it stutters or textures look blurry, raise "
        f"the allocation in {where} (this leaves less RAM for Windows)."
    )


def _handheld_advice(
    hw: HardwareProfile, pick: _Pick, power: HandheldPower, known: bool, est: float
) -> HandheldAdvice:
    mode = pick.mode
    assert mode is not None
    cap = 60 if est >= 58 else 40 if est >= 40 else 30
    battery_cap = 40 if est >= 40 else 30
    hours = power.battery_wh / (mode.watts + 5)
    battery_note = (
        f"Roughly {hours:.1f} h of play on battery at {mode.watts} W "
        f"(rough estimate; depends on the game and screen brightness). "
        f"Capping at {battery_cap} FPS saves power."
    )
    power_note = None
    if mode is power.modes[-1]:
        power_note = f"{mode.name} gives the most performance; use it plugged in for best results."
    if not known:
        power_note = " ".join(
            x
            for x in (
                "Power modes for this device are generic (9/15/25 W); check your device's own "
                "names and limits.",
                power_note,
            )
            if x
        )
    return HandheldAdvice(
        device=hw.handheld_name or hw.model or "Handheld",
        power_mode=mode.name,
        watts=mode.watts,
        fps_cap=cap,
        battery_fps_cap=battery_cap,
        battery_note=battery_note,
        power_note=power_note,
    )


def recommend_settings(hw: HardwareProfile, report: Report) -> SettingsRecommendation:
    gpu_row, cpu_row = _row(report, "gpu"), _row(report, "cpu")
    if (
        gpu_row is None
        or gpu_row.verdict == Verdict.UNKNOWN
        or not gpu_row.your_score
        or not (gpu_row.min_score or gpu_row.rec_score)
    ):
        return SettingsRecommendation(
            available=False,
            unavailable_reason="Settings can't be recommended because your GPU couldn't be "
            "compared with the game's requirements.",
            playable=False,
        )

    warnings: list[str] = []
    notes: list[str] = []
    handheld = hw.device_type == DeviceType.HANDHELD
    gpu = hw.primary_gpu
    disp = hw.display
    if disp and disp.width and disp.height:
        out_w, out_h, refresh = disp.width, disp.height, disp.refresh_hz
    else:
        out_w, out_h, refresh = 1920, 1080, None
        warnings.append("Display resolution wasn't detected; assuming 1920x1080.")

    gpu_ref = interp_fps(
        gpu_row.your_score,
        gpu_row.min_score,
        gpu_row.rec_score,
        MIN_FPS / PRESET_MULT[Preset.LOW],
        REC_FPS,
    )
    cpu_cap = math.inf
    if cpu_row and cpu_row.your_score and (cpu_row.min_score or cpu_row.rec_score):
        cpu_cap = interp_fps(
            cpu_row.your_score, cpu_row.min_score, cpu_row.rec_score, MIN_FPS, REC_FPS
        )

    # VRAM caps the preset: Ultra textures need the recommended amount, High needs the minimum.
    cap_preset = Preset.ULTRA
    vram = _row(report, "vram")
    if vram and vram.specified:
        if vram.verdict == Verdict.BELOW_MIN:
            cap_preset = Preset.MEDIUM
            notes.append("Low video memory: keep texture quality at Medium or below.")
        elif vram.verdict == Verdict.MEETS_MIN:
            cap_preset = Preset.HIGH
    ladder = [
        c
        for c in (HANDHELD_LADDER if handheld else DESKTOP_LADDER)
        if PRESET_ORDER.index(c[0]) <= PRESET_ORDER.index(cap_preset)
    ]

    power, known = power_profile(hw.handheld_name) if handheld else (None, True)
    modes = list(power.modes) if power else None
    max_watts = power.modes[-1].watts if power else 1
    target = HANDHELD_TARGET_FPS if handheld else DESKTOP_TARGET_FPS
    pick = _choose(ladder, gpu_ref, cpu_cap, out_w, out_h, target, modes, max_watts)

    axis = UPSCALE_AXIS[pick.upscale] if pick.upscale else 1.0
    render_w, render_h = round(out_w * axis), round(out_h * axis)
    tech = upscaler_technology(gpu)
    if pick.upscale:
        note = (
            f"Use {tech} {pick.upscale.value} (renders at {_res(render_w, render_h)}, shown at "
            f"{_res(out_w, out_h)}) if the game supports it."
        )
        if tech == "FSR" and gpu and gpu.vendor == GpuVendor.AMD:
            note += " If it doesn't, AMD's driver upscaling (RSR) is an alternative."
        upscaler = UpscalerAdvice(technology=tech, mode=pick.upscale, needed=True, note=note)
    else:
        upscaler = UpscalerAdvice(
            technology=tech,
            needed=False,
            note="Not needed to reach your target. Optionally use "
            f"{tech} Quality as anti-aliasing if the game offers it.",
        )

    est = pick.fps
    limited_by = "CPU" if pick.cpu_cap < pick.gpu_fps else "GPU"
    spread = 0.35 if report.confidence == Confidence.LOW else 0.2
    fps = FpsEstimate(
        low=_round5(est * (1 - spread)), high=_round5(est * (1 + spread)), limited_by=limited_by
    )
    if math.isfinite(cpu_cap) and limited_by == "CPU":
        warnings.append(
            f"Your CPU limits the frame rate to roughly {pick.cpu_cap:.0f} FPS, "
            "so lowering graphics further won't help."
        )
    if report.confidence == Confidence.LOW:
        warnings.append("Low confidence in the hardware comparison, so the FPS range is wide.")

    playable = est >= PLAYABLE_FPS
    if not pick.reached:
        warnings.append(
            f"Even the lowest settings may not reach {target} FPS on this system."
            if not playable
            else f"The {target} FPS target may not be reachable; this is the best compromise."
        )
    if gpu_row.verdict == Verdict.BELOW_MIN:
        warnings.append("Your GPU is below the game's minimum; expect stutter or crashes.")

    handheld_advice = None
    if handheld and power and pick.mode:
        handheld_advice = _handheld_advice(hw, pick, power, known, est)
        if pick.upscale is None:
            notes.append(
                "Handhelds often look as good at 720p-800p with FSR as at native 1080p while "
                "saving power."
            )

    return SettingsRecommendation(
        available=True,
        playable=playable,
        preset=pick.preset,
        target_fps=target,
        output_resolution=_res(out_w, out_h),
        render_resolution=_res(render_w, render_h),
        upscaler=upscaler,
        frame_generation=frame_generation(gpu, est, refresh),
        fps=fps,
        handheld=handheld_advice,
        vram_tip=_vram_tip(report, hw),
        notes=notes,
        warnings=warnings,
    )
