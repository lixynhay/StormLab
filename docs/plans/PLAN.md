# PLAN.md — Dead Code Elimination (батчи A→E)

Статус: **ОЖИДАЕТ ОДОБРЕНИЯ ОПЕРАТОРА**. Удаления не выполнялись.
Основание: `docs/DEAD_CODE_REPORT.md`. Baseline: **155 passed, 3 skipped**, coverage 71.4 %, граф 761 узел / 1848 рёбер (`graphify update .`, commit `96bf3c9`).
Правило: один батч = один коммит = полный `pytest -q`. Только удаления, никаких рефакторингов.

## Предусловие (блокер перед батчем A)

В рабочем дереве лежат **незакоммиченные правки оператора** (не мои):
`alert_manager.py`, `clients/geocoding.py`, `clients/sounding_api.py`, `core/storm_indices.py`
(в последнем — переименование параметров `calculate_stp` и ветка `sbLCL < 1000`; зона SPC-пинов).

`git add -A` из ТЗ захватит их в первый же dead-code коммит. Перед стартом выбрать одно:

1. **Рекомендуется:** `git stash push -m "operator WIP" -- alert_manager.py clients/geocoding.py clients/sounding_api.py core/storm_indices.py`, выполнить батчи A–E, затем `git stash pop` (конфликтов не ожидается: батчи трогают другие строки, кроме `alert_manager.py:38` и `clients/geocoding.py:3` — при конфликте решить вручную).
2. Закоммитить WIP оператора отдельным коммитом до батча A (тогда diff батчей останется чистым).
3. Использовать path-scoped `git add <файлы батча>` вместо `git add -A` (WIP останется незакоммиченным между батчами).

Без выбора одного из трёх батч A **не стартует**.

---

## Батч A — D2/D3/D9/D12 · риск zero

Удалить строго следующие строки (только импорты/переменные/файлы):

| Файл | Строки | Удаление |
|---|---|---|
| `ai/ai_analysis.py` | 2 | `from ai.ai_providers import LocalProvider` |
| `ai/ai_providers.py` | 2 | `import time` |
| `api.py` | 1, 10, 17 | `import io`; `from typing import Optional`; `API_TIMEOUT` из импорта config |
| `bot.py` | 11, 14 | `from telegram.constants import ParseMode`; `JobQueue` из импорта telegram.ext |
| `clients/geocoding.py` | 3 | `from functools import lru_cache` |
| `clients/openmeteo_api.py` | 75 | `as e` → `except Exception:` (удалить только связывание имени) |
| `render/skewt_builder.py` | 234 | строка `p = np.array(pressures) * units.hPa` |
| `tests/test_batch2.py` | 12 | `LocalProvider` из импорта |
| `tests/test_batch3a.py` | 4 | верхний `import sqlite3` (локальный на 319 оставить) |
| `tests/test_persistence_atomic.py` | 3 | `import pickle` |
| `tests/test_radar_builder.py` | 1 | `import io` |
| `tests/test_skewt_builder.py` | 2, 5 | `import metpy.calc as mpcalc`; дубль `import matplotlib.pyplot as plt` |
| корень | — | `Remove-Item =0.25.0, =0.28.1, =0.9.0, =1.7.1, =12.3.0` (untracked) |

D9 — удалять нечего (comments-only). `bot.log` уже в `.gitignore`, ACTION не требуется.

**Evidence:** F-01…F-16 отчёта; каждый импорт подтверждён ruff F401/F811/F841 + grep.
**Верификация:** `pytest -q` (≥155), `ruff check . --select F401,F841` (0 находок в перечисленных файлах), `git commit -m "chore(dead-code): batch A — unused imports, locals and junk files"`.

## Батч B — D1/D6/D8 · риск low

| Файл | Строки | Удаление |
|---|---|---|
| `config.py` | 15 | `DEFAULT_CITY` |
| `config.py` | 19-20 | `SOUNDING_STATION_ID`, `SOUNDING_STATION_NAME` |
| `config.py` | 38-39 | `GEMINI_RETRY_ATTEMPTS`, `GEMINI_RETRY_DELAY` |
| `config.py` | 66-75 | `FUSION_SIGMA` (весь dict) |
| `config.py` | 77-81 | `FUSION_DIVERGENCE_WARN_THRESHOLD` (весь dict) |
| `config.py` | 83 | `RADAR_COOLDOWN` |
| `alert_manager.py` | 38 | `CAPE_GATE = CAPE_FLOOR["warm"]` |
| `.env.example` | 39-41 | `AITUNNEL_API_KEY/BASE_URL/MODEL` |
| `README.md` | 126 | фраза про зарезервированные AiTunnel-переменные |

D1 — AST-проверка дала 0 недостижимых блоков, удалений нет.
**F-25 (`bot.py:714-717`) НЕ входит в батч** — PROBABLY_DEAD, отложен.

**Evidence:** F-17…F-24 (vulture 60 % + grep по корпусу + coverage). `API_TIMEOUT` и `GEMINI_API_TIMEOUT` остаются (используются).
**Верификация:** `pytest -q` (≥155), `grep -rn "FUSION_SIGMA\|RADAR_COOLDOWN\|AITUNNEL" --include="*.py" --include="*.example" --include="*.md"` → только исторические упоминания в `docs/AUDIT.md`, `git commit -m "chore(dead-code): batch B — unused config constants and env placeholders"`.

## Батч C — D4/D5/D11 · риск medium

| Файл | Строки | Удаление |
|---|---|---|
| `alert_manager.py` | 316-322 | `_self_check()` (zombie, 0 вызовов, coverage тела 0) |
| `logging_config.py` | 100-122 | `setup_banner()` |
| `bot.py` | 74-76 | `drop_skewt_ctx()` |
| `clients/radar_api.py` | 93-100 | `is_radar_available()` |
| `clients/openmeteo_api.py` | 216-226 | `get_forecast()` |
| `clients/openmeteo_api.py` | 268-275 | `get_precipitation_nowcast()` |
| `clients/openmeteo_api.py` | 277-281 | `clear_cache()` |
| `verify_batch1.py` | весь файл | `git rm verify_batch1.py` |

**Запрещено трогать** в этом батче: `bot.py:86-87 _prune_ctx()` (CONTRADICTION F-34), `core/effective_layer.py:204 p_mu` (F-35), все handler/route/job/provider (раздел DYNAMIC отчёта).

**Evidence:** F-26…F-33 — grep 0 ссылок + coverage тела 0 + (для F-26/27/28/29) graph zero in-degree + vulture 60 %.
**Верификация:** `pytest -q` (≥155), smoke `python -X dev -c "import bot, api"`, `python bot.py` (старт, JobQueue без падения), `python api.py` + `GET /api/health`, `git commit -m "chore(dead-code): batch C — unreferenced helpers and legacy verifier"`.

## Батч D — D7 · риск medium

`requirements.txt` — удалить только:
- `groq>=1.6.0` (F-36: провайдер работает через OpenAI-совместимый клиент)
- `colorlog>=6.12.0` (F-37: stdlib `logging`)
- `Cartopy>=0.25.0` (F-38: нет импортов)
- `scipy>=1.14.0` — **условно** (F-39): сначала проверить чистый venv; если `metpy` не тянет scipy и падает импорт — оставить и задокументировать.

`pytest*`, `pytest-asyncio`, `pytest-cov` **оставить** (F-40 — нужны для верификации, отдельного requirements-dev нет).

**Верификация (обязательная по ТЗ):**
1. `python -m venv C:\Users\Никита\AppData\Local\Temp\stormlab-clean`
2. `...\Scripts\pip install -r requirements.txt`
3. `...\Scripts\python -m pytest -q` (≥155)
4. `...\Scripts\python bot.py` — старт без падений; `...\Scripts\python api.py` + `/api/health` → 200
5. `git commit -m "chore(dead-code): batch D — drop unused runtime dependencies"`

## Батч E — D10 · риск high

- `git rm .opencode/plugins/graphify.js` (F-41: хуки используют `graphify` CLI; active config — `AGENTS.md` + skills).
- **Не удалять:** `.claude/`, исторические упоминания `.opencode/` в `docs/AUDIT.md` / `docs/VERIFICATION.md`, `.mcp.json`, `AGENTS.md`.

**Верификация:** `grep` по `.git/hooks`, `AGENTS.md`, `.mcp.json`, `.claude/` на `graphify.js` → 0 ссылок; `pytest -q`; `git commit -m "chore(dead-code): batch E — remove stale OpenCode plugin"`.

---

## После всех батчей (Фаза 4)

1. `git diff <baseline>..HEAD` — только удаления (плюс requirements).
2. `pytest -q` ≥155, coverage ≥71.4 % (ожидается рост).
3. Smoke bot + API + `/storm`, `/radar` (живьём требует токен/сеть — если недоступно, честно зафиксировать как не проверенное).
4. `graphify . --update` — ожидаемое уменьшение числа узлов; dangling-рёбра не должны вырасти.
5. Сверить DYNAMIC-вердикты: handlers/routes/job/providers остались на месте.

## Ожидаемый эффект

- Удалено: ~14 импортов, 2 локальные переменные, 8 констант, 7 функций/методов, 1 модуль, 1 плагин, 5 мусорных файлов, 3 зависимости (scipy — условно).
- Файлов удалено полностью: `verify_batch1.py`, `.opencode/plugins/graphify.js`, `=*.0` ×5.
- Граф: 761 узел → ожидается ~735–745 (точная цифра после `--update`).
