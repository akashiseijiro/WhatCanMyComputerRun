# WhatCanMyComputerRun

Find out whether your Windows PC, laptop or handheld (ROG Ally, Legion Go, MSI Claw…) can run a
game, and at what settings, before you buy it.

It detects your hardware, looks up the game's system requirements live (Steam first, then an AI
web search for games that aren't on Steam), compares the two, and tells you:

- a verdict per component (GPU, CPU, RAM, VRAM, storage, OS, DirectX) and an overall
  recommendation: **Buy / Buy with compromises / Risky / Don't buy**, with reasons and a
  confidence level (unknowns are never shown as a pass);
- recommended settings: graphics preset, resolution, upscaler (DLSS / FSR / XeSS), frame
  generation, a rough FPS range, and, on handhelds, power mode, FPS cap and battery notes;
- optional AI tips for the specific game.

> **Be aware:** CPU/GPU comparisons use AI-estimated PassMark-style scores, and the FPS range is a
> heuristic. They are good for "will it run?", not for close calls or exact frame rates. The app
> labels estimates and shows its sources.

## Quick start on Windows

You need Windows 10/11 (the WebView2 runtime ships with Windows 11 and most updated Windows 10).

### Option A: the built app (no Python needed)

1. On GitHub open **Actions → the latest green run → Artifacts → `WhatCanMyComputerRun-windows`**
   and unzip it.
2. Copy `.env.example` (from this repo) next to `WhatCanMyComputerRun.exe`, rename it to `.env`,
   and put your Anthropic API key in it (see [API key](#api-key)).
3. Double-click `WhatCanMyComputerRun.exe`. A console window opens (useful for errors) together
   with the app window.

### Option B: run from source

```powershell
winget install --id astral-sh.uv        # one-time; or see https://docs.astral.sh/uv/
git clone https://github.com/akashiseijiro/WhatCanMyComputerRun.git
cd WhatCanMyComputerRun
copy .env.example .env                  # then edit .env and add your key
uv sync
uv run python -m whatcanmycomputerrun.main
```

`uv` downloads Python 3.12 for you. Use `git pull` + `uv sync` to update later.

## API key

AI features (hardware scoring, parsing odd requirement lists, web search, tips) use the
Anthropic API. Get a key at <https://console.anthropic.com/>, then put it in `.env`:

```
ANTHROPIC_API_KEY=your-key-here
```

`.env` is git-ignored. The app looks for it, in this order (later wins): your app-data folder
(`%LOCALAPPDATA%\WhatCanMyComputerRun\.env`), next to the `.exe`, then the current folder.
Never commit or share it.

Without a key, hardware detection, Steam lookups and requirement parsing still work, but
CPU/GPU comparisons are shown as **unknown**.

Models and cost: by default everything uses the cheapest model (`claude-haiku-4-5`). A new game
costs roughly a cent or two of AI calls; scores are cached (30 days) so repeats are free. Web
search for non-Steam games adds about $0.01 per search. Settings in `.env`
(see `.env.example`):

| Setting | Default | Used for |
|---|---|---|
| `WHATCANMYCOMPUTERRUN_RESOLVER_MODEL` | `claude-haiku-4-5` | CPU/GPU performance scores |
| `WHATCANMYCOMPUTERRUN_PARSER_MODEL` | `claude-haiku-4-5` | Reading odd requirement text |
| `WHATCANMYCOMPUTERRUN_SEARCH_MODEL` | `claude-sonnet-4-6` | Web search for non-Steam games |
| `WHATCANMYCOMPUTERRUN_TIPS_MODEL` | `claude-haiku-4-5` | Game-specific tips |
| `WHATCANMYCOMPUTERRUN_CACHE_TTL_HOURS` | `24` | Steam/response cache lifetime |
| `WHATCANMYCOMPUTERRUN_CACHE_DIR` | app-data folder | Where the cache lives |

If scores look wrong, try `WHATCANMYCOMPUTERRUN_RESOLVER_MODEL=claude-sonnet-4-6`.

## Using it

1. **My System**: your detected hardware, with a device badge and anything that couldn't be
   detected. "Comparable to" lines show what parts roughly equal in desktop/laptop terms.
   **Re-scan** re-detects.
2. **Search**: type a game; pick it from the results. Not on Steam? Choose **Search the web for
   requirements**.
3. **Report**: verdicts, recommendation, settings, sources, and **Copy report**.

**Detection didn't work (or you want to try another machine)?** On My System choose **Choose
hardware manually**: pick the device type (or a handheld preset), CPU, GPU, RAM, screen,
storage and Windows version from a catalog of parts from 2019 onwards.

**Controller / handheld:** targets are large and everything is keyboard-navigable (Tab,
Shift+Tab, Enter) with a visible focus ring. On an ROG Ally, use Desktop mode / the
controller's mouse emulation.

**ROG Ally graphics memory:** it is a software setting (e.g. 4 → 6 → 8 GB). Reports assume **6 GB**
and tell you what to set in Armoury Crate.

## Run on macOS (development, demo hardware)

The app is Windows-only, but everything except real hardware detection runs on a Mac using demo
hardware profiles:

```bash
uv sync
uv run python -m whatcanmycomputerrun.main --mock-hardware ally_z1e --browser
```

Profiles: `ally_z1e`, `ally_x`, `desktop_rtx3060`, `desktop_high_end`, `laptop_igpu_lowend`.

| Flag | Meaning |
|---|---|
| `--mock-hardware <name or .json path>` | Use a demo/fixture profile instead of scanning |
| `--browser` | Open the default browser instead of a native window |
| `--no-ui` | Serve the API only |
| `--port N` | Fixed port (default: a random free one) |
| `--dump-hardware` | Print detected hardware (and raw WMI/registry/DXGI data) as JSON, then exit |

**If automatic detection looks wrong, run `--dump-hardware` on that machine and share the JSON.**

## Build the `.exe`

On Windows (PyInstaller one-folder build):

```powershell
powershell -File build\build.ps1          # add -NoConsole to hide the console window
```

Result: `dist\WhatCanMyComputerRun\WhatCanMyComputerRun.exe`. Copy your `.env` next to it. Zip
the whole folder to move it to another PC. CI also builds and smoke-tests it on every push
(download it from the run's **Artifacts**). `build/build.sh` builds for the current OS (used to
validate the spec on a Mac).

## Where things are stored

- **Cache**: `%LOCALAPPDATA%\WhatCanMyComputerRun\cache` (macOS:
  `~/Library/Application Support/WhatCanMyComputerRun/cache`). It is only speed/rate-limit
  caching, not a database, and is safe to delete.
- **Manual hardware choice**: remembered in the app window's local storage.
- Nothing else is written. No game database is shipped; requirements are fetched live.

## Privacy

Game names and your CPU/GPU model names are sent to the Anthropic API (scoring, parsing, web
search, tips) and game names to the Steam store API. Nothing else about your machine leaves it.

## Development

```bash
uv run pytest            # all tests run offline (recorded Steam data, stubbed AI)
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

CI (`.github/workflows/ci.yml`) runs lint, types and tests on `windows-latest` and
`macos-latest` (including a real hardware-detection smoke test on Windows), and builds the
Windows app.

```
whatcanmycomputerrun/
  hardware/   detection (windows.py, windows_parse.py), mock profiles, manual catalog, handhelds
  sources/    Steam client, web-search fallback, response cache
  parsing/    requirement HTML/text parsing + schemas
  compare/    name normalization, performance resolver (AI), verdict engine
  settings/   rule-based settings engine, AI tips
  llm/        Anthropic client wrapper
  api/        FastAPI routes      ui/   the HTML/JS/CSS front end
  main.py     entry point (window, CLI flags)
tests/        unit tests + recorded fixtures      build/   PyInstaller spec + scripts
```

## Troubleshooting

- **A blank window or "native window unavailable":** the WebView2 runtime is missing. Install
  the Evergreen runtime from Microsoft; meanwhile the app falls back to your browser.
- **"AI features unavailable" / scores show unknown:** `ANTHROPIC_API_KEY` is missing or wrong in
  `.env`. The banner at the top of the app tells you.
- **Steam errors:** you may be offline or rate limited; wait a minute and retry.
- **Wrong hardware:** use **Choose hardware manually**, and send the `--dump-hardware` output.
- **Port in use:** pass `--port 8765`.

## Known limits

- Real Windows detection and the Windows window were written without access to a Windows
  machine; CI exercises them, but treat the first runs on real hardware as testing.
- Pre-2019 parts aren't in the manual catalog (the 2019+ rule); add them to
  `whatcanmycomputerrun/hardware/catalog.json` if needed.
- Handheld power modes and battery sizes for devices other than the ROG Ally are best guesses.
