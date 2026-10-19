# Build the Windows .exe (one-folder). Run from anywhere:  powershell -File build\build.ps1
# Add -NoConsole for a build without a console window (only once everything works).
param([switch]$NoConsole)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if ($NoConsole) { $env:WCMCR_NOCONSOLE = "1" }
uv sync --python 3.12
uv run pyinstaller build/whatcanmycomputerrun.spec --noconfirm --workpath build/work --distpath dist
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Write-Host "Built: dist\WhatCanMyComputerRun\WhatCanMyComputerRun.exe"
Write-Host "Put your .env next to the .exe (copy .env.example and add your API key)."
