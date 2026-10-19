#!/usr/bin/env bash
# Build for the current OS (the real deliverable is the Windows .exe; this validates the spec).
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --python 3.12
uv run pyinstaller build/whatcanmycomputerrun.spec --noconfirm --workpath build/work --distpath dist
echo "Built: dist/WhatCanMyComputerRun/"
