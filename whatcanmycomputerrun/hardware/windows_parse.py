"""Pure parsing of raw Windows hardware data into a HardwareProfile.

No Windows imports here, so everything is unit-tested on macOS with recorded/hand-written data.
Raw input shape (all keys optional): see windows.COLLECT_SCRIPT and the registry/DXGI collectors.
"""

from __future__ import annotations

import re
from typing import Any

from whatcanmycomputerrun.hardware.base import (
    CpuInfo,
    DeviceType,
    DisplayInfo,
    DriveInfo,
    GpuInfo,
    GpuKind,
    GpuVendor,
    HardwareProfile,
    MediaType,
    OsInfo,
    RamInfo,
)
from whatcanmycomputerrun.hardware.handhelds import match_handheld

WMI_ADAPTER_RAM_CAP = 0xFFF00000  # AdapterRAM is uint32; cards with >= 4 GB report ~4293918720
LAPTOP_CHASSIS = {8, 9, 10, 11, 12, 14, 18, 21, 30, 31, 32}
VIRTUAL_GPU = re.compile(
    r"basic display|basic render|remote display|hyper-v|vmware|virtualbox|parsec|"
    r"indirect display|virtual|citrix|displaylink|meta virtual",
    re.I,
)


def as_list(value: Any) -> list[Any]:
    """PowerShell's ConvertTo-Json collapses 1-item arrays to objects and empty to null."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _s(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def gpu_vendor(name: str, adapter_compat: str | None = None) -> GpuVendor:
    text = f"{name} {adapter_compat or ''}".lower()
    if "nvidia" in text or "geforce" in text or "quadro" in text:
        return GpuVendor.NVIDIA
    if "amd" in text or "radeon" in text or "advanced micro" in text or "ati " in text:
        return GpuVendor.AMD
    if "intel" in text:
        return GpuVendor.INTEL
    return GpuVendor.OTHER


def classify_gpu_kind(name: str, vendor: GpuVendor) -> GpuKind:
    if vendor == GpuVendor.NVIDIA:
        return GpuKind.DISCRETE
    if vendor == GpuVendor.INTEL:
        if re.search(r"\bArc\b.*\b[AB]\d{3}\b", name, re.I):
            return GpuKind.DISCRETE
        return GpuKind.INTEGRATED
    if vendor == GpuVendor.AMD:
        if re.search(r"\bRX\b|\bPro\b|\bR[579]\s+\d{3}\b|\bVII\b|\bFury\b", name, re.I):
            return GpuKind.DISCRETE
        if re.search(r"Graphics\s*$|\b\d{3,4}M\s*$", name, re.I):
            return GpuKind.INTEGRATED
    return GpuKind.DISCRETE


def _pnp_ids(pnp: str | None) -> tuple[str, str] | None:
    m = re.search(r"VEN_([0-9A-F]{4})&DEV_([0-9A-F]{4})", pnp or "", re.I)
    return (m.group(1).lower(), m.group(2).lower()) if m else None


def _match_registry(
    wmi: dict[str, Any], entries: list[dict[str, Any]], used: set[int]
) -> dict[str, Any] | None:
    name = clean_name(str(wmi.get("Name") or "")).lower()
    pnp = str(wmi.get("PNPDeviceID") or "").lower()
    for i, e in enumerate(entries):
        if i in used:
            continue
        desc = clean_name(str(e.get("driver_desc") or "")).lower()
        mid = str(e.get("matching_device_id") or "").lower()
        if (name and desc == name) or (mid and pnp.startswith(mid)):
            used.add(i)
            return e
    return None


def _match_dxgi(
    wmi: dict[str, Any], adapters: list[dict[str, Any]], used: set[int]
) -> dict[str, Any] | None:
    name = clean_name(str(wmi.get("Name") or "")).lower()
    ids = _pnp_ids(wmi.get("PNPDeviceID"))
    for i, a in enumerate(adapters):
        if i in used or a.get("software"):
            continue
        a_ids = (f"{a.get('vendor_id', 0):04x}", f"{a.get('device_id', 0):04x}")
        if (ids and ids == a_ids) or (
            name and clean_name(str(a.get("name") or "")).lower() == name
        ):
            used.add(i)
            return a
    return None


def build_gpus(
    wmi_gpus: list[dict[str, Any]],
    registry: list[dict[str, Any]],
    dxgi: list[dict[str, Any]],
    warnings: list[str],
) -> list[GpuInfo]:
    reg_used: set[int] = set()
    dxgi_used: set[int] = set()
    gpus: list[GpuInfo] = []
    for w in wmi_gpus:
        name = clean_name(str(w.get("Name") or ""))
        if not name:
            continue
        vendor = gpu_vendor(name, _s(w.get("AdapterCompatibility")))
        kind = classify_gpu_kind(name, vendor)

        reg = _match_registry(w, registry, reg_used)
        dx = _match_dxgi(w, dxgi, dxgi_used)
        vram_mb: int | None = None
        source: str | None = None
        reg_bytes = _int(reg.get("memory_bytes")) if reg else None
        dx_bytes = _int(dx.get("dedicated_bytes")) if dx else None
        wmi_bytes = _int(w.get("AdapterRAM"))
        if reg_bytes:
            vram_mb, source = reg_bytes // (1024 * 1024), "registry"
        elif dx_bytes:
            vram_mb, source = dx_bytes // (1024 * 1024), "dxgi"
        elif wmi_bytes:
            vram_mb, source = wmi_bytes // (1024 * 1024), "wmi"
            if wmi_bytes >= WMI_ADAPTER_RAM_CAP:
                warnings.append(
                    f"{name}: VRAM is 4 GB or more but the exact amount could not be read "
                    "(registry and DXGI unavailable; WMI is capped at 4 GB)."
                )
        else:
            warnings.append(f"{name}: VRAM could not be detected.")

        gpus.append(
            GpuInfo(
                name=name,
                vendor=vendor,
                kind=kind,
                vram_mb=vram_mb,
                vram_shared=kind == GpuKind.INTEGRATED,
                driver_version=_s(w.get("DriverVersion")),
                vram_source=source,
            )
        )

    physical = [g for g in gpus if not VIRTUAL_GPU.search(g.name)]
    if physical:
        return physical
    if gpus:
        warnings.append("Only virtual/basic display adapters were found; no physical GPU detected.")
    return gpus


def parse_cpu(raw: list[dict[str, Any]], warnings: list[str]) -> CpuInfo | None:
    if not raw:
        warnings.append("CPU could not be detected.")
        return None
    cpus = raw
    name = clean_name(str(cpus[0].get("Name") or "")) or "Unknown CPU"
    cores = sum(_int(c.get("NumberOfCores")) or 0 for c in cpus) or None
    threads = sum(_int(c.get("NumberOfLogicalProcessors")) or 0 for c in cpus) or None
    return CpuInfo(
        model=name,
        cores=cores,
        threads=threads,
        base_clock_mhz=_int(cpus[0].get("MaxClockSpeed")),
        boost_clock_mhz=None,  # Windows exposes no reliable boost clock
    )


def parse_ram(
    computer: dict[str, Any] | None, modules: list[dict[str, Any]], warnings: list[str]
) -> RamInfo | None:
    total_bytes = _int((computer or {}).get("TotalPhysicalMemory"))
    if not total_bytes:
        total_bytes = sum(_int(m.get("Capacity")) or 0 for m in modules) or None
    speeds = [
        s for m in modules if (s := _int(m.get("ConfiguredClockSpeed")) or _int(m.get("Speed")))
    ]
    if not total_bytes:
        warnings.append("RAM size could not be detected.")
        return None
    return RamInfo(
        total_gb=round(total_bytes / 1024**3, 1),
        speed_mhz=max(speeds) if speeds else None,
    )


def parse_storage(raw: dict[str, Any], warnings: list[str]) -> list[DriveInfo]:
    disks = as_list(raw.get("logical_disks"))
    if not disks:
        warnings.append("Storage drives could not be detected.")
        return []
    letter_to_disk = {
        str(p.get("DriveLetter") or "").upper(): _int(p.get("DiskNumber"))
        for p in as_list(raw.get("partitions"))
    }
    media: dict[int, MediaType] = {}
    for p in as_list(raw.get("physical_disks")):
        dev = _int(p.get("DeviceId"))
        if dev is None:
            continue
        kind = str(p.get("MediaType") or "").upper()
        bus = str(p.get("BusType") or "").upper()
        if kind == "SSD" or bus == "NVME":
            media[dev] = MediaType.SSD
        elif kind == "HDD":
            media[dev] = MediaType.HDD
        else:
            media[dev] = MediaType.UNKNOWN

    drives: list[DriveInfo] = []
    for d in disks:
        letter = str(d.get("DeviceID") or "").strip().upper()
        if not letter:
            continue
        free, size = _int(d.get("FreeSpace")), _int(d.get("Size"))
        disk_no = letter_to_disk.get(letter.rstrip(":"))
        drives.append(
            DriveInfo(
                letter=letter,
                free_gb=round(free / 1024**3, 1) if free is not None else None,
                total_gb=round(size / 1024**3, 1) if size is not None else None,
                media_type=media.get(disk_no, MediaType.UNKNOWN)
                if disk_no is not None
                else MediaType.UNKNOWN,
            )
        )
    return drives


def parse_os(raw_os: dict[str, Any] | None, warnings: list[str]) -> OsInfo | None:
    if not raw_os:
        warnings.append("Operating system could not be detected.")
        return None
    build = _s(raw_os.get("BuildNumber"))
    build_no = _int(build)
    # Win10+ ships the DirectX 12 runtime. The GPU's supported feature level is not probed.
    directx = "DirectX 12" if build_no and build_no >= 10240 else None
    return OsInfo(
        name=_s(raw_os.get("Caption")),
        version=_s(raw_os.get("Version")),
        build=build,
        directx=directx,
    )


def parse_display(wmi_gpus: list[dict[str, Any]], warnings: list[str]) -> DisplayInfo | None:
    for g in wmi_gpus:
        w, h = _int(g.get("CurrentHorizontalResolution")), _int(g.get("CurrentVerticalResolution"))
        if w and h:
            return DisplayInfo(width=w, height=h, refresh_hz=_int(g.get("CurrentRefreshRate")))
    warnings.append("Display resolution/refresh rate could not be detected.")
    return None


def detect_device_type(
    manufacturer: str | None,
    model: str | None,
    chassis_types: list[int],
    pc_system_type: int | None,
    has_battery: bool,
) -> tuple[DeviceType, str | None]:
    handheld = match_handheld(manufacturer, model)
    if handheld:
        return DeviceType.HANDHELD, handheld
    if (
        LAPTOP_CHASSIS & set(chassis_types)
        or pc_system_type in (2, 8)
        or (has_battery and not chassis_types)
    ):
        return DeviceType.LAPTOP, None
    return DeviceType.DESKTOP, None


def build_profile(
    raw: dict[str, Any],
    registry: list[dict[str, Any]] | None = None,
    dxgi: list[dict[str, Any]] | None = None,
) -> HardwareProfile:
    """Combine raw collector output. A missing/broken section yields None + a warning."""
    warnings: list[str] = []
    wmi_gpus = [g for g in as_list(raw.get("gpu")) if isinstance(g, dict)]
    computer_raw = raw.get("computer_system")
    computer = computer_raw if isinstance(computer_raw, dict) else None

    gpus = build_gpus(wmi_gpus, registry or [], dxgi or [], warnings) if wmi_gpus else []
    if not gpus and not wmi_gpus:
        warnings.append("GPU could not be detected.")

    manufacturer = _s((computer or {}).get("Manufacturer"))
    model = _s((computer or {}).get("Model"))
    chassis: list[int] = []
    for enc in as_list(raw.get("enclosure")):
        if isinstance(enc, dict):
            chassis += [c for c in map(_int, as_list(enc.get("ChassisTypes"))) if c is not None]
    device_type, handheld_name = detect_device_type(
        manufacturer,
        model,
        chassis,
        _int((computer or {}).get("PCSystemType")),
        bool(as_list(raw.get("battery"))),
    )
    if computer is None:
        warnings.append("System manufacturer/model could not be detected; device type is a guess.")

    os_raw = raw.get("os")
    return HardwareProfile(
        cpu=parse_cpu([c for c in as_list(raw.get("cpu")) if isinstance(c, dict)], warnings),
        gpus=gpus,
        ram=parse_ram(
            computer,
            [m for m in as_list(raw.get("ram_modules")) if isinstance(m, dict)],
            warnings,
        ),
        storage=parse_storage(raw, warnings),
        os=parse_os(os_raw if isinstance(os_raw, dict) else None, warnings),
        display=parse_display(wmi_gpus, warnings),
        device_type=device_type,
        manufacturer=manufacturer,
        model=model,
        handheld_name=handheld_name,
        warnings=warnings,
        source="detected",
    )
