# AUDIT — StormLab (read-only аудит + приоритизированный backlog)

Дата: 2026-11-26
Режим: только чтение. Код не изменялся. Единственный новый файл — этот отчёт.
Граф: `graphify-out/graph.json` (272 узла / 742 ребра / 10 сообществ, import cycles: none).

---

## 0. Как проверялось (факты команд)

```text
$ python -m py_compile <все *.py>
ALL_PY_COMPILE_OK

$ python -m pytest -q
C:\...\python.exe: No module named pytest

$ python -c "import api"
  File "C:\StormLab-clean\storm_indices.py", line 3, in <module>
    import metpy.calc as mpcalc
ModuleNotFoundError: No module named 'metpy'

$ python -c "import importlib.util as u; ..."
pytest MISSING | metpy MISSING | matplotlib MISSING | telegram MISSING
apscheduler MISSING | cartopy MISSING | siphon MISSING

$ git status --short
 D .env.example
?? .opencode/
?? AGENTS.md
?? bot.log
?? graphify-out/

$ git rev-list --left-right --count main...origin/main
0	0
```

Вывод: в текущем окружении тесты **физически не запускаются** (нет pytest/metpy/matplotlib/telegram).
Пины проверены статически (AST + арифметика формул, без импорта модулей):

```text
EFFECTIVE_CONSTANTS == PIN_CONSTANTS: True
stp_effective(1500,1000,150,20,-50) = 1.0
scp_effective(1500,150,20)         = 4.5
calculate_stp(1500,150,1000,-50,20) = 1.0
calculate_scp(1500,150,20,-50)      = 2.25
threat(cape=300,shear=25,warm)      = 1
threat(cape=300,shear=25,cool)      = 2
```

Живая проверка RainViewer (подпроцесс с жёстким таймаутом 25 с):

```text
OUT: (None, None, False)
elapsed 0.97
LOG: RainViewer: API временно отдает только заглушки
```

---

## 1. Карта архитектуры (из графа)

### 1.1 God nodes (топ-10, `graphify god-nodes`)

| Узел | Рёбра | Роль |
|---|---|---|
| `build_storm_report()` | 46 | ядро: собирает все индексы, мост bot↔api↔season |
| `button_handler()` | 18 | вся inline-навигация Telegram |
| `build_application()` | 16 | сборка PTB Application + JobQueue |
| `build_skewt_chart()` | 14 | Skew-T/годограф/инфо-бокс |
| `alerts_background_task()` | 13 | фоновые алерты каждые 30 мин |
| `OpenMeteoAPI` | 12 | единственный источник модельного профиля |
| `md()` | 12 | Markdown-экранирование |
| `_send_skewt()` | 12 | отправка Skew-T |
| `_send_storm_report()` | 12 | отправка отчёта |
| `build_profile_chart()` | 11 | вертикальный профиль (PNG) |

### 1.2 Сообщества (cohesion)

- **0 — `storm_indices.py`** (44 узла, 0.11): `build_storm_report`, CAPE/ML/MU, STP/SCP, EHI, BRN, DCAPE, effective-layer.
- **1 — `bot.py`** (37, 0.10): хендлеры, `_send_*`, `alerts_background_task`, `build_application`.
- **2 — `api.py`** (22, 0.09): FastAPI, auth/rate-limit, эндпоинты.
- **3 — `logging`/infra** (13, 0.12): `setup_logging`, `resolve_city`, radar/sounding helpers.
- **4 — `ai_providers.py`** (10, 0.12): цепочка Groq/GitHub/Gemini/OpenRouter/Local.
- **5 — `skewt_builder.py`** (10, 0.15): отрисовка Skew-T/годографа/радара.
- **7 — `OpenMeteoAPI`** (4, 0.23): Session + CircuitBreaker + TTL-кэш.
- **9 — `_send_storm_report`/season** (10, 0.28): `get_regime`, `thresholds_for`, `interpret`, threat.

### 1.3 Потоки данных

```text
Telegram bot.py
  └─ _get_fused_current_data()
       ├─ OpenMeteoAPI.get_current()/get_pressure_levels()   [requests.Session, cache 50, breaker 300s]
       ├─ OpenWeatherMapAPI.get_current()                    [optional]
       └─ data_fusion.fuse_current_weather()                 [inverse-variance + circular mean]
  └─ storm_indices.build_storm_report(regime=...)
       ├─ calculate_mucape_real → mlcape → sbcape (fallback MU→ML→SB)
       ├─ calculate_thunderstorm_indices (K/TT/CT/VT), LI, SI, SWEAT, DCAPE, EHI, BRN
       ├─ calculate_hodograph_shear_srh (Bunkers + SRH 0–3 км)
       ├─ calculate_stp / calculate_scp (fixed layer)
       └─ effective_layer: find_effective_layer → effective_srh/ebwd → stp_eff/scp_eff
  └─ format_storm_text / chart_builder / skewt_builder → Telegram

REST api.py
  └─ те же _get_fused_data + build_storm_report
  └─ /api/radar: radar_api.get_latest_radar_frame → radar_builder.build_radar_image
  └─ /api/ai-analysis: ai_analysis → ai_providers chain

Alerts (JobQueue, 30 мин)
  └─ alerts_background_task → _get_fused_current_data → build_storm_report(regime)
     → alert_manager.check_dangerous_conditions → SQLite → Telegram

Sounding (только bot /skewt)
  └─ sounding_api (siphon/pandas) → skewt_builder (модель vs зонд)
```

Ключевые мосты по графу: `build_storm_report()` (betweenness 0.124), `OpenMeteoAPI` (0.062).
`graphify affected "calculate_stp"` подтверждает 5 точек входа: `api.py:191/236/279`, `bot.py:205/253/318/645`.

---

## 2. Findings

Severity: crit / high / med / low. Каждый пункт — с `file:line` или выводом команды.

| id | sev | file:line | факт | предложение |
|---|---|---|---|---|
| F-01 | **high** | `radar_api.py:45` | Живой RainViewer отдаёт пути вида `/v2/radar/237cea37e45b` (3 слэша). Условие `path.count('/') >= 4` отбрасывает **все** кадры → `get_latest_radar_frame()` всегда `(None,None,False)`; `/api/radar` → 503 (`api.py:258-260`), `/radar` → «недоступен» (`bot.py:282-287`). Подтверждено live-выводом и JSON API. | Заменить guard на проверку префикса `/v2/radar/` и непустого хэша (или `count('/') >= 2`), добавить unit-тест на реальный формат пути. |
| F-02 | **high** | `requirements.txt:1`; `bot.py:692` | `python-telegram-bot>=22.8` без extra `[job-queue]`. На чистой установке нет APScheduler (`apscheduler MISSING`), `application.job_queue` недоступен → падение старта/алерты мертвы. | `python-telegram-bot[job-queue]>=22.8`, зафиксировать lock-файлом, smoke-тест `build_application()`. |
| F-03 | **high** | `storm_indices.py:175-197`, `503`, `718-721` | Fixed-STP отклоняется от SPC: (a) в формулу добавлен CIN-член, которого в fixed-STP нет; (b) используется `report["srh"]` = SRH 0–3 км (`:503`), а нужен 0–1 км; (c) CAPE — MUCAPE (`:653-656`), а нужен sbCAPE; (d) LCL — SB (`calculate_mucape_real:350`), CAPE — MU. | Привести `calculate_stp` к SPC fixed-layer: sbCAPE, sbLCL, SRH 0–1 км, 6BWD; убрать CIN-член. Pin-тесты на каждое слагаемое. |
| F-04 | **high** | `storm_indices.py:199-215`; `effective_layer.py:21-25,178-191` | SCP расходится с первоисточником SPC: EBWD lower bound 12.5 вместо **10 м/с**; shear cap 1.5 вместо **1.0** (EBWD>20→1); CIN-член `(200-\|CIN\|)/150` вместо `(-40/muCIN)` (Gropp & Davenport 2018); в `scp_effective` CIN-члена нет вовсе. | Пересмотреть константы и формулу CIN; синхронизировать fixed/effective; pin-тест на границы 10/20 м/с и CIN −40. |
| F-05 | **high** | `effective_layer.py:47-79`, `116-138` | «Effective layer» — это base→**EL**, а не effective inflow layer. Нет проверки `CIN >= -250`; top не обрезается условием CAPE<100. EBWD считается до **полного EL**, а по SPC — до **50 % EL**. Итог: ESRH/EBWD, а значит `stp_eff`/`scp_eff`, завышены. | Реализовать inflow layer по SPC (CAPE≥100 и CIN≥−250, contiguous), EBWD — до 50 % EL; pin-тесты на синтетическом профиле. |
| F-06 | **med** | `api.py:131-132,151,191,216,226,240,262,282`; `bot.py:226` | `async def` эндпоинты выполняют синхронные `requests`/MetPy/matplotlib прямо в event loop (до 3 ретраев × timeout (10,20) с). Один uvicorn-worker блокируется на всё время запроса. `build_profile_chart` в боте тоже не в `to_thread` (в отличие от `_send_skewt:260`). | `await asyncio.to_thread(...)` для I/O и рендера либо `run_in_threadpool`; вынести `_get_fused_data` в threadpool. |
| F-07 | **med** | `bot.py:644-646`; `alert_manager.py:11-16,192-231` | Алерты **не season-aware**: `build_storm_report(regime=...)` считается, но `check_dangerous_conditions` использует жёсткие warm-пороги (CAPE 1000 / shear 15 / LCL 1500 / CIN 150) и игнорирует regime. Кул-сезонные «низкий CAPE + сильный сдвиг» не дают алертов. Утверждение «зимой больше алертов» **не подтверждается**. | Передавать `thresholds_for(regime)` в `check_dangerous_conditions` (или гейтить по `report["threat_level"]`), добавить тест cool/warm. |
| F-08 | **med** | `alert_manager.py:234-251` | `prune_history()` определена, но **нигде не вызывается** (`Select-String` по всем `*.py` — только определение). `alert_history` растёт неограниченно. | Вызывать prune в `alerts_background_task` (раз в сутки) или отдельным JobQueue; тест на удаление старых строк. |
| F-09 | **med** | `git status`; `README.md:107` | `.env.example` удалён в рабочем дереве (` D .env.example`), хотя README требует «скопируйте `.env.example` в `.env`». Чистая установка/деплой ломается. | `git checkout -- .env.example` (вернуть файл), затем обычный коммит. |
| F-10 | **med** | `radar_api.py:31`; `radar_builder.py:42` | Радар всё ещё на `httpx.Client` — тот же класс Windows-hang, который чинили для Open-Meteo. Live-запрос сейчас вернулся за 0.97 с (не воспроизводится), но нет User-Agent, timeout-кортежа, ретраев и переиспользования сессии. | Перевести на общий `requests.Session` с UA и `timeout=(5,15)`, либо подтвердить стабильность httpx отдельным soak-тестом. `httpx` из requirements не убирать — он нужен PTB. |
| F-11 | **med** | `tests/`; `test_api_auth.py`; вывод pytest/import | Ядро `storm_indices` не покрыто: только effective-пины, season и auth. Нет тестов на `calculate_stp/scp`, Bunkers, CAPE-fallback, K/TT/LI/SI/SWEAT, DCAPE, EHI, BRN, алерты. `_self_check()` (`alert_manager.py:254`) никем не вызывается. В текущем env тесты не запускаются (нет pytest/metpy). | Добавить `tests/test_storm_indices.py` с фикстурами-профилями и pin-значениями; поднять CI с установкой requirements. |
| F-12 | **low** | `README.md:109,141,216` | README: «BOT_TOKEN … иначе config.py поднимет RuntimeError» — фактически `config.py:7-9` не падает, проверка в `bot.main()` (`bot.py:702-706`). Тесты описаны только как `pytest test_api_auth.py`, папка `tests/` не упомянута. | Синхронизировать README с кодом; указать `pytest -q`. |
| F-13 | **low** | `geocoding.py:7,46`; `sounding_api.py:15-18,98-99,141`; `.gitignore:5` | Неограниченные кэши: `_GEO_CACHE` (ключ — любой город), `_SOUNDING_CACHE/_SOUNDING_TS/_PROBE_CACHE` (без eviction). `data/persistence.pkl` не покрыт `.gitignore` (`data/*.db` — только БД). | LRU/лимит + TTL для гео/зондов; добавить `data/persistence.pkl` и `*.log` в `.gitignore`. |
| F-14 | **low** | `config.py:56-71,73`; `data_fusion.py:7-12`; `api.py:15` | Мёртвый конфиг: `FUSION_SIGMA` и `FUSION_DIVERGENCE_WARN_THRESHOLD` не используются (фьюжн берёт свои равные sigma), `RADAR_COOLDOWN` не используется, `API_TIMEOUT` импортирован в api.py но не нужен. | Удалить или задействовать; иначе конфиг вводит в заблуждение. |
| F-15 | **low** | `requirements.txt:5,8,11,13-16` | Лишние/неиспользуемые: `Cartopy`, `colorlog`, `groq` (Groq идёт через OpenAI-совместимый клиент); dev-зависимости `pytest*` в прод-файле; нет lock-файла. `httpx` нужен (radar + PTB), `siphon/pandas/Pillow` нужны. | Разделить `requirements.txt` / `requirements-dev.txt`, убрать неиспользуемое, добавить lock. |
| F-16 | **low** | `api.py:204,224,248,272,291` | 500-ответы отдают `detail=str(e)` — утечка внутренних сообщений/путей клиенту. | Логировать исключение, клиенту — обобщённый `detail`. |
| F-17 | **low** | `bot.py:505-506,557-559,580-600` | `time_idx` из callback не валидируется (`TIME_OFFSETS[time_idx]` → IndexError), `wmo` не валидируется; дублирующийся блок `if target:` (580–600) — мёртвый код. | Валидировать `0 <= idx < len(TIME_OFFSETS)` и формат WMO; убрать дубль. |
| F-18 | **low** | `skewt_builder.py:28,39,130-132` | Заявленный `BARB_COLOR NameError` **не воспроизводится**: везде `BARB_COLORS` (plural), `_barb_color` определена. Реальная мелочь: барбы красятся одним средним цветом, а любая ошибка глотается `except` с warning. | Считать риск закрытым; опционально — цвет по уровню и явный лог ошибки. |
| F-19 | **low** | `git status`; `git rev-list` | Локальный `main` == `origin/main` (`0 0`), root-commit `01c2ac3` (2026-08-03), 27 коммитов. Расхождения с remote нет. Но untracked: `AGENTS.md`, `.opencode/`, `graphify-out/`, `bot.log`; `bot.log` не в `.gitignore`. | Добавить `*.log`, `graphify-out/cache/` в `.gitignore`; закоммитить `AGENTS.md`, плагин и `graphify-out/graph.json` (по правилу AGENTS.md). Синхронизация — только `git fetch && git merge --ff-only origin/main`; **force-push запрещён**. |

### 2.1 Первоисточник для F-03…F-05 (SPC)

Проверено по SPC Mesoanalysis Help (`begin.html`, `help_scp.html`):

- **SCP** = `(muCAPE/1000) * (ESRH/50) * (EBWD/20) * (-40/muCIN)`; EBWD<10 → 0, EBWD>20 → 1; CIN-член = 1.0 при muCIN > −40.
- **STP (effective)** = `(mlCAPE/1500) * ((2000-mlLCL)/1000) * (ESRH/150) * (EBWD/20) * ((mlCIN+200)/150)`; LCL-член = 1.0 при <1000 м; EBWD cap 1.5 при >30, 0 при <12.5; CIN-член = 1.0 при >−50; весь индекс 0, если effective inflow base выше земли.
- **STP (fixed)** = `(sbCAPE/1500) * ((2000-sbLCL)/1000) * (0–1 км SRH/150) * (6BWD/20)`; **CIN-члена нет**; 6BWD cap 1.5, 0 при <12.5.
- **Effective inflow layer** — первый слой, где все contiguous parcels имеют `CAPE >= 100` и `CIN >= -250`.
- **EBWD** — сдвиг от effective inflow base до **50 % высоты EL** MU-парцеля.

Следствие: константы `EBWD_MIN=12.5 / EBWD_MAX=30` для **effective** STP верны, но для **SCP** должны быть `10 / 20`; CIN-члены и SRH-слой требуют правки формул, а не только констант. Задача «править только CONSTANTS + pin» выполнима для SCP-границ, но **не** для CIN-формулы и 50 % EL — это отдельные изменения логики (см. backlog #3/#10).

---

## 3. Приоритизированный backlog (top-10)

| # | Задача | Effort | Зависимости |
|---|---|---|---|
| 1 | Вернуть `.env.example`, добавить `[job-queue]`, lock-файл, smoke `build_application()` | S | — |
| 2 | Починить radar guard (`/v2/radar/<hash>`) + unit-тест формата пути | S | — |
| 3 | Привести fixed STP/SCP к SPC (SRH 0–1, sbCAPE, CIN-формула, EBWD 10/20, убрать CIN из fixed STP) | M | #4 (пины) |
| 4 | Добавить `tests/test_storm_indices.py`: пины STP/SCP/threat, Bunkers, CAPE-fallback, K/TT/LI/SWEAT | M | #1 (окружение) |
| 5 | Season-aware алерты: `thresholds_for(regime)` + тест cool/warm | S/M | #4 |
| 6 | Убрать blocking I/O из event loop (`api.py`, `bot.py:226`) | S/M | — |
| 7 | `prune_history` в JobQueue + лимиты кэшей (geo/sounding) + `.gitignore` | S | — |
| 8 | Деплой-документация: `.env`, `API_HOST`, коды 401/429/503, Windows-запуск, BOT_TOKEN-формулировка | S | #1 |
| 9 | Гигиена requirements/git: dev-deps отдельно, `*.log`, `graphify-out/cache/`, ff-only sync | S | — |
| 10 | Effective-layer по SPC: inflow layer (CAPE≥100, CIN≥−250), EBWD до 50 % EL, pin-тесты | M/L | #3, #4 |

Порядок: 1→2→4→3→5→6→7→8→9→10. Пункты 1, 2, 7, 9 независимы и дают быстрый эффект.

---

## 4. НЕ трогать (проверено, стабильно)

- **REST-защита**: `api.py:61-104` — `hmac.compare_digest`, fail-closed при пустом ключе, публичны только `/` и `/api/health`, rate-limit 60/мин; тесты `test_api_auth.py:6-93` покрывают 401/429/health.
- **Open-Meteo клиент**: `openmeteo_api.py:52-95,120-170` — `requests.Session` + User-Agent + `timeout=(10,20)` (не (10,30), как в базовом описании), CircuitBreaker 3/300 с, TTL-кэш 50 записей. Live-проверка ранее — sub-second.
- **Пины effective-layer**: `EFFECTIVE_CONSTANTS == PIN_CONSTANTS` (AST-проверка), ESRH=100, STP_eff=1.0, SCP_eff=4.5, fixed regression 1.0/2.25/threat=5 — сходятся арифметически.
- **Season**: `season_regime.py:1-42`, тесты `tests/test_season_regime.py`; warm-пин CAPE=300/shear=25 → threat=1 **присутствует** (`tests/test_season_regime.py:24-33`).
- **Память рендера**: `chart_builder.py:134`, `skewt_builder.py:336,351,370` — `plt.close(fig)` есть; утечки фигур нет.
- **Rate limiter бота**: `rate_limiter.py:16-48` — admin bypass, prune при >500.
- **Фьюжн**: `data_fusion.py:15-27` — inverse-variance и круговое среднее корректны.
- **Graphify**: `AGENTS.md`, `.opencode/plugins/graphify.js`, `graphify-out/graph.json` — работает, import cycles нет.

---

## 5. Приёмка

- Секции «Карта архитектуры», «Findings», «Backlog top-10», «НЕ трогать» — присутствуют.
- Каждый finding имеет `file:line` и/или вывод команды.
- Код не изменялся: `py_compile` до/после — OK; правок в `*.py` нет.
- `git status` **не полностью чист из-за pre-existing состояния** (до аудита): ` D .env.example`, untracked `AGENTS.md/.opencode/graphify-out/bot.log`. Единственное добавление от аудита — `AUDIT.md`. Удаление `.env.example` зафиксировано как F-09 и намеренно не исправлялось (read-only).
