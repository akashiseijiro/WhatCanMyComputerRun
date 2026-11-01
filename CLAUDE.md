# WhatCanMyComputerRun: notes for Claude

**Read `HANDOFF.md` first.** It has the full history, what to install on Windows, the real-hardware
verification checklist, design decisions, gotchas and the next milestones.

Essentials:

- Python 3.12 with `uv`. Setup: `uv sync`. Checks before every commit:
  `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`.
- App entry: `uv run python -m whatcanmycomputerrun.main` (`--mock-hardware ally_z1e`,
  `--browser`, `--no-ui`, `--dump-hardware`).
- The app is Windows-only; Windows-only code lives in `whatcanmycomputerrun/hardware/windows.py`
  and must stay lazily imported. Parsing of raw Windows data is pure and unit-tested in
  `hardware/windows_parse.py`.
- Always pass `encoding="utf-8"` when reading or writing files (Windows defaults to cp1252).
- Secrets go in `.env` (git-ignored). Never commit keys, caches or build output.
- No local game database: requirements are fetched live; the cache is disposable.
- Tests must pass offline (recorded HTTP via respx, stubbed AI).
- Do not silently change the stack, skip a pitfall or stub something out. After each milestone,
  say what is verified and what is untested on real Windows hardware.
- Check current Anthropic docs for model names and tool versions; keep model names in config.
- Commit messages: clear, one milestone or fix per commit. Push triggers CI (Windows + macOS +
  exe build); failed tests appear as annotations via the GitHub API.
