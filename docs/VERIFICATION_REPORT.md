# VERIFICATION_REPORT — Full Verification (2026-11-28)

Репозиторий: `main` @ `f0919cc` + незакоммиченный WIP оператора (4 файла). Принцип: только проверки и документирование, **nop fixes**. Пруфы замеров — в `graphify-out/verify/*.py` (каталог игнорируется Git) и в разделах ниже.

## Baseline (зафиксирован до начала)

| Метрика | Значение |
|---|---|
| pytest | **155 passed, 3 skipped** (с WIP и без WIP — одинаково) |
| coverage | **73.1 %** (перепроверено в конце) |
| ruff F401/F841 | 1 finding, и он относится к WIP (`clients/geocoding.py:3`, `lru_cache`) |
| Граф | 747 узлов / 1789 рёбер @ `1e92732` |
| pip check | No broken requirements found (main + чистый venv) |

## Фаза 0 — матрица совместимости: ЧАСТИЧНО PASS

Подробности — `docs/ENV_MATRIX.md`.

| Пункт | Вердикт | Пруф |
|---|---|---|
| Python 3.11.9, чистый venv | **PASS** | `pip install -r requirements.txt` → pytest 155/3 → `import bot, api` OK |
| Python 3.12 / 3.13 | **NOT VERIFIED** | `py -0` показывает только `3.11` — интерпретаторов нет |
| Linux (прод) | **NOT VERIFIED** | только Windows в окружении |
| Matplotlib backend | **PASS (Windows)** | `tkagg` → `Agg` после импорта `render/*`; `matplotlib.use("Agg")` в коде |
| Namespace packages | **PASS (Windows)** | импорт из чужого cwd с `PYTHONPATH` — OK |
| Пути/кодировки | **PASS (Windows)** | `data/alerts.db` через pathlib; `RotatingFileHandler(..., encoding="utf-8")` |
| Порт 8000 занят | **PASS (Windows)** | явный `[Errno 10048]`, exit code 3 |
| Удалённые зависимости | **PASS** | 0 импортов colorlog/groq/cartopy/scipy; scipy 1.17.1 транзитивно; `pip check` чистый |

## Фаза 1 — конфликты: PASS, плюс дваfinding

Подробности — `docs/CONFLICTS.md`. `pip check` чистый, 23 модуля импортируются по одному без циклов, requirements ↔ imports совпадают (pytest-asyncio/pytest-cov — плагины, не прямой import), `requests` и `httpx` сосуществуют без конфликта версий. Порт 8000 — понятная ошибка.

## Фаза 2 — регрессия: PASS

| Проверка | Результат |
|---|---|
| `pytest -q` с WIP | 155 passed, 3 skipped |
| `pytest -q` без WIP (stash) | 155 passed, 3 skipped — **delta = 0** |
| `pytest --cov=.` | 73.1 % — совпадает с baseline |
| `ruff check --select F401,F841` | 1 finding из WIP, батчи чистые |
| SPC-пины (`test_storm_indices_core.py`, `test_effective_layer.py`, `test_season_regime.py`) | **30 passed** |
| Причина 3 skipped | `tests/test_audit_fixes.py:71`: `tzset()` POSIX-only; на Windows пропущены, на Linux должны запуститься |

## Фаза 3 — живой smoke: OPERATOR / NOT VERIFIED

Агент подготовил `docs/LIVE_SMOKE_CHECKLIST.md` со всеми сценариями (команды, кнопки, `/radar`, алерты, REST, AI fallback, lifecycle). Живые проверки **не выполнялись**: нет Telegram-токена, внешних ключей и тестового бота. AUTO-часть чеклиста помечена в документе.

## Фаза 4 — async/concurrency: MAJOR finding F-06

| Проверка | Вердикт | Пруф |
|---|---|---|
| Event loop blocking (F-06) | **FAIL → MAJOR** | `/api/health` = **328 мс** пока `/api/storm` (`_get_fused_data` → `time.sleep(0.30)`) выполнялся; 10 параллельных `/api/storm`: p50=p95=**3016 мс**, wall 3016 мс ≈ 10×300 мс. Скрипт `verify/loop_block.py` |
| Реальный рендер | контекст | 50 Skew-T рендеров = 138.9 с → ~2.8 с/рендер |
| 10×`/storm` живой Telegram | NOT VERIFIED | OPERATOR |
| SQLite гонки job/handler | NOT VERIFIED | OPERATOR |
| Кэши под нагрузкой | **PASS** | `tests/test_locks.py` 3 passed; `test_geo_cache_two_threads_stay_consistent` PASS |
| `user_data` изоляция | **PASS** | `test_ctx_is_keyed_by_chat_and_message` PASS |
| `time_idx` out of bounds (F-17) | **FAIL → MINOR** | `bot.py:596` без проверки; `time:5`/`time:-1` не валидируются |
| Rate limiter 100 req | **PASS** | 100/100 allowed; 20×один user → 1 allowed; prune удалил 50 |
| JobQueue vs рестарт | NOT VERIFIED | OPERATOR |

## Фаза 5 — failure injection: PASS (юнит-уровень)

`37 passed` по набору: `test_bot_forbidden.py`, `test_unavailable_radar_is_503`, `test_local_provider.py`, `test_effective_layer.py`.
Покрытые сценарии: Forbidden удаляет подписку, NetworkError — нет, ошибка `remove_alert` не ломает job, недоступный радар → 503, `None`-поля → «н/д», CAPE=0 + DCAPE=None не крашит, сезонные hazard-фолбэки. Живые отказы (токсичный proxy, блокировка хостов) — OPERATOR.

## Фаза 6 — ресурсы: частично PASS

| Проверка | Вердикт | Пруф |
|---|---|---|
| Figure leak | **PASS** | 50/50 рендеров, `plt.get_fignums()` 0 → 0, 138.9 с |
| LRU 600 городов (мок сети, WIP) | **PASS** | `_GEO_CACHE` = 500, oldest evicted, newest kept |
| REST 60 req/min | **PASS** | `test_api_rate_limit` в наборе из 32 security-тестов |
| Radar mosaic / FD / RSS soak 12–24 ч | **NOT VERIFIED** | OPERATOR |

## Фаза 7 — метео-корректность: частично PASS

| Проверка | Вердикт | Пруф |
|---|---|---|
| Сезон, ноябрь | **PASS (чистая функция)** | Москва 55.75 → cool; Сочи 43.6 → warm; Мурманск 68.97 → cool; Сидней −33.87 → warm |
| PIN-тесты STP/SCP/effective | **PASS** | 30 passed |
| None-поля → «н/д» | **PASS** | `test_local_provider.py` в наборе failure-injection |
| Реальные профили/зонд | **NOT VERIFIED** | OPERATOR (внешняя сеть) |

## Фаза 8 — security: PASS (AUTO-часть)

`32 passed`: `test_api_auth.py`, `test_text_safety.py`, `test_radar_api.py`, `test_redact_secrets_removes_appid`, `test_calculation_error_hides_internals`.

- F-16 разрешён: `_internal_error()` (`api.py:59-62`) отдаёт только `request_id`, `detail=str(e)` отсутствует.
- SQL: все `execute()` в `alert_manager.py` параметризованы (`?`).
- Radar path: `^/v2/radar/[A-Za-z0-9_-]{1,64}$`, 10 parametrized-тестов на traversal — PASS.
- `ADMIN_USER_IDS` используется только в `rate_limiter.py` (Telegram-лимиты), REST-ключ не обходит.
- Markdown/redaction: `test_text_safety.py` + `test_redact_secrets_removes_appid` — PASS.
- Callback tampering: **F-17** (см. Фазу 4).

## Сводка findings

| ID | Класс | Кратко | Пруф |
|---|---|---|---|
| F-06 | **MAJOR** | Синхронные вызовы в async REST-эндпоинтах блокируют event loop | 328 мс, p50/p95 3016 мс |
| F-17 | **MINOR** | `time_idx` без проверки границ | `bot.py:596`, `time:5` |
| F-18 | **MINOR** | Неиспользуемые константы в WIP (`_GEO_CACHE_TTL`, `_PROBE_*`) | grep + AUTO-скрипт |
| F-19 | **INFO** | Утерян double-check в WIP геокодера | `git diff` WIP |
| F-01 (radar live) | **PENDING** | Реальная картинка радара не проверена | OPERATOR |
| F-16 | **RESOLVED** | `detail=str(e)` нет, только request_id | `api.py:62` + тест |

## Вердикт по критериям приёмки

- [ ] Чистая установка + pytest на ≥2 версиях Python — **НЕ ВЫПОЛНЕНО**: только 3.11 доступна (Environment gap, не баг кода).
- [x] `pip check` чистый, удалённые deps не сломали логирование/AI — static PASS, живой Groq — OPERATOR.
- [ ] Все 9 команд + кнопки + алерты + REST проверены живьём, `/radar` отдаёт картинку — **OPERATOR**.
- [x] Event loop: замер есть, вердикт числами — **PASS (но вердикт FAIL для кода)**.
- [ ] Все fallback-цепочки инъекцией отказов — частично (юниты PASS, живые — OPERATOR).
- [ ] Soak 12–24 ч — **OPERATOR**.
- [x] BLOCKER/MAJOR имеют пруф и шаги воспроизведения — F-06/F-17 задокументированы.
- [x] Ноль попутных фиксов — **соблюдено**; все находки только классифицированы.

**Рекомендация архитектору:** F-06 — кандидат в следующий батч (обернуть синхронные вызовы REST в `to_thread` / перевести в sync-эндпоинты), F-17 — тривиальная валидация. Оба **не исправлялись** в рамках этой верификации.

## WIP STP delta=0 — разрешено

Незакоммиченные правки `core/storm_indices.py` меняют только имена параметров `calculate_stp` (`cape→sb_cape`, `srh→srh_0_1`, `lcl_height_m→sb_lcl_height_m`) и добавляют явную ветку `sb_lcl_height_m < 1000 → lcl_term = 1.0`. Численно поведение **не меняется**: старое выражение `min(1.0, (2000-lcl)/1000)` уже давало 1.0 для `lcl < 1000`; вызывающие стороны используют только позиционные аргументы. Поэтому `delta=0` в pytest — ожидаемый результат, а не пропущенная регрессия.

Добавлен дискриминирующий пин `tests/test_stp_surface_lcl_pin.py`: он принудительно делает `report["lcl"]` (MU-парацель) отличным от sbLCL и проверяет, что в `calculate_stp` уходит именно surface-based LCL. Пруф: при искусственной регрессии вызова на `lcl_height_m` тест падает (`1949.0 != 843.0`); с текущим кодом проходит. Это защищает реальный инвариант SPC fixed-layer STP от будущих правок вызова.

Одновременно в WIP убраны неиспользуемые TTL-константы (`_GEO_CACHE_TTL`, `_PROBE_CACHE_MAX`, `_PROBE_CACHE_TTL`) и неиспользуемый `lru_cache`, восстановлен double-check в `clients/geocoding.py` (F-18/F-19). Живой контур радара частично закрыт агентом: RainViewer + рендер дали валидный PNG 600×558 (`no_echo=True`); доставка в Telegram остаётся за оператором — `/radar` стоит первым в `docs/LIVE_SMOKE_CHECKLIST.md`.
