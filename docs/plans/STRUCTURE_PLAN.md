# STRUCTURE_PLAN — реорганизация файловой структуры (architect)

Статус: **ОЖИДАЕТ ОДОБРЕНИЯ**. Реализация батчей A–D после одобрения.

## Baseline (зафиксирован ДО)

| Метрика | Значение |
|---|---|
| Ветка / HEAD | `main` @ `e512d6d`, рабочее дерево чистое |
| pytest | **159 passed, 3 skipped** |
| coverage | **73.64 %** (`graphify-out/coverage_structure.json`) |
| ruff F401/F841 | **0** |
| Корневые `.py` | **7** (без `#!`: все модули, включая bot/api) |
| Граф | ~859 узлов, import cycles: none |

---

## Фаза 0 — Inventory

### 0.1 Таблица перемещений (git mv для tracked)

| Источник | Целевой путь | Комментарий |
|---|---|---|
| `alert_manager.py` | `stormlab/alert_manager.py` | `DB_PATH` → `paths.DATA_DIR` |
| `config.py` | `stormlab/config.py` | `LOG_FILE` → `paths.LOGS_DIR / "bot.log"`; `load_dotenv()` оставляем как есть |
| `logging_config.py` | `stormlab/logging_config.py` | `cwd` git-команды → `PROJECT_ROOT` |
| `persistence.py` | `stormlab/persistence.py` | без path-зависимостей |
| `rate_limiter.py` | `stormlab/rate_limiter.py` | без path-зависимостей |
| `bot.py` | `stormlab/bot.py` | `data/` → `DATA_DIR`; `if __name__ == "__main__"` уходит в wrapper |
| `api.py` | `stormlab/api.py` | `Path(__file__).parent/"docs"` → `PROJECT_ROOT/"docs"`; добавить `main()` |
| `core/` (5 .py) | `stormlab/core/` | + `__init__.py` |
| `clients/` (6 .py) | `stormlab/clients/` | + `__init__.py` |
| `render/` (3 .py) | `stormlab/render/` | + `__init__.py` |
| `ai/` (2 .py) | `stormlab/ai/` | + `__init__.py` |
| `PLAN.md` | `docs/plans/PLAN.md` | прошлая версия плана |
| `docs/F06_FIX_PLAN.md` | `docs/plans/F06_FIX_PLAN.md` | рабочий план |
| `bot.log` (untracked) | `logs/bot.log` | обычный `Move-Item`, не `git mv` |
| **новый** | `stormlab/__init__.py`, `stormlab/paths.py`, `logs/`, `docs/plans/` | — |
| **остаются в корне** | `bot.py`, `api.py` (тонкие wrapper'ы) + `AGENTS.md`, `README.md`, `requirements.txt`, `.env*`, `.gitignore`, `.gitattributes`, `.mcp.json` | — |

Остальные каталоги не двигаются: `tests/`, `scripts/`, `agents/`, `skills/`, `data/`, `graphify-out/`, `venv/`, `.claude/`, `.opencode/`.

### 0.2 Аудит резолвинга путей — КРИТИЧНО

| Файл:строка | Сейчас | После переезда | Действие |
|---|---|---|---|
| `config.py:56` | `LOG_FILE = "bot.log"` | cwd-зависимый путь, лог упадёт не в `logs/` | `LOG_FILE = str(LOGS_DIR / "bot.log")` |
| `config.py:5` | `load_dotenv()` | ищет `.env` от cwd; при запуске из корня поведение то же | **НЕ трогать** ( нулевое изменение поведения ) |
| `alert_manager.py:24` | `DB_PATH = Path("data/alerts.db")` | cwd-зависимый | `DB_PATH = DATA_DIR / "alerts.db"`; `init_db()` уже делает `DB_PATH.parent.mkdir(...)` |
| `bot.py:797` | `os.makedirs("data", exist_ok=True)` | cwd-зависимый | `DATA_DIR.mkdir(parents=True, exist_ok=True)` |
| `bot.py:798` | `persistence_path = "data/persistence.pkl"` | cwd-зависимый | `persistence_path = str(DATA_DIR / "persistence.pkl")` |
| `api.py:108` | `Path(__file__).parent / "docs" / "api_docs.html"` | `parent` станет `stormlab/` → 404 | `PROJECT_ROOT / "docs" / "api_docs.html"` |
| `logging_config.py:86` | `cwd=Path(__file__).resolve().parent` | `parent` станет `stormlab/`; git всё равно найдёт репо, но явно нужен корень | `cwd=PROJECT_ROOT` |
| `tests/test_radar_builder.py:12` | `Path(__file__).parent / "fixtures"` | tests не двигаются | без изменений |
| `scripts/sync_agents.py:23` | `parents[1]` | scripts не двигаются | без изменений |

**Контракт `stormlab/paths.py`:**
```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent   # C:\StormLab
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
```
Директории создаются там, где они реально нужны (`init_db`, `setup_logging`, `build_application`), а не при импорте `paths.py`.

### 0.3 Аудит авто-рестарта

`bot.py:850-882` — **не re-exec**: это в-process `while True` с `time.sleep(RESTART_DELAY_SECONDS)` и fast-fail через `sys.exit(1)` после 5 быстрых падений. `sys.argv[0]`/`sys.executable` не используются. Следовательно тонкий wrapper (`from stormlab.bot import main; main()`) механику не ломает: цикл живёт внутри `stormlab/bot.py::main`.

Пруф после батча C: юнит-тест `tests/test_restart_loop.py` с monkeypatch `build_application`/`time.sleep` (один сбой → повтор; 5 быстрых сбоев → `SystemExit(1)`). Живой искусственный краш — OPERATOR.

### 0.4 Карта импортов (93 ссылки)

| Префикс | Ссылок | Файлов | Rewrite |
|---|---|---|---|
| `core` | 35 | 23 | `stormlab.core.*` |
| `clients` | 19 | 8 | `stormlab.clients.*` |
| `config` | 12 | 11 | `stormlab.config` |
| `render` | 10 | 5 | `stormlab.render.*` |
| `ai` | 6 | 5 | `stormlab.ai.*` |
| `alert_manager` | 5 | 4 | `stormlab.alert_manager` |
| `rate_limiter` | 3 | 3 | `stormlab.rate_limiter` |
| `persistence` | 2 | 2 | `stormlab.persistence` |
| `logging_config` | 1 | 1 | `stormlab.logging_config` |

Выбраны **абсолютные** импорты `stormlab.*` (не относительные): одинаково работают из root wrapper'ов, тестов и скриптов; `tests/`, `scripts/` и сами модули обновляются одним правилом. Внутрипакетные `from core.X import` тоже становятся `from stormlab.core.X import`.

### 0.5 Ссылки в docs/агентах/скиллах

- `agents/architect.md`: `PLAN.md` → `docs/plans/PLAN.md`; `graphify-out/` без изменений.
- `skills/stormlab-dev.md`: пути `core/*`, `render/*`, `bot.py`, `api.py`, `alert_manager.py` → `stormlab/core/*`, `stormlab/render/*`, `stormlab/bot.py`, `stormlab/api.py`, `stormlab/alert_manager.py`; `data/alerts.db` остаётся.
- `docs/VERIFICATION.md`, `docs/CONFLICTS.md`, `docs/PERSISTENCE.md`, `docs/F06_FIX_PLAN.md`, `docs/DEAD_CODE_REPORT.md`, `README.md` — обновить ссылки на новые пути (исторические отчёты оставляем как есть, но добавляем пометку «пути актуальны на момент аудита» либо правим точечно).
- `README.md` раздел «Структура проекта» — полностью заменить деревом из раздела 1 ТЗ.
- После правок канона: `python scripts/sync_agents.py` + `--check`.

### 0.6 Tracked-мусор и gitignore

`git ls-files` в корне: `.env.example`, `.gitattributes`, `.gitignore`, `AGENTS.md`, `PLAN.md`, `README.md`, 7 `.py`, `requirements.txt`. `bot.log`/кэши **не tracked** — `git rm --cached` не требуется (проверить на батче A повторно).

Добавить в `.gitignore`: `.pytest_cache/`, `.ruff_cache/`, `logs/`, оставить `bot.log` и `data/`. Удалить физически `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`.

---

## Фаза 1 — План исполнения

### Батч A — уборка индекса и каталогов (zero risk)
1. `.gitignore`: `logs/`, `.pytest_cache/`, `.ruff_cache/`.
2. `Move-Item bot.log logs/bot.log`; `New-Item -ItemType Directory logs, docs/plans`.
3. `git mv PLAN.md docs/plans/PLAN.md`; `git mv docs/F06_FIX_PLAN.md docs/plans/F06_FIX_PLAN.md`.
4. Удалить кэш-директории.
5. Проверка: `pytest -q` (159/3), `python -c "import bot, api"`, `ruff`, `git status` (только ожидаемые move'ы).

### Батч B — package move + import rewrite (high risk)
1. `New-Item stormlab/`; `git mv` 7 модулей + 4 подпакета.
2. Добавить `__init__.py` в `stormlab/`, `stormlab/core`, `stormlab/clients`, `stormlab/render`, `stormlab/ai`.
3. Создать `stormlab/paths.py` с контрактом из 0.2.
4. Rewrite 93 импорта во всех `.py` (код, тесты, `scripts/sync_agents.py` — у него только `ROOT`, импортов нет) по таблице 0.4.
5. Path-фиксы: все 7 строк из таблицы 0.2.
6. Проверка: `pytest -q` (159/3), `python -c "import bot, api"` (ещё корневые модули — на этом шаге они уже в пакете, поэтому wrapper'ы пока не меняем: импорт `bot` всё ещё работает через корневой `bot.py`, который теперь импортирует `from config...` — **поэтому импорты в корневых bot/api тоже обновляются на `stormlab.*` уже в батче B**), ruff 0. `python stormlab/api.py` не запускать до батча C.

### Батч C — тонкие wrapper'ы + логи (medium risk)
1. Переписать корневые `bot.py`/`api.py` (3 строки каждый) на `from stormlab.bot/api import main`.
2. В `stormlab/api.py` вынести `uvicorn.run(...)` в `def main()`.
3. `LOG_FILE` из `stormlab.config` указывает в `logs/`; `setup_logging()` создаёт каталог; проверить, что новый лог пишется туда (импорт + один `logger.info`).
4. Добавить `tests/test_restart_loop.py` (пруф fast-fail/restart).
5. Проверка: `pytest -q` ≥159/3, `python -c "import bot, api"`, `timeout`-smoke `python bot.py` (ожидаемый `RuntimeError` без `BOT_TOKEN`) и `python api.py` + `/api/health` через TestClient/uvicorn с таймаутом (для/api — запуск uvicorn без токена допустим), ruff 0.

### Батч D — docs/агенты/граф (low risk)
1. Обновить `README.md` (дерево, команды запуска, coverage), `AGENTS.md` (если нужно), `agents/*.md`, `skills/stormlab-dev.md`, точечно docs.
2. `python scripts/sync_agents.py` + `--check`.
3. `graphify . --update` (после коммита — hook сделает сам, но запустить явно).
4. Проверка: `pytest -q`, `python -c "import bot, api"`, ruff.

## Риски и меры

| Риск | Мера |
|---|---|
| `__file__`-пути (главный) | Все 7 точек из 0.2 покрыты тестами/импорт-смоуком; `api_docs.html` проверяется через `GET /` |
| Авто-рестарт | В-process loop, wrapper transparent; юнит-тест + OPERATOR artificial crash |
| `load_dotenv()` | Не меняем — cwd-семантика сохранена |
| Namespace → regular package | `__init__.py` во все 5 пакетов; абсолютныеImports `stormlab.*` |
| История файлов | только `git mv`, `git log --follow` должен находить историю |
| Граф | hook пересоберёт; сверить, что dangling-рёбра не выросли критично |

**Откат батча:** `git revert <commit>`; состояние до батча восстанавливается полностью, так как перемещения сделаны `git mv`.

## Критерии приёмки (проверить в Фазе 3)

- [ ] В корне только `bot.py`, `api.py` + конфиги/MD; `Get-ChildItem *.py` → ровно 2.
- [ ] `python bot.py` / `python api.py` работают без изменения команд.
- [ ] Авто-рестарт: юнит-пруф fast-fail + OPERATOR live.
- [ ] Логи в `logs/`, `LOG_FILE` указывает туда, ротация 5 МБ × 3 сохранена.
- [ ] pytest ≥159/3, coverage ≥73.64 %, ruff 0.
- [ ] `grep -rn "import config\|from core\|import alert_manager"` — только в контексте `stormlab.*`.
- [ ] `git ls-files` — кэшей/логов нет; `git log --follow stormlab/bot.py` показывает историю.
- [ ] `sync_agents.py --check` — up to date; README-дерево = реальность.
