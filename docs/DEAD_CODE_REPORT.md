# Dead Code Elimination — отчёт обнаружения (StormLab)

Дата: 2026-11-28. HEAD: `96bf3c9` (main). Граф пересобран из рабочего дерева (`graphify update .`, `built_at_commit=96bf3c9`).
Baseline: **155 passed, 3 skipped** (в ТЗ указано 154 — зафиксирован фактический результат, файл `graphify-out/baseline.txt`).
Инструменты установлены в `venv` (в `requirements.txt` не добавлялись): ruff 0.17.6, vulture 2.16, pytest-cov 7.x, pytest 9.2.0.
Покрытие до очистки: **71.4 %** (`graphify-out/coverage.json`). Граф до очистки: **761 узел / 1848 рёбер / 34 сообщества**.

## Методика и коды доказательств

| Код | Метод |
|---|---|
| E1 | `ruff check . --select F401,F811,F841 --output-format json` — 17 находок (13 F401, 2 F811, 2 F841) |
| E2 | `vulture . --min-confidence 80` — 11 строк; `--min-confidence 60` — расширенный список |
| E3 | Граф: нулевая внешняя входящая степень узла (`contains`-рёбра исключены) |
| E4 | `grep` по всему корпусу (`.py`, `.md`, `.env.example`, `.git/hooks`), проверка регистраций/декораторов |
| E5 | Coverage: тело функции/метода не выполнялось ни разу (строка `def` исполняется при импорте — не считаем) |
| E6 | AST-обход: def/class без вызывающих; поиск кода после `return`/`raise`; ручной read-просмотр |
| E7 | Инвентаризация файлов/зависимостей (untracked, git ls-files, requirements vs imports) |

Классификация: **DEAD** — ≥2 независимых подтверждения, динамика исключена. **PROBABLY_DEAD** — одно подтверждение/сомнение. **DYNAMIC** — выглядит мёртвым, но вызывается внешне. **KEEP** — публичный API/точка входа/тесты. **CONTRADICTION** — источники расходятся.

---

## F-01..F-16 — Batch A (D2/D3/D9/D12), риск zero

| ID | Локация | Что | Доказательства | Класс |
|---|---|---|---|---|
| F-01 | `ai/ai_analysis.py:2` | `from ai.ai_providers import LocalProvider` | E1 F401; E4 — нет использования и re-export (`from ai.ai_analysis import` только `generate_storm_analysis`) | DEAD |
| F-02 | `ai/ai_providers.py:2` | `import time` | E1 F401; E4 — `time` в файле не встречается | DEAD |
| F-03 | `api.py:1` | `import io` | E1 F401; E4 — нет `io.` в файле | DEAD |
| F-04 | `api.py:10` | `from typing import Optional` | E1 F401; E4 — нет `Optional` в файле | DEAD |
| F-05 | `api.py:17` | `API_TIMEOUT` в импорте из config | E1 F401; E4 — константа используется в `clients/geocoding.py:30` и `clients/openmeteo_api.py:165`, но **не в api.py** (опровержение F-14) | DEAD (только импорт) |
| F-06 | `bot.py:11` | `from telegram.constants import ParseMode` | E1 F401 + E2 (90 %) — два независимых инструмента; E4 — нет `ParseMode` | DEAD |
| F-07 | `bot.py:14` | `from telegram.ext import JobQueue` | E1 F401 + E2 (90 %); E4 — нет `JobQueue` | DEAD |
| F-08 | `clients/geocoding.py:3` | `from functools import lru_cache` | E1 F401 + E2 (90 %); E4 — нет `lru_cache` (файл из незакоммиченных правок) | DEAD |
| F-09 | `clients/openmeteo_api.py:75` | `except Exception as e:` (e не используется, `raise` голый) | E1 F841; E6 — строки 76-81 не обращаются к `e` | DEAD |
| F-10 | `render/skewt_builder.py:234` | `p = np.array(pressures) * units.hPa` | E1 F841; E6 — в теле `_draw_hodograph` (241-280) `p` не используется | DEAD |
| F-11 | `tests/test_batch2.py:12` | `LocalProvider` в импорте | E1 F401; E4 — в файле нет вызовов | DEAD |
| F-12 | `tests/test_batch3a.py:4` | верхний `import sqlite3` | E1 F401 + F811 (переопределён на строке 319); E4 — строки 288 (`am.sqlite3`) и 324 (локальный импорт) вышестоящий импорт не используют | DEAD (верхний; локальный оставить) |
| F-13 | `tests/test_persistence_atomic.py:3` | `import pickle` | E1 F401; E4 — используется `_BotUnpickler` (строки 7, 29) | DEAD |
| F-14 | `tests/test_radar_builder.py:1` | `import io` | E1 F401; E4 — нет `io.` | DEAD |
| F-15 | `tests/test_skewt_builder.py:2`, `:5` | `import metpy.calc as mpcalc`; дубль `import matplotlib.pyplot as plt` | E1 F401 + F811; E4 — `mpcalc` не используется, `plt` импортирован дважды | DEAD |
| F-16 | `=0.25.0`, `=0.28.1`, `=0.9.0`, `=1.7.1`, `=12.3.0` (корень) | лог-артефакты `pip install` | E7 — 5 untracked файлов 0–5 КБ, содержимое «Collecting/Requirement already satisfied» | DEAD (файлы) |
| D9 | — | закомментированный код | E6 — паттерн `# (def|class|import|from|=...)` дал только поясняющие комментарии в `tests/test_effective_layer.py:107,160` | **нет находок** |

---

## F-17..F-28 — Batch B (D1/D6/D8), риск low

| ID | Локация | Что | Доказательства | Класс |
|---|---|---|---|---|
| F-17 | `config.py:66-75` | `FUSION_SIGMA` | E2 (60 %); E4 — только определение + упоминание в `docs/AUDIT.md`; E5 — строка 66 исполняется только при импорте | DEAD |
| F-18 | `config.py:77-81` | `FUSION_DIVERGENCE_WARN_THRESHOLD` | E2 (60 %); E4 — только определение + AUDIT; E5 | DEAD |
| F-19 | `config.py:83` | `RADAR_COOLDOWN = 300` | E2 (60 %); E4 — только определение + AUDIT (F-14); E5 | DEAD |
| F-20 | `config.py:15` | `DEFAULT_CITY` | E2 (60 %); E4 — 0 ссылок во всём корпусе; E5 | DEAD |
| F-21 | `config.py:19-20` | `SOUNDING_STATION_ID`, `SOUNDING_STATION_NAME` | E2 (60 %); E4 — 0 ссылок; fallback-станции захардкожены в `clients/sounding_api.py:_FALLBACK_STATIONS` | DEAD |
| F-22 | `config.py:38-39` | `GEMINI_RETRY_ATTEMPTS`, `GEMINI_RETRY_DELAY` | E2 (60 %); E4 — 0 ссылок; `GEMINI_API_TIMEOUT` при этом используется | DEAD |
| F-23 | `alert_manager.py:38` | `CAPE_GATE = CAPE_FLOOR["warm"]` | E2 (60 %); E4 — 0 ссылок; E5 | DEAD |
| F-24 | `.env.example:39-41` + `README.md:126` | `AITUNNEL_API_KEY/BASE_URL/MODEL` и поясняющая фраза | E4 — `config.py` не читает эти ключи; README прямо говорит «не читаются»; E7 — в `.env` они есть, но кодом не потребляются | DEAD (пример + фраза) |
| D1 | — | код после `return`/`raise` | E6 — AST-обход всех `.py` (кроме venv/graphify-out): **0 находок** | **нет находок** |
| F-25 | `bot.py:714-717` | второй `elif query.data == "skewt"` внутри повторного `if target:` (686-720) | E6 — первый `if target:` (686-706) уже обрабатывает `skewt` с `return`; E5 — ветка 714-717 в тестах не исполнялась; E4 — нет тестов `button_handler` | PROBABLY_DEAD (отложить) |

---

## F-26..F-35 — Batch C (D4/D5/D11), риск medium

| ID | Локация | Что | Доказательства | Класс |
|---|---|---|---|---|
| F-26 | `alert_manager.py:316-322` | `_self_check()` | E4 — только определение и упоминания в README/AUDIT (никем не вызывается); E5 — тело 318-322 не исполнялось; E3; E2 (60 %) | DEAD |
| F-27 | `logging_config.py:100-122` | `setup_banner()` | E4 — 0 ссылок; E5 — тело 112-122 не исполнялось; E3; E2 (60 %) | DEAD |
| F-28 | `bot.py:74-76` | `drop_skewt_ctx()` | E4 — 0 ссылок (не вызывается даже тестами); E5 — тело 75-76 не исполнялось; E3; E2 (60 %) | DEAD |
| F-29 | `clients/radar_api.py:93-100` | `is_radar_available()` | E4 — 0 ссылок; E5 — тело 94-100 не исполнялось; E3; E2 (60 %) | DEAD |
| F-30 | `clients/openmeteo_api.py:216-226` | `OpenMeteoAPI.get_forecast()` | E4 — 0 ссылок; E5 — тело 217-226 не исполнялось; E2 (60 %) | DEAD* |
| F-31 | `clients/openmeteo_api.py:268-275` | `get_precipitation_nowcast()` | E4 — 0 ссылок; E5 — тело 269-275 не исполнялось; E2 (60 %) | DEAD* |
| F-32 | `clients/openmeteo_api.py:277-281` | `clear_cache()` | E4 — 0 ссылок; E5 — тело 278-281 не исполнялось; E2 (60 %) | DEAD* |
| F-33 | `verify_batch1.py` (76 stmts) | legacy-скрипт верификации | E7 — 0 импортёров (dotted-import scan); E5 — coverage 0 % (76/76 пропущено); E4 — нет ссылок в коде/CI | DEAD |
| F-34 | `bot.py:86-87` | `_prune_ctx()` — no-op stub | E4 — 0 ссылок; E2 (60 %); **но** граф сохранил rationale «Kept for backwards compatibility» | CONTRADICTION → отложить |
| F-35 | `core/effective_layer.py:204` | `p_mu` в распаковке `most_unstable_parcel` | E2 (60 %); E6 — `p_mu` не используется дальше (207-214); удаление требует замены на `_`, а не чистого удаления строки | PROBABLY_DEAD (отложить) |

\* F-30..F-32 — публичные методы клиента, но StormLab — приложение, а не библиотека; внешних потребителей в репозитории нет. Перед удалением — обязательный smoke bot/API.

### DYNAMIC / KEEP (удалять запрещено)

- **Telegram handlers** — 10 регистраций `application.add_handler(...)` в `bot.py:832-841` + `add_error_handler` (842): `start`, `storm_command`, `skewt_command`, `radar_command`, `ai_command`, `alert_command`, `unalert_command`, `alerts_command`, `button_handler`, `error_handler`. В графе часть из них имеет нулевую входящую степень — **DYNAMIC, не трогать**.
- **FastAPI routes** — 9 декораторов `@app.get/post` в `api.py:89,231,236,245,271,292,317,342,363` и middleware `require_api_key` (100). **DYNAMIC / публичный API**.
- **JobQueue** — `run_repeating` в `bot.py:845` → `alerts_background_task`. **DYNAMIC**.
- **AI fallback chain** — провайдеры выбираются через `build_provider_chain()`; `OpenAICompatProvider` использует `base_url` для Groq/OpenRouter. **KEEP**.
- **Точки входа** — `bot.py:854 main()`, `api.py:376 uvicorn.run`, `if __name__ == "__main__"`. **KEEP**.
- **Тесты** — fixtures/параметры `cls`, `tz`, `show_alert`, `src`, `dst` (vulture 100 %) являются частью сигнатур `@classmethod`/fake-методов/monkeypatch. **DYNAMIC, false positives**.
- `config._parse_admin_user_ids()` — используется внутри `config.py` (наш grep исключал own-file). **KEEP**.
- `api.py` endpoints, `alert_manager.prune_history()` — вызываются из job по графу. **KEEP**.

---

## F-36..F-40 — Batch D (D7), риск medium

| ID | Пакет | Доказательства | Класс |
|---|---|---|---|
| F-36 | `groq>=1.6.0` | E4 — ни одного `import groq`; `ai/ai_providers.py:320` использует `OpenAI(base_url="https://api.groq.com/openai/v1")`. README называет Groq провайдером — провайдер жив, пакет мёртв | DEAD |
| F-37 | `colorlog>=6.12.0` | E4 — ни одного `import colorlog`; `logging_config.py:37` использует `logging.Formatter`. README:85 устарела | DEAD |
| F-38 | `Cartopy>=0.25.0` | E4 — ни одного `import cartopy`; рендер использует только matplotlib/MetPy | DEAD |
| F-39 | `scipy>=1.14.0` | E4 — прямого импорта нет; scipy приходит транзитивно через MetPy | PROBABLY_DEAD (проверить чистым venv; при падении оставить) |
| F-40 | `pytest`, `pytest-asyncio`, `pytest-cov` в прод-`requirements.txt` | E4 — нужны для самого прогона тестов; отдельного `requirements-dev.txt` в репозитории нет | KEEP (CONTRADICTION F-15 разрешена: замечание верно, но удаление сломает верификацию) |

Используются и остаются: telegram, httpx, metpy, numpy, matplotlib, Pillow, python-dotenv, google-genai, openai, requests, pandas, siphon, fastapi, uvicorn (плюс pytest* как dev-инструмент).

---

## F-41 — Batch E (D10), риск high

| ID | Локация | Что | Доказательства | Класс |
|---|---|---|---|---|
| F-41 | `.opencode/plugins/graphify.js` (3085 Б, tracked) | плагин эпохи OpenCode | E4 — `.git/hooks/*` используют `graphify` CLI, не JS-плагин; `docs/AUDIT.md:191` и `docs/VERIFICATION.md:155` помечают `.opencode/` как «предварительные» артефакты; активная конфигурация — `AGENTS.md` + skills + git-хуки | DEAD |

**Не удалять:** `.claude/` (текущая конфигурация агента, содержит `settings.local.json`, `skills/`, `agents/`) — это не наследие OpenCode. Внутри есть stale-копия `.claude/worktrees/eloquent-moore-db5525/`, но она untracked и относится к локальному окружению, не к репозиторию. Исторические упоминания `.opencode/` в `docs/AUDIT.md`/`docs/VERIFICATION.md` — архивная переписка, **KEEP**.

**Конфликт locale:** `.claude/settings.local.json` содержит allow-правила `Bash(... verify_batch1.py*)`. После удаления `verify_batch1.py` правила становятся безвредными; файл конфигурации не трогаем.

---

## Разрешённые CONTRADICTION-seeds

1. **F-15 (audit) vs README про colorlog** — разрешено grep'ом: colorlog нигде не импортируется, `logging_config.py` использует stdlib `logging.Formatter`. Аудит прав, README устарела → F-37 DEAD.
2. **Groq «провайдер №1» vs отсутствие пакета groq** — провайдер жив через OpenAI-совместимый клиент (`ai_providers.py:320`), пакет `groq` не используется → F-36 DEAD, провайдер KEEP.
3. **F-14: `API_TIMEOUT` мёртв?** — константа жива в geocoding/openmeteo, мёртв только импорт в `api.py` → F-05 (DEAD import), константа KEEP.
4. **F-14: `FUSION_SIGMA`, `RADAR_COOLDOWN`** — подтверждено E2+E4 → F-17/F-19 DEAD; `docs/AUDIT.md` упоминает их как историческую находку, это не использование.
5. **`_self_check()` «используется тестами» (docstring) vs реальность** — grep по тестам дал 0 вызовов, coverage тела 0 → F-26 DEAD.
6. **`_prune_ctx()` rationale «kept for backwards compatibility» vs 0 вызывающих** — источники расходятся → F-34 CONTRADICTION, отложен.

## Итог находок и статус

- DEAD: F-01…F-24, F-26…F-33, F-36…F-38, F-41, F-16 → **36 finding** (включая 5 файлов-артефактов).
- PROBABLY_DEAD / отложено: F-25, F-34, F-35, F-39 → **4 finding**.
- KEEP / DYNAMIC: handlers, routes, JobQueue, AI-провайдеры, тестовые сигнатуры, pytest*, `.claude/` → **не удалять**.
- D1 и D9: находок нет.

Дальше — `PLAN.md`. Удаления начнутся только после одобрения плана.
