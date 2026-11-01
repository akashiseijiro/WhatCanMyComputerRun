# Build the Windows .exe (one-folder). Run from anywhere:  powershell -File build\build.ps1
# Add -NoConsole for a build without a console window (only once everything works).
param([switch]$NoConsole, [switch]$EmbedKeyFromDotenv, [switch]$OneFile)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if ($NoConsole) { $env:WCMCR_NOCONSOLE = "1" }
# -OneFile: build one self-contained dist\WhatCanMyComputerRun.exe to hand to people.
if ($OneFile) { $env:WCMCR_ONEFILE = "1" }
uv sync --python 3.12

# Release build: bake a Gemini key into the exe so users need no setup. The key comes from the
# GEMINI_API_KEY environment variable (or -EmbedKeyFromDotenv reads it from .env). The generated
# module is git-ignored and removed after the build. Anyone can extract an embedded key from the
# exe, so use a free-tier key with no billing attached.
$embedded = "whatcanmycomputerrun\_embedded.py"
$key = $env:GEMINI_API_KEY
if (-not $key -and $EmbedKeyFromDotenv -and (Test-Path .env)) {
    $line = Get-Content .env -Encoding utf8 | Where-Object { $_ -match '^\s*GEMINI_API_KEY\s*=' } | Select-Object -First 1
    if ($line) { $key = ($line -split '=', 2)[1].Trim() }
}
if ($key) {
    Set-Content -Path $embedded -Value "GEMINI_API_KEY = '$key'" -Encoding ascii
    Write-Host "Embedding a Gemini key in this build."
}
try {
    uv run pyinstaller build/whatcanmycomputerrun.spec --noconfirm --workpath build/work --distpath dist
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
} finally {
    if (Test-Path $embedded) { Remove-Item $embedded -Force }
}
if ($OneFile) {
    Write-Host "Built: dist\WhatCanMyComputerRun.exe (single file)"
} else {
    Write-Host "Built: dist\WhatCanMyComputerRun\WhatCanMyComputerRun.exe"
}
if (-not $key) { Write-Host "No key embedded: put a .env next to the .exe (copy .env.example, add a key)." }
