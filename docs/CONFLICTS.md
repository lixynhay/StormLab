# CONFLICTS — зависимости, гонки, async-блокировки (AUTO)

Дата: 2026-11-28. Все замеры reproducible скриптами в `graphify-out/verify/` (каталог игнорируется Git). Фиксов нет — только классификация.

## F-06 — синхронные вызовы внутри async-эндпоинтов: **MAJOR**

**Локация:** `api.py:236` (`resolve_city`), `api.py:251-252` (`_get_fused_data`, `build_storm_report` внутри `async def get_storm_report`), `api.py:277`, `api.py:302`, `api.py:345` — синхронные сетевые/расчётные вызовы без `to_thread`. В `bot.py` часть вызовов обёрнута в `asyncio.to_thread` (например `bot.py:564-565`), но рендер Skew-T — синхронный.

**Пруф (script `verify/loop_block.py`, ASGITransport, `_get_fused_data` подменён на `time.sleep(0.30)`):**
```
F-06 blocking: health=328.0 ms while /api/storm=328.0 ms (health=200, storm=503)
VERDICT: EVENT LOOP BLOCKED
10x /api/storm: p50=3016.0 ms p95=3016.0 ms min=3016.0 max=3016.0 wall=3016.0 ms
sequential-equivalent: 10 x 300 ms = 3000 ms; observed 3016.0 ms
```
То есть лёгкий `/api/health` ждёт тяжёлый запрос, а 10 параллельных `/api/storm` выполняются **строго последовательно** (3016 мс ≈ 10×300 мс). Реальный рендер Skew-T в отденом замере — 138.9 с / 50 вызовов = **~2.8 с на рендер**, так что в проде задержка будет больше синтетической. Замер сделан на реальном `api.app` через `ASGITransport`, внешняя сеть не использовалась.

**Шаги воспроизведения:** запустить `python graphify-out/verify/loop_block.py` из корня репозитория (внешняя сеть не нужна).
**Рекомендация (не применялось):** обернуть синхронные вызовы в `asyncio.to_thread` либо перевести эндпоинты в `def` (FastAPI сам уведёт их в threadpool). Отдельный батч после одобрения; `concurrent_updates(True)` не включать.

## F-17 — callback_data `time:N` без проверки границ: **MINOR**

**Локация:** `bot.py:596` — `time_idx = int(query.data.split(":")[1])`, затем `TIME_OFFSETS[time_idx]`.
**Пруф:** `TIME_OFFSETS` содержит 5 элементов, генератор `_build_time_markup()` (`bot.py:193-194`) выдаёт `time:0..time:4` (6 байт, лимит 64 — OK). Значения `time:5`, `time:-1`, `time:abc` проходят парсинг и попадают в индекс без валидации → `IndexError`/`ValueError` внутри хендлера. Воспроизведение: отправить callback с таким `data` тестовому боту; AUTO-скрипт `verify/auto_checks.py` печатает список.
**Рекомендация:** проверять `0 <= time_idx < len(TIME_OFFSETS)` и `data.isdigit()` перед индексацией. Не чинилось.

## F-18 — мёртвые константы в незакоммиченной правке (WIP): **MINOR / INFO**

`clients/geocoding.py:14 _GEO_CACHE_TTL = 3600` и `clients/sounding_api.py:42-43 _PROBE_CACHE_MAX/_PROBE_CACHE_TTL` объявлены, но не используются (AUTO-скрипт подтвердил TTL = 3600 при работающем LRU-вытеснении). Это часть WIP оператора, не коммитов `main` — в Dead Code батчи не входило. При желании — отдельный батч.

## F-19 — потеря double-check в кэше геокодера (WIP): **INFO**

В закоммиченной версии после сетевого запроса перед записью был повторный `with _GEO_LOCK: current = _GEO_CACHE.get(key)...`; в WIP его нет — запись всегда безусловна. Блокировка целостность словаря сохраняет, но два потока с одним городом могут сделать два HTTP-запроса. Пруф: `git diff` WIP vs HEAD для `clients/geocoding.py`. Не чинилось.

## Конфликты зависимостей — **PASS**

| Проверка | Результат |
|---|---|
| `pip check` (main venv) | No broken requirements found |
| `pip check` (чистый venv) | No broken requirements found |
| Версии | numpy 2.4.6 / pandas 3.1.1 / MetPy 1.7.1 / pint 0.25.3 / scipy 1.17.1 |
| Удалённые `groq/colorlog/Cartopy/scipy` | 0 импортов в `.py`; `import bot, api` стартует; scipy транзитивен |
| Двойной HTTP-стек | `requests`: geocoding/openmeteo/OWM/sounding; `httpx`: radar_api/radar_builder + PTB `HTTPXRequest`; конфликтов версий `pip check` не нашёл |
| Циклические импорты | 23 модуля импортированы по одному в одном процессе — все OK; graphify: Import Cycles = None detected |
| Namespace packages | импорт из другого cwd с `PYTHONPATH=C:\StormLab` — OK |
| Порт 8000 занят | явный `[Errno 10048] error while attempting to bind` + exit code 3 (не тихий краш) |

## Гонки и блокировки — **PASS** (за мерой F-06)

| Проверка | Результат / пруф |
|---|---|
| `get_lock` / `KeyedLocks` | `tests/test_locks.py` — 3 passed (одинаковый лок по имени, drop работает) |
| Кэш геокодера, 2 потока | `test_geo_cache_two_threads_stay_consistent` — PASS |
| LRU-вытеснение 600 городов (мок сети, WIP) | размер ровно 500, oldest удалён, newest на месте |
| Rate limiter 100 пользователей | 100/100 allowed, размер словаря 100 |
| Rate limiter 20 вызовов одним пользователем | 1 allowed, remaining=30 |
| Pruning | после принудительного вызова `_prune_rate_limits()` удалено 50 устаревших записей |
| `user_data` изоляция | `test_ctx_is_keyed_by_chat_and_message` — PASS |
| SQLite гонки (alert job vs handler) | **НЕ ИЗМЕРЕНО** — требует живого JobQueue; OPERATOR |
| JobQueue после рестарта | **НЕ ИЗМЕРЕНО** — OPERATOR |

## Ресурсы — **PASS (частично)**

| Проверка | Результат |
|---|---|
| 50 последовательных Skew-T рендеров | 50/50 OK, `plt.get_fignums()` 0 → 0, 138.9 с, последний payload 284 589 байт |
| Бэкенд matplotlib | `tkagg` до импорта рендера → `Agg` после (`matplotlib.use("Agg")` в `chart_builder.py:8`, `skewt_builder.py:4`) |
| Radar mosaic, FD-утечки, RSS soak | **НЕ ИЗМЕРЕНО** — OPERATOR |

## Сводка findings

| ID | Класс | Статус |
|---|---|---|
| F-06 | MAJOR | event loop блокируется синхронными вызовами; пруф с числами есть |
| F-17 | MINOR | нет валидации `time_idx`; пруф статический + AUTO-скрипт |
| F-18 | MINOR | неиспользуемые константы в WIP |
| F-19 | INFO |double-check утерян в WIP геокодера |
| остальное | PASS | зависимости, локи, rate limiter, figure leak, порт, бэкенд |
