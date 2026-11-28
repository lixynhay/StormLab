---
name: stormlab-dev
description: Engineering guardrails, SPC meteorological formula pins, async/render rules, and verification checklists for StormLab. Use whenever editing stormlab/core/storm_indices.py, stormlab/core/effective_layer.py, core/season_regime.py, render/*, bot.py, api.py, or stormlab/alert_manager.py.
---

# StormLab Engineering Guardrails & Verification

## 1. Hard Architectural Invariants
- **Environment**: Always use the project virtualenv (`venv\Scripts\python.exe` on Windows, `venv/bin/python` on POSIX) — never global Python.
- **Graphify**: NEVER read `graphify-out/graph.json` directly. Use `graphify-out/GRAPH_REPORT.md` for architecture overview and `graphify query` / `graphify explain` / `graphify path` CLI commands for targeted lookups.
- **Async & Rendering (`stormlab/bot.py`, `stormlab/api.py`, `render/*`)**:
  - Never run synchronous Matplotlib/PIL rendering or blocking HTTP I/O directly inside `async def` handlers — always offload via `await asyncio.to_thread(...)`.
  - Always close Matplotlib figures inside a `finally:` block (`plt.close(fig)`).
  - RainViewer live tile URLs (`stormlab/render/radar_builder.py`) must include explicit `size`, `color`, and `options` parameters to prevent `"Zoom Level Not Supported"`.
- **Security (`stormlab/bot.py`, `stormlab/api.py`)**:
  - Validate `API_ACCESS_KEY` using `hmac.compare_digest`; fail-closed (`401`) if empty/unset.
  - Never expose raw exception details (`detail=str(e)`) in HTTP 500 responses.
  - Apply `escape_markdown()` only to dynamic user/API strings in `stormlab/bot.py`; validate `time_idx` and `wmo` callback parameters.

## 2. SPC Meteorological Formula Pins (`core/`)
Do not alter these verified SPC definitions without updating unity and discriminating pin-tests:
- **Effective Inflow Layer (`effective_layer.py`)**: Contiguous layer where parcel `CAPE >= 100` **AND** `CIN >= -250`.
- **EBWD**: Bulk shear measured from `base` to **50% of EL height** (`0.5 * EL`), NOT full EL.
- **Fixed-layer STP (`calculate_stp`)**: Uses `sbCAPE`, `sbLCL`, `SRH 0-1 km`, `6BWD` (`< 12.5 m/s -> 0`, `> 30 m/s -> cap 1.5`). Contains **NO CIN term**.
- **Effective STP (`stp_effective`)**: Uses `mlCAPE`, `mlLCL`, `mlCIN`, `ESRH`, `EBWD`; forced to `0.0` when effective inflow base is above ground.
- **Effective SCP (`scp_effective`)**: Uses `muCAPE`, `ESRH` (normalized to 100), `EBWD` (lower bound `10 m/s`, cap `1.0` at `> 20 m/s`), and CIN term `(-40 / muCIN)` capped at `1.0` for `muCIN >= -40`.

## 3. Mandatory Verification Workflow
Run these checks via the project venv after any code modification:

1. **Core & Regression Suite**: `venv\Scripts\python.exe -m pytest -q tests/` (POSIX: `venv/bin/python -m pytest -q tests/`). The legacy `verify_batch1.py` script was removed; the full pytest suite is the canonical verification.

2. **Task-Specific Checklists**:
   - **SPC Formula Change**: Verify all sub-terms, unity pins (`ESRH=100`, `EBWD=10`, `STP_eff=1.0`, `SCP_eff=4.5`), and discriminating pins (`CIN=-300 -> None`, `EL=8000 -> 4000m`, `6BWD=10 -> fixed STP=0`).
   - **Season / Alert Threshold Change**: Verify both `warm` and `cool` regimes (including Southern Hemisphere month inversion) and SQLite schema in `data/alerts.db`.
   - **Chart / Radar Render Change**: Run `tests/test_skewt_builder.py` and `tests/test_radar_builder.py`, and verify `plt.close(fig)` cleanup.

Используйте код с осторожностью.
