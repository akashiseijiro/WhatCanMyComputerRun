# -*- mode: python ; coding: utf-8 -*-
# One-folder PyInstaller build. Run via build/build.ps1 (Windows) or build/build.sh (any OS).
# Set WCMCR_NOCONSOLE=1 to build without a console window (errors then go nowhere: debug first).
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
PKG = ROOT / "whatcanmycomputerrun"
DEST = "whatcanmycomputerrun"

datas = [
    (str(PKG / "ui"), f"{DEST}/ui"),
    (str(PKG / "hardware" / "catalog.json"), f"{DEST}/hardware"),
    (str(PKG / "hardware" / "profiles"), f"{DEST}/hardware/profiles"),
]
datas += collect_data_files("certifi")  # CA bundle for httpx / anthropic

hiddenimports = collect_submodules("uvicorn")
hiddenimports += ["whatcanmycomputerrun.hardware.windows", "winreg"]  # imported lazily
hiddenimports += collect_submodules("webview")  # empty where pywebview is not installed
if (PKG / "_embedded.py").exists():  # written by build.ps1 when GEMINI_API_KEY is set
    hiddenimports += ["whatcanmycomputerrun._embedded"]

a = Analysis(
    [str(ROOT / "build" / "entry.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "mypy", "ruff"],
)
pyz = PYZ(a.pure)
console = os.environ.get("WCMCR_NOCONSOLE") != "1"
if os.environ.get("WCMCR_ONEFILE") == "1":
    # One self-contained .exe to hand to people (unpacks to a temp folder on each start).
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [], name="WhatCanMyComputerRun", console=console
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="WhatCanMyComputerRun",
        console=console,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="WhatCanMyComputerRun")
