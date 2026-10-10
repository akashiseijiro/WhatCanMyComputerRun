"""Windows hardware collectors. Imported lazily; never import this at module level elsewhere.

Sources, in priority order for VRAM: registry (64-bit) -> DXGI -> WMI (32-bit, caps at 4 GB).
Everything else comes from one PowerShell/CIM call. Parsing lives in windows_parse (pure).
"""

from __future__ import annotations

import base64
import ctypes
import json
import subprocess
import uuid
from typing import Any

from canirunit.hardware.base import HardwareProfile
from canirunit.hardware.windows_parse import build_profile

COLLECT_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
function Q($class, $props) { @(Get-CimInstance -ClassName $class | Select-Object $props) }
$r = [ordered]@{
  cpu = Q Win32_Processor Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed
  gpu = Q Win32_VideoController Name,AdapterCompatibility,DriverVersion,AdapterRAM,PNPDeviceID,CurrentHorizontalResolution,CurrentVerticalResolution,CurrentRefreshRate
  ram_modules = Q Win32_PhysicalMemory Capacity,Speed,ConfiguredClockSpeed
  computer_system = Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,TotalPhysicalMemory,PCSystemType
  os = Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber
  enclosure = Q Win32_SystemEnclosure ChassisTypes
  battery = Q Win32_Battery Name
  logical_disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Select-Object DeviceID,Size,FreeSpace)
  partitions = @(Get-Partition | Where-Object DriveLetter | Select-Object @{n='DriveLetter';e={[string]$_.DriveLetter}},DiskNumber)
  physical_disks = @(Get-PhysicalDisk | Select-Object @{n='DeviceId';e={[int]$_.DeviceId}},@{n='MediaType';e={[string]$_.MediaType}},@{n='BusType';e={[string]$_.BusType}})
}
ConvertTo-Json -InputObject $r -Depth 4 -Compress
"""

GPU_CLASS_KEY = r"SYSTEM\{cs}\Control\Class\{{4d36e968-e325-11ce-bfc1-08002be10318}}"


def run_powershell(script: str, timeout: float = 90) -> dict[str, Any]:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    last_error: Exception | None = None
    for exe in ("powershell", "pwsh"):
        try:
            proc = subprocess.run(
                [exe, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                capture_output=True,
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            last_error = exc
            continue
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        if not out:
            last_error = RuntimeError(proc.stderr.decode("utf-8", errors="replace")[:300])
            continue
        data = json.loads(out)
        if isinstance(data, dict):
            return data
        raise ValueError("PowerShell returned unexpected JSON")
    raise RuntimeError(f"PowerShell hardware query failed: {last_error}")


def read_registry_gpus() -> list[dict[str, Any]]:
    """64-bit VRAM sizes from the display class registry key (WMI AdapterRAM caps at 4 GB)."""
    import winreg

    entries: list[dict[str, Any]] = []
    for control_set in ("ControlSet001", "CurrentControlSet"):
        try:
            base = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, GPU_CLASS_KEY.format(cs=control_set)
            )
        except OSError:
            continue
        with base:
            index = 0
            while True:
                try:
                    sub = winreg.EnumKey(base, index)
                except OSError:
                    break
                index += 1
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(base, sub) as key:
                        entries.append(_read_gpu_subkey(winreg, key))
                except OSError:
                    continue
        if entries:
            break
    return [e for e in entries if e.get("driver_desc")]


def _read_gpu_subkey(winreg: Any, key: Any) -> dict[str, Any]:
    def value(name: str) -> Any:
        try:
            return winreg.QueryValueEx(key, name)[0]
        except OSError:
            return None

    mem = value("HardwareInformation.qwMemorySize")
    if isinstance(mem, bytes | bytearray):
        mem = int.from_bytes(mem, "little")
    if not mem:  # older drivers: 32-bit field
        legacy = value("HardwareInformation.MemorySize")
        mem = int.from_bytes(legacy, "little") if isinstance(legacy, bytes | bytearray) else legacy
    return {
        "driver_desc": value("DriverDesc"),
        "matching_device_id": value("MatchingDeviceId"),
        "memory_bytes": int(mem) if mem else None,
    }


def read_dxgi_adapters() -> list[dict[str, Any]]:
    """Enumerate adapters via DXGI 1.1 with raw COM vtable calls (no extra dependency)."""

    class GUID(ctypes.Structure):
        _fields_ = [("bytes", ctypes.c_ubyte * 16)]

    class DESC1(ctypes.Structure):
        _fields_ = [
            ("Description", ctypes.c_wchar * 128),
            ("VendorId", ctypes.c_uint),
            ("DeviceId", ctypes.c_uint),
            ("SubSysId", ctypes.c_uint),
            ("Revision", ctypes.c_uint),
            ("DedicatedVideoMemory", ctypes.c_size_t),
            ("DedicatedSystemMemory", ctypes.c_size_t),
            ("SharedSystemMemory", ctypes.c_size_t),
            ("AdapterLuid", ctypes.c_int64),
            ("Flags", ctypes.c_uint),
        ]

    def method(obj: ctypes.c_void_p, index: int, *argtypes: Any) -> Any:
        vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
        fn = proto(vtbl[index])
        return lambda *args: fn(obj, *args)

    iid = GUID.from_buffer_copy(uuid.UUID("770aae78-f26f-4dba-a829-253c83d1b387").bytes_le)
    factory = ctypes.c_void_p()
    dxgi = ctypes.WinDLL("dxgi")
    if dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory)) != 0:
        return []

    adapters: list[dict[str, Any]] = []
    try:
        enum_adapters1 = method(factory, 12, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            if enum_adapters1(index, ctypes.byref(adapter)) != 0:
                break
            index += 1
            try:
                desc = DESC1()
                if method(adapter, 10, ctypes.POINTER(DESC1))(ctypes.byref(desc)) == 0:
                    adapters.append(
                        {
                            "name": desc.Description,
                            "vendor_id": desc.VendorId,
                            "device_id": desc.DeviceId,
                            "dedicated_bytes": desc.DedicatedVideoMemory,
                            "shared_bytes": desc.SharedSystemMemory,
                            "software": bool(desc.Flags & 2),
                        }
                    )
            finally:
                method(adapter, 2)()  # IUnknown::Release
    finally:
        method(factory, 2)()
    return adapters


class WindowsDetector:
    def __init__(self) -> None:
        self.last_raw: dict[str, Any] = {}

    def detect(self) -> HardwareProfile:
        extra_warnings: list[str] = []
        try:
            raw = run_powershell(COLLECT_SCRIPT)
        except Exception as exc:
            raw = {}
            extra_warnings.append(f"System query (PowerShell/CIM) failed: {exc}")

        try:
            registry = read_registry_gpus()
        except Exception as exc:
            registry = []
            extra_warnings.append(f"Registry GPU/VRAM read failed: {exc}")
        try:
            dxgi = read_dxgi_adapters()
        except Exception as exc:
            dxgi = []
            extra_warnings.append(f"DXGI adapter query failed: {exc}")

        self.last_raw = {"wmi": raw, "registry": registry, "dxgi": dxgi}
        profile = build_profile(raw, registry, dxgi)
        profile.warnings.extend(extra_warnings)
        return profile
