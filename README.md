# CanIRunIt

Game compatibility checker for Windows PCs and handhelds (ROG Ally etc.). Work in progress; full setup and build instructions arrive in milestone 8.

## Develop on macOS (mock hardware)

```bash
uv sync
uv run python -m canirunit.main --mock-hardware ally_z1e --browser
uv run pytest
```

Bundled profiles: `ally_z1e`, `ally_x`, `desktop_rtx3060`, `laptop_igpu_lowend`, `desktop_high_end`.
