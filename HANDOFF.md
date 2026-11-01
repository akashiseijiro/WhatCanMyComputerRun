# WhatCanMyComputerRun: project handoff

Read this first. It was written so that a fresh Claude session (for example Claude desktop on
the Windows machine, which does **not** have the earlier chat history) can pick up the project
with full context. It is a snapshot as of commit `98e08ef` (CI green on Windows and macOS).

Repo: <https://github.com/akashiseijiro/WhatCanMyComputerRun> (public)

---

## 1. What the project is

A Windows desktop tool that:

1. detects the local machine's hardware (desktop, laptop or handheld such as the ROG Ally);
2. looks up a game's system requirements **live** (Steam store API; for non-Steam games an AI
   web search);
3. compares the two and gives a verdict per component plus an overall recommendation
   (**Buy / Buy with compromises / Risky / Don't buy / Can't tell**) with reasons and a
   confidence level;
4. recommends settings (preset, resolution, upscaler, frame generation, rough FPS band, and for
   handhelds power mode, FPS cap, battery notes);
5. optionally gives AI tips for the specific game.

Stack (agreed up front, do not change silently): Python 3.12+, managed with `uv`; FastAPI backend;
a vanilla HTML/CSS/JS single-page UI served by FastAPI and shown in a native window with
pywebview (Edge WebView2), falling back to the default browser; PyInstaller one-folder build;
pytest (with `respx` recorded HTTP so tests never touch the network), `ruff`, `mypy`.

Hard rules from the original brief:

- Development happens on **macOS**; the app runs on **Windows only**. All Windows-only code
  (WMI, winreg, DXGI, PowerShell) is isolated in `hardware/windows.py` and imported lazily, so
  everything else imports and tests on a Mac. A test enforces this.
- `--mock-hardware <profile>` loads a JSON hardware profile so the full flow runs on a Mac.
- **No local game database.** Requirements are fetched live. A short-lived TTL response cache
  (app-data folder) is allowed; it is not a database and is safe to delete.
- Secrets live in `.env` (git-ignored); `.env.example` is committed. **Never commit secrets,
  caches or build output.**
- UI must be handheld friendly: targets of at least 48 px (we use 56), readable on a 7"
  1080p screen, keyboard/Tab navigation with a visible focus ring, Enter submits, dark theme.
- Every hardware detection step fails gracefully (missing field becomes `None` plus a warning,
  never a crash).
- Tests must pass offline on macOS and Windows. Do not silently change the stack, skip a pitfall
  or stub something out; say so.
- After each milestone: summarize what was done, what is verified, and what is **untested on
  real Windows hardware**. Be explicit about that gap.
- Check current Anthropic docs for model names and tool versions rather than relying on memory.
  Model names live in config.

---

## 2. What has been done (milestones 1 to 8, all complete)

| # | Milestone | Result |
|---|---|---|
| 1 | Skeleton, config, CI, mock hardware, `HardwareProfile` schema | `hardware/base.py`, 5 mock profiles, FastAPI app, CI on windows-latest + macos-latest |
| 2 | Windows hardware detection | One PowerShell/CIM call + registry + DXGI collectors, pure parsing layer, handheld table, real-hardware smoke test |
| 3 | Steam search, requirements fetch, parser, cache | Deterministic HTML parser, AI gap-filler, TTL cache, recorded fixtures |
| 4 | Performance resolver, comparison engine, verdicts | AI-scored `PerformanceResolver` (pluggable), weakest-alternative rule, overall recommendation |
| 5 | Settings engine | Rule-based preset/upscaler/frame-gen/FPS/handheld advice, optional AI tips |
| 6 | UI | My System, Search, Report screens; manual hardware picker; loading and error states; Copy report |
| 7 | Non-Steam fallback | Claude web search (`web_search_20250305`) with source URLs shown |
| 8 | Packaging | PyInstaller spec and scripts, CI builds and smoke-tests the `.exe`, README |

Extras added along the way: ROG Ally VRAM assumption (6 GB), manual hardware catalog (2019+
parts), "comparable to" desktop/laptop equivalents, app renamed to WhatCanMyComputerRun, package
renamed to `whatcanmycomputerrun`, score calibration anchors, CI failure annotations.

**State of verification**

- Mac: ruff, mypy, 153 tests passing (2 Windows-only tests skipped on Mac); live Steam + AI flow
  tested with real API calls; built a macOS PyInstaller bundle and ran it.
- CI (GitHub Actions, run `39212068139`): green on `windows-latest` (tests including the real
  hardware smoke test) and `macos-latest`; the **Windows `.exe` builds, starts, serves the bundled
  UI/catalog/demo profile, and runs real detection without crashing**. A CI VM has no real GPU,
  so GPU/VRAM values are not validated by CI.
- **Never yet run on a real Windows PC or an ROG Ally.** That is the next step (milestone 9).

---

## 3. Setting up the Windows machine (what to install)

Open PowerShell (not cmd). Check what you already have first:

```powershell
git --version
uv --version
winget --version
```

Install what is missing:

| Need | Why | Install |
|---|---|---|
| **Git for Windows** | clone/pull/push; includes Git Credential Manager (browser login for GitHub, no token pasting) | `winget install --id Git.Git -e` |
| **uv** | manages Python 3.12 and the virtual env | `winget install --id astral-sh.uv -e` (or `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"`) |
| **Python 3.12** | the app needs 3.12+ | nothing to do: `uv sync` downloads it. (`uv python install 3.12` to do it ahead) |
| **WebView2 runtime** | the native app window | already present on Windows 11 and updated Windows 10. Check *Settings → Apps* for "Microsoft Edge WebView2 Runtime", else `winget install --id Microsoft.EdgeWebView2Runtime -e` |
| **Anthropic API key** | the app's AI features (scoring, parsing, web search, tips) | create at <https://console.anthropic.com/>; needs API credits. A claude.ai/Claude desktop login does **not** work for this |
| Claude desktop | to continue this work on the machine | already installed |

Not needed: Visual Studio Build Tools, Node.js, or a separate Python install (all dependencies
ship Windows wheels for Python 3.12). Close and reopen PowerShell after installing so `PATH`
updates.

Get the code and run it:

```powershell
git clone https://github.com/akashiseijiro/WhatCanMyComputerRun.git
cd WhatCanMyComputerRun
copy .env.example .env          # then edit .env: ANTHROPIC_API_KEY=your-key
uv sync                          # creates .venv, downloads Python 3.12, installs everything
uv run pytest -q                 # should pass (153 passed; Windows runs the 2 smoke tests too)
uv run python -m whatcanmycomputerrun.main --dump-hardware > hardware.json
uv run python -m whatcanmycomputerrun.main      # opens the app window
```

Other useful commands:

```powershell
uv run python -m whatcanmycomputerrun.main --browser          # use the default browser instead
uv run python -m whatcanmycomputerrun.main --mock-hardware ally_z1e   # demo profile
uv run ruff check . ; uv run ruff format --check . ; uv run mypy
powershell -ExecutionPolicy Bypass -File build\build.ps1      # builds dist\WhatCanMyComputerRun\
```

If PowerShell blocks scripts, use `-ExecutionPolicy Bypass` as shown. If `uv`/`git` are "not
recognized", reopen the terminal.

Git identity on this machine (earlier commits were authored as `dev <kurokoaomine741@gmail.com>`):

```powershell
git config user.name "akashiseijiro"
git config user.email "<your GitHub noreply or preferred email>"
```

Pushing works through Git Credential Manager (a browser sign-in pops up the first time). If you
ever use a personal access token instead, it needs **Contents** and **Workflows** write access,
because the repo contains `.github/workflows/ci.yml`.

---

## 4. Do this first on the real hardware (milestone 9 checklist)

Run `--dump-hardware` on **each** machine (the desktop PC and the ROG Ally) and compare against
Task Manager, Settings → System → About and Armoury Crate. The output has `profile` (what the app
decided) and `raw` (WMI, registry and DXGI data). Check:

1. **CPU**: `model`, cores, threads are right.
2. **GPU(s)**: names right; multi-GPU laptops list both; `primary_gpu` logic picks the dGPU.
3. **VRAM**: `vram_mb` should come from the **registry** (`vram_source: "registry"`) or DXGI, not
   WMI (capped at 4 GB). On the Ally it is the BIOS/Armoury Crate iGPU allocation (4 to 8 GB).
   The app then *assumes* 6 GB for the Ally (`vram_assumed: true`, `vram_detected_mb` keeps the
   detected value).
4. **RAM, important unknown**: the code assumes Windows reports RAM **after** the iGPU reservation
   (a 16 GB Ally reports about 12 GB) and adds the reservation back. If the Ally reports 16 GB,
   that add-back double counts by 4 GB. Look at `profile.ram.total_gb` vs the physical 16 GB and
   fix `_effective_ram` in `compare/engine.py` (and `HardwareProfile.equivalents` in
   `hardware/base.py`) if needed. The Ally demo fixtures (`profiles/ally_z1e.json`,
   `ally_x.json`) use the "reported after reservation" assumption (12 and 16 GB); correct them
   with the real values.
5. **Device type**: the Ally should give `device_type: "handheld"`, `handheld_name:
   "ASUS ROG Ally"` (manufacturer `ASUSTeK COMPUTER INC.`, model `ROG Ally RC71L_RC71L`). Model
   codes for the ROG Xbox Ally and Legion Go S in `hardware/handhelds.py` are marked `verify`.
6. **Display** resolution and refresh rate; **storage** free space and SSD/HDD; **OS** build and
   `DirectX 12`.
7. **Warnings** list: any `warnings` entries mean a detection step failed; investigate each.
8. **App window**: the pywebview window opens (WebView2), the UI renders, and a Steam report works
   end to end. If the window is blank, check the console message and WebView2.

Fix detection bugs in `hardware/windows.py` (collectors) and `hardware/windows_parse.py` (pure
parsing, unit-tested), add the real `--dump-hardware` JSON as a fixture under
`tests/fixtures/windows_raw/` and a test, then commit and push.

---

## 5. Architecture quick map

```
whatcanmycomputerrun/
  main.py            entry point, CLI flags, pywebview window (falls back to browser)
  config.py          Settings (.env lookup order, model names, cache dir)
  api/app.py         FastAPI routes
  hardware/
    base.py          HardwareProfile schema, device/GPU enums, get_detector()
    windows.py       Windows-only collectors: PowerShell/CIM, registry VRAM, DXGI (ctypes)
    windows_parse.py PURE parsing of raw collector data into HardwareProfile
    handhelds.py     handheld table (Ally, Ally X, Xbox Ally, Legion Go, MSI Claw), power modes,
                     VRAM assumption (Ally = 6 GB)
    mock.py          loads profiles/*.json for --mock-hardware
    catalog.py/.json manual hardware picker (129 CPUs, 126 GPUs from 2019+, handheld presets)
    equivalents.py   "roughly equal to desktop X / laptop Y" table (editable)
  sources/
    steam.py         store search + appdetails
    web_fallback.py  Claude web search for non-Steam games, source URLs
    cache.py         TTL JSON cache (not a database)
    service.py       GameService: Steam + parse + AI gap fill + web fallback
  parsing/           requirement HTML/text to structured schema (deterministic first, AI fallback)
  compare/
    normalize.py     strip "NVIDIA", "(R)", memory sizes; laptop variants keep a " laptop" tag
    resolver.py      PerformanceResolver interface + ClaudeResolver (batched, cached, anchored)
    engine.py        per-row verdicts, bottleneck, recommendation, confidence
  settings/rules.py  deterministic settings and FPS heuristic; llm_tips.py optional AI tips
  llm/client.py      Anthropic wrapper (structured output, web search, error translation)
  ui/                index.html, app.js, styles.css (no build step; textContent only, no innerHTML)
tests/               unit tests + recorded fixtures (steam/, windows_raw/)
build/               PyInstaller spec + build.ps1/build.sh
.github/workflows/ci.yml   tests on windows+macos; builds and smoke-tests the .exe
```

HTTP API: `GET /api/health`, `GET /api/hardware`, `POST /api/hardware/rescan`,
`GET /api/hardware/catalog`, `POST /api/hardware/manual`, `GET /api/search?q=`,
`GET /api/game/{appid}`, `GET /api/report/{appid}`, `GET /api/web-report?name=&appid=`,
`GET /api/tips/{appid}`.

Settings in `.env` (names are `WHATCANMYCOMPUTERRUN_*`, plus `ANTHROPIC_API_KEY`):
`RESOLVER_MODEL`, `PARSER_MODEL`, `TIPS_MODEL` (default `claude-haiku-4-5`), `SEARCH_MODEL`
(default `claude-sonnet-4-6`; the owner sets Haiku), `CACHE_TTL_HOURS`, `CACHE_DIR`. `.env` is read
from the app-data folder, next to the `.exe`, then the current folder (later wins).

---

## 6. Important design decisions and known guesses

- **Scoring is AI-estimated.** CPU/GPU names cannot be compared as strings, so `ClaudeResolver`
  asks the model for a PassMark-style score (G3D for GPUs, CPU Mark for CPUs), in one batched,
  cached call. Haiku's recall is unreliable, so the prompt carries **calibration anchors**
  (`compare/resolver.py` `SYSTEM`) and a plausibility guard rejects impossible numbers (for
  example an iGPU above 12000). Unscoreable parts become `UNKNOWN`, never a pass. Anchors are
  approximate estimates by the developer; parts without anchors are still guessed.
- **Cache keys are versioned** (`perf:v4:...`). Bump the version whenever scoring prompts change.
- **Requirements with alternatives are compared against the weakest listed option.**
- **Verdict constants** (top of `compare/engine.py`): score margin 5%, RAM 8%, VRAM 10%, "exceeds"
  at 1.5x, "Don't buy" if GPU/CPU is under 50% of the minimum or the OS is below minimum.
- **FPS model is a heuristic**, not a benchmark (`settings/rules.py`): recommended spec is
  assumed to give about 60 FPS at High 1080p, minimum spec about 30 FPS at Low 1080p;
  interpolation, resolution/preset multipliers and a CPU cap. Constants are at the top of the file.
- **iGPU VRAM is shared memory**, shown with a note, never a hard fail. The Ally assumption is 6 GB
  (software adjustable up to 8 GB); table in `hardware/handhelds.py` (`HANDHELD_VRAM`).
- **Owner-supplied calibration:** the Radeon 780M (Ally, Ally X, Legion Go) is equivalent to a
  desktop GTX 1650 and a laptop RTX 2050. Other equivalents in `equivalents.py` are the
  developer's estimates (marked `basis="estimate"`).
- **Handheld power/battery data** for devices other than the Ally is a best guess (`# verify`).
- **Manual catalog** is from memory (core/thread counts, VRAM, years may contain errors) and
  excludes pre-2019 parts by request.
- **Web search** uses the basic tool `web_search_20250305` (no beta header); Haiku 4.5 supports it.
  It may return third-party pages instead of official ones; the report warns when it does.
- **Windows RAM reporting** assumption: see section 4, item 4.

---

## 7. Gotchas learned the hard way

- **Always pass `encoding="utf-8"`** when reading or writing files. Windows defaults to cp1252,
  which broke many tests on the first CI run.
- GitHub **job logs need a sign-in**, but annotations do not: `tests/conftest.py` prints each
  failed test as a `::error` annotation on GitHub Actions, readable via
  `https://api.github.com/repos/akashiseijiro/WhatCanMyComputerRun/check-runs/<job id>/annotations`.
- Keep Windows-only imports **lazy** (`hardware/windows.py` is only imported inside
  `get_detector`); a test fails if any other file imports it or `winreg` at module level.
- `ruff format` is enforced (CI uses `ruff check`; run `uv run ruff format .` before committing).
- mypy runs with `platform = "win32"` so the Windows code is type-checked on a Mac.
- After renaming the package or env vars, local `.env` files need the same rename.
- Git may convert line endings on Windows (CRLF). Nothing relies on LF, but keep
  `build/build.sh` LF if you edit it.
- The frozen `.exe` finds data files through `sys._MEIPASS` (`resources.py`) and the module-relative
  paths in `hardware/mock.py` and `hardware/catalog.py`; new data files must be added to the `datas`
  list in `build/whatcanmycomputerrun.spec`.

---

## 8. Next milestones

Order is a suggestion; items marked **(Windows)** need the real machine.

**Milestone 9: Verify and fix on real hardware (Windows).** Section 4 checklist on the desktop and
the Ally. Record real `--dump-hardware` outputs as fixtures, fix detection bugs, confirm RAM
reporting, VRAM source, handheld identification, window behaviour, `.env` discovery next to the
`.exe`. Download and test the CI-built artifact (`WhatCanMyComputerRun-windows`) as well as
`uv run`.

**Milestone 10: Scoring accuracy.** (a) Build a small static score table for common GPUs/CPUs as
the first source behind the same `PerformanceResolver` interface, with the AI only for the rest;
(b) or offer Sonnet for scoring as the documented default for accuracy; (c) a golden-test corpus:
about 20 popular games across the 5 mock profiles with expected verdict ranges, so scoring or
engine changes show up as test diffs; (d) more "equivalent to" pairs for handheld APUs; (e)
sanity-check ordering across anchors automatically.

**Milestone 11: Windows and handheld polish (Windows).** Windowed (no console) build with an icon
and a log file; check/prompt for WebView2; ROG Ally layout and text size at 1080p/7"; controller
navigation via the browser Gamepad API (D-pad moves focus, A clicks, B back) since desktop mode
only maps the pad to mouse/keyboard; on-screen keyboard behaviour for the search box; fullscreen
option; zip/release packaging.

**Milestone 12: Features.**
- AI tips for web-sourced (non-Steam) games (needs a name-based tips endpoint);
- multi-GPU manual entry (iGPU + dGPU);
- optional "legacy" catalog for pre-2019 parts;
- Steam search cleanup (hide DLC/demos/soundtracks, sort by relevance);
- "what upgrade would fix this?" suggestions;
- compare against another device (for example "what if I buy an Ally X?");
- save/share a report, local history of checked games;
- region-aware pricing;
- verify power modes and battery sizes for Ally X, Legion Go, MSI Claw and the ROG Xbox Ally
  (model codes marked `verify` in `handhelds.py`).

**Milestone 13: Release hygiene.** Version tags and GitHub Releases with the zipped app; bump the
GitHub Actions versions (Node 20 deprecation warnings); optional code signing (the exe is unsigned
so SmartScreen warns: "More info, Run anyway"); update check; decide on rewriting git author
identity (older commits are `dev <kurokoaomine741@gmail.com>`).

---

## 9. Open decisions for the owner

- Search model default: Haiku (cheap, sometimes picks unofficial pages) or Sonnet (better sources)?
- Rewrite git history to the GitHub identity, or leave it?
- Add a pre-2019 "legacy" parts section to the manual catalog?
- Which Windows-only items should come before features (suggested: milestone 9 first)?

---

## 10. How to start a Claude session on the Windows machine

Open the cloned folder in Claude desktop's Code tab and say something like:

> Read HANDOFF.md and CLAUDE.md. Check that my machine has everything in section 3, then do the
> milestone 9 checklist on this PC: run `--dump-hardware`, compare it to what Windows shows, fix
> any detection bugs, add the real output as a test fixture, and commit and push. Tell me what is
> verified and what is not.
