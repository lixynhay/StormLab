# Аудит мёртвого кода

Дата: 2026-11-26. Проверен 21 корневой `.py` файл. Graphify недоступен: `graphify affected "bot.py"` завершился `command not found`; `graphify-out/` отсутствует. Поэтому module relationships проверены поиском Python imports, вызовов и entrypoints; классификация ниже не основана на graph results.

## Root Python modules

| Модуль | Импортёры / entrypoints (`file:line`) | Вердикт | Доказательство |
| --- | --- | --- | --- |
| `ai_analysis.py` | `bot.py:24`, `api.py:25` | USED | `generate_storm_analysis` вызывается ботом и REST API; цепочка providers создаётся при импорте (`ai_analysis.py:6`). |
| `ai_providers.py` | `ai_analysis.py:2` | USED | `build_provider_chain()` вызывается `ai_analysis`; Local provider всегда добавляется, облачные providers добавляются по ключам (`ai_providers.py:227-271`). |
| `alert_manager.py` | `bot.py:31` | USED | Подписки и проверки вызываются командами `/alert`, `/unalert`, `/alerts` и `alerts_background_task` (`bot.py:426-458,627-668`). |
| `api.py` | `test_api_auth.py:3`; entrypoint `python api.py` (`api.py:307`) | USED | Создаёт FastAPI app, предоставляет REST endpoints и самостоятельный запуск Uvicorn. |
| `bot.py` | entrypoint `python bot.py` (`bot.py:741`) | USED | Регистрирует команды и запускает Telegram application. |
| `chart_builder.py` | `bot.py:23`, `api.py:20`, `skewt_builder.py:12` | USED | Профильный renderer используется ботом и REST; сериализованный render decorator также импортируется Skew-T builder. |
| `config.py` | `bot.py:16`, `api.py:15`, `ai_providers.py:228`, `geocoding.py:3`, `logging_config.py:5`, `openmeteo_api.py:8`, `openweathermap_api.py:6`, `rate_limiter.py:3` | USED | Централизованные runtime-настройки, ключи и defaults импортируются этими модулями. |
| `data_fusion.py` | `bot.py:20`, `api.py:18` | USED | `fuse_current_weather` объединяет приземные данные Open-Meteo и OWM. |
| `effective_layer.py` | `storm_indices.py:6` | USED | Импортированы effective-layer, ESRH, EBWD и effective STP/SCP функции; layer применяется в storm report (`storm_indices.py:814`). |
| `geocoding.py` | `bot.py:27`, `api.py:22` | USED | `resolve_city` используется Telegram workflow и `/api/geocode`. |
| `logging_config.py` | `bot.py:17` | USED | `setup_logging()` вызывается при загрузке бота (`bot.py:36`). |
| `openmeteo_api.py` | `bot.py:18`, `api.py:16` | USED | Оба entrypoints создают API client и загружают текущие/профильные данные. |
| `openweathermap_api.py` | `bot.py:19`, `api.py:17` | OPTIONAL | Client создаётся импортёрами, но `get_current()` пропускает сетевой вызов без `OPENWEATHERMAP_API_KEY` (`openweathermap_api.py:21-24`); fusion продолжает работу без OWM (`bot.py:107-110`, `api.py:152-155`). |
| `radar_api.py` | `bot.py:28`, `api.py:23`, `tests/test_radar_api.py:3` | USED | Получает и валидирует RainViewer frame path; TTL cache и allowlist выполняются в рабочем radar workflow. |
| `radar_builder.py` | `bot.py:29`, `api.py:24`, `tests/test_radar_builder.py:9-10` | USED | Строит tile mosaic для Telegram и REST; stub/coverage regression tests импортируют его. |
| `rate_limiter.py` | `bot.py:30` | USED | Вызывается для storm, Skew-T, radar и AI команд (`bot.py:360-399`). |
| `season_regime.py` | `bot.py:22`, `storm_indices.py:619`, `tests/test_season_regime.py:1` | USED | Режим и thresholds применяются в отчёте/боте; есть отдельные regression tests. |
| `skewt_builder.py` | `bot.py:25`, `api.py:21`, `tests/test_skewt_builder.py:9` | USED | Skew-T/model+sounding renderer вызывается ботом и REST; projection, dewpoint, hodograph/barb tests используют helpers. |
| `sounding_api.py` | `bot.py:26` | USED | `probe_stations` вызывается в Skew-T flow; `get_sounding_by_wmo` вызывается при выборе станции (`bot.py:258,568`). |
| `storm_indices.py` | `bot.py:21`, `api.py:19`, `openmeteo_api.py:9`, `chart_builder.py:15`, `skewt_builder.py:11`, `tests/test_effective_layer.py:12`, `tests/test_season_regime.py:2`, `tests/test_storm_indices_core.py:6` | USED | Центральные расчёты индексов используются отчётами, профилями и chart code; формулы покрыты tests. |
| `test_api_auth.py` | pytest root discovery; importer: — | MISPLACED | Живой pytest module с `test_` prefix, но расположен в корне, тогда как остальные pytest modules находятся в `tests/`. Целевой путь: `tests/test_api_auth.py`. |

**Итог:** среди root production modules DEAD не найдено. `api.py` и `bot.py` являются скриптовыми entrypoints; `test_api_auth.py` тоже исполняется pytest discovery, поэтому он живой, но расположен отдельно от тестового каталога.

## Артефакты и gitignore

| Путь / тип | Статус Git | Ignore | Наблюдение |
| --- | --- | --- | --- |
| `charts_audit_out/` — live/audit PNG и stderr log | удалено из индекса и с диска | Игнорируется | Удалено при деперсонализации; папка не создаётся Git. |
| `tests/fixtures/*.png` (3 RainViewer fixtures) | tracked | Не игнорируется | Echo, transparent и stub PNG используются `tests/test_radar_builder.py`. |
| `data/persistence.pkl` | исключено из индекса; файл удалён с диска | Игнорируется | Bot создаёт локальный валидный пустой persistence state при старте, если файла нет. |
| `data/*.db` | не найдено в `data/` при аудите | игнорируется | Правило `.gitignore:5` исключает SQLite alert DB. |
| `bot.log`, `__pycache__/`, `*.pyc`, `.env`, `venv/` | зависит от наличия | игнорируется | Соответствующие правила находятся в `.gitignore:1-9`. |
| `graphify-out/` | отсутствует | игнорируется | `.gitignore:9`; graphify CLI и graph output недоступны. |

## Проверки

- Graphify: `graphify affected "bot.py"` — unavailable (`command not found`); graph directory absent.
- Direct imports: поиск по всем Python files в корне и `tests/`; динамических загрузчиков (`importlib`, `__import__`, `runpy`, file loaders) не обнаружено.
- Entry points: `bot.py:741`, `api.py:307`.
- Код не изменён; для `test_api_auth.py` предложено перемещение в `tests/`, но перемещение не выполнялось.
