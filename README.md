# 🌩 StormLab — Telegram-бот для анализа грозовой обстановки

Профессиональный метеорологический бот для анализа конвективной неустойчивости атмосферы, построения аэрологических диаграмм (Skew-T Log-P) и AI-разборов грозовой обстановки. Расчёт индексов выполняется по стандартам SPC на модельных данных Open-Meteo с возможностью сверки с реальными аэрологическими зондами (Wyoming/IGRA2).

---

## 🚀 Возможности

### Основные команды
| Команда | Описание |
| --- | --- |
| `/start` | Начать работу с ботом |
| `/storm [город]` | Грозовые индексы + вертикальный профиль атмосферы |
| `/skewt [город]` | Skew-T Log-P диаграмма + выбор реального зонда |
| `/radar [город]` | Радар осадков (RainViewer API) |
| `/ai [город]` | AI-анализ грозовой обстановки (Groq/GitHub/Gemini/OpenRouter/Local с fallback) |
| `/alert [город]` | Подписка на уведомления об опасной погоде |
| `/unalert [город]` | Отписка от уведомлений |
| `/alerts` | Список активных подписок |
| `/help` | Справка по командам |

После `/storm` и `/skewt` доступны inline-кнопки выбора времени: **Сейчас / +3ч / +6ч / +12ч / +24ч**, а для Skew-T — выбор ближайшей станции зондирования с выводом сравнения «модель vs реальный зонд».

### Рассчитываемые индексы (по стандартам SPC)
**Термодинамика:**
- **CAPE** (MU → ML → SB fallback-цепочка через MetPy) — Convective Available Potential Energy
- **CIN** — Convective Inhibition (крышка)
- **LCL** — Lifted Condensation Level

**Индексы устойчивости:**
- K-Index, Total Totals, **Lifted Index** (точный расчёт через MetPy)
- Showalter Index (парсель, поднятый с уровня 850 гПа), SWEAT Index, Mid-layer spread

**Динамика (важно для суперячеек):**
- Bulk Wind Shear 0-6 км и 0-3 км
- Storm Relative Helicity (SRH) с расчётом Bunkers Storm Motion

**Композитные индексы (шторм-чейзинг):**
- **STP** (Significant Tornado Parameter) — fixed-layer SPC-формула на SB CAPE/LCL, SRH 0–1 км и bulk shear 0–6 км; CIN в формулу не входит
- **SCP (local)** — локальная fixed-layer эвристика, не SPC SCP
- **STP(eff) / SCP(eff)** — SPC effective-layer композиты: STP использует ML CAPE/LCL/CIN, SCP — MU CAPE/CIN; оба используют ESRH/EBWD. При отсутствии effective layer выводятся `н/д`, fixed-layer значения остаются доступны
- **DCAPE** (Downdraft CAPE) — риск микропорывов/шквалов (metpy `downdraft_cape_cin` + ручной fallback с виртуальной температурой)
- EHI (Energy-Helicity Index, CAPE 0-3 км), BRN (Bulk Richardson Number)
- MCS Maintenance — устойчивость линий шквалов

**Уровень угрозы:** визуальная шкала 0-5 с учётом всех параметров (`calculate_threat_level`).

### Сезонный режим
Для грозового отчёта режим определяется по широте и месяцу (UTC): cool — ноябрь–март от |45°| и апрель/октябрь от |55°|; в остальных случаях warm. Южное полушарие зеркально: cool — май–сентябрь от |45°|, апрель/октябрь от |55°|. Пороги warm: CAPE 1000, shear 0-6 км 15 м/с, LCL 1500 м, CIN 150; cool: CAPE 200, shear 20 м/с, LCL 2500 м, CIN 100. В cool сочетание CAPE ≥ 200 и shear ≥ 20 м/с добавляет балл угрозы; при таком сочетании выводится предупреждение о проверке прокси thundersnow/snow-squall, а интерпретации shear/CAPE/CIN/LCL говорят о зимней конвекции, не о суперячейках.

**Границы эвристики:** переходные месяцы (апрель/октябрь) грубые; пороги 45°/55° — эвристика широты, не физическая модель; сезон считается по календарному месяцу UTC. В алертах `CAPE_FLOOR` — это лишь ранний выход «есть ли вообще конвекция» (warm 250, cool 100), он всегда ниже сезонного порога (`cape_min`), чтобы зимняя конвекция CAPE 200–250 не отсекалась.

### Система алертов
Подписки хранятся в SQLite (`data/alerts.db`, таблицы `alerts` и `alert_history`, кулдаун повторной отправки — 2 часа). Хардкоженного warm-only словаря `THRESHOLDS` больше нет: пороги опасной погоды берутся из `core.season_regime.thresholds_for(regime)` по широте и месяцу UTC подписки:

```python
# core/season_regime.thresholds_for(regime)
# warm: cape_min=1000, shear06_min=15, lcl_max=1500, cin_max=150
# cool: cape_min=200,  shear06_min=20, lcl_max=2500, cin_max=100

# alert_manager.CAPE_FLOOR — ранний выход «есть ли вообще конвекция»,
# НЕ порог срабатывания: warm 250, cool 100 (всегда ниже cape_min).
```

Три разных CAPE-числа — разные механизмы, не дублирование:
- **floor** (`alert_manager.CAPE_FLOOR`): дешёвый early exit, warm 250 / cool 100;
- **threshold** (`cape_min` в `thresholds_for`): одно из ≥3 условий алерта, warm 1000 / cool 200;
- **first-ball** (`calculate_threat_level`): первый балл уровня угрозы в отчёте, warm 250 / cool 150 — на срабатывание алерта не влияет.

Алерт формируется при совпадении ≥3 условий либо при сочетании CAPE ≥ 2000 Дж/кг + сдвиг ≥ 20 м/с (в warm — риск суперячеек, в cool — thundersnow/snow-squall). Лимит подписок — `MAX_ALERTS_PER_USER` (по умолчанию 5 уникальных координат, округлённых до `round(lat, 2), round(lon, 2)`); подписки на одну локацию дедуплицируются в один запрос погоды за цикл.

> ✅ **Статус:** рассылка подключена — фоновая задача `alerts_background_task` запускается через `JobQueue.run_repeating` в `bot.py` каждые 30 минут (первый запуск через 60 с после старта). Для каждой уникальной локации обновляются данные, считается отчёт с сезонным режимом, и при опасной обстановке пользователю приходит уведомление с кулдауном 2 часа; между локациями выдерживается пауза 2 с для защиты от rate-limit внешних API. В `alert_manager.py` есть `prune_history()`, но фоновая задача её не вызывает, поэтому автоматическая очистка истории сейчас не выполняется.

---

## 🛠 Технологический стек

- **Язык**: Python 3 (async/sync-микс: хендлеры `async def`, HTTP-запросы синхронные через `requests`/`httpx`)
- **Framework**: `python-telegram-bot` (v22+)
- **Метеорология**: `MetPy`, `NumPy`; для sounding данных — `pandas`, `Siphon` (Wyoming Upper Air / IGRA2)
- **Визуализация**: `Matplotlib`, `Pillow`
- **Хранение**: `SQLite` (стандартная библиотека `sqlite3`)
- **API**: Open-Meteo (основной источник), OpenWeatherMap (фьюжн приземных данных), RainViewer (радар)
- **AI**: цепочка fallback Groq (llama-3.3-70b) → GitHub Models (gpt-4o-mini) → Gemini → OpenRouter → LocalProvider (rule-based анализ без внешних API)
- **Логирование**: стандартный `logging` + ротационный файл `bot.log` (5 МБ × 3 бэкапа)
- **REST API**: `api.py` на FastAPI + Uvicorn (`fastapi`, `uvicorn` включены в `requirements.txt`)

---

## 📦 Установка

### 1. Клонирование репозитория
```bash
git clone https://github.com/lixynhay/StormLab.git
cd StormLab
```

### 2. Создание виртуального окружения (uv, Python 3.12)

Проект требует Python **≥3.12** (numpy ≥2.5.5). Если `uv` ещё не установлен:
```powershell
# Windows (user scope, без админа)
irm https://astral.sh/uv/install.ps1 | iex
```
```bash
# POSIX
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
uv venv --python 3.12
# активация: Windows — .venv\Scripts\activate, POSIX — source .venv/bin/activate
```

### 3. Установка зависимостей
```bash
uv pip install --no-build -r requirements.txt
```
`--no-build` — бывший `--only-binary=:all:`; он не даёт MetPy/numpy компилироваться на свежих интерпретаторах. Файл `uv.lock` в репозиторий не коммитится: источник истины — `requirements*.txt`, чтобы Dependabot продолжал присылать обновления (trade-off зафиксирован в `AGENTS.md`). Dev-инструменты (`pytest`, `pytest-cov`, `ruff`, `mypy`, `bandit`, `hypothesis`, `pip-audit` и др.) вынесены в `requirements-dev.txt`:
```bash
uv pip install --no-build -r requirements.txt -r requirements-dev.txt
```

Все зависимости REST API (`fastapi`, `uvicorn`) уже входят в `requirements.txt` — отдельная установка не требуется.

### 4. Настройка окружения
Скопируйте шаблон `.env.example` в `.env` и заполните значения. Обязателен только `BOT_TOKEN`, остальное — опционально:
```env
BOT_TOKEN=твой_токен_от_BotFather        # обязателен, иначе config.py поднимет RuntimeError
GROQ_API_KEY=ключ_Groq                  # опционально (AI, приоритет 1)
GITHUB_TOKEN=токен_GitHub               # опционально (AI, приоритет 2)
GEMINI_API_KEY=ключ_Google_AI           # опционально (AI, приоритет 3; модель — GEMINI_MODEL)
OPENROUTER_API_KEY=ключ_OpenRouter      # опционально (AI, приоритет 4)
OPENWEATHERMAP_API_KEY=ключ_OWM         # опционально (фьюжн приземных данных)
API_ACCESS_KEY=длинный_случайный_ключ   # обязательно для REST API
API_HOST=127.0.0.1                      # опционально (хост для python api.py)
ADMIN_USER_IDS=123456,789012            # опционально (id админов, bypass лимитов запросов)
```
При отсутствии ключей AI-провайдеров `/ai` автоматически работает через встроенный rule-based LocalProvider; без ключа OWM используется только Open-Meteo.

### 5. Запуск бота
```bash
python bot.py
```
Бот содержит встроенный цикл авто-рестарта (задержка `RESTART_DELAY_SECONDS`, защита от fast-fail циклов: после 5 подряд быстрых падений процесс завершается).

Запуск REST API:
```bash
python api.py   # uvicorn, порт 8000, хост из переменной API_HOST (по умолчанию 127.0.0.1)
```

- `GET /` — публичная интерактивная страница документации (`docs/api_docs.html`); Swagger/ReDoc/OpenAPI отключены.
- К остальным эндпоинтам `/api/*`, кроме публичного `/api/health`, требуется заголовок `X-API-Key` с **единым** значением `API_ACCESS_KEY` из `.env`. Если `API_ACCESS_KEY` не задан — ответ `401`.
- **Текущий механизм до деплоя key-store:** один общий `API_ACCESS_KEY` (не per-key/per-user авторизация). Key-store и выдача индивидуальных ключей **не реализованы** — не считайте их работающими.
- Действует rate-limit `REST_RATE_LIMIT = 60` запросов в минуту на ключ (сверх лимита — `429`).
- REST-путь сезонно-корректен после batch 2.5: `/api/storm`, `/api/chart/skewt` и `/api/ai-analysis` передают `regime`, вычисленный из широты и месяца UTC; раньше был silent-warm. `None`-поля (eff-композиты, DCAPE, интерпретации) рендерятся как `н/д` и в `/storm`, и в Skew-T/AI-контексте, без литерала `None`.

Эндпоинты: `/api/health`, `/api/geocode`, `/api/storm`, `/api/chart/profile`, `/api/chart/skewt`, `/api/radar`, `POST /api/ai-analysis`, `/api/time-offsets`.

### 6. Тесты
```bash
python -m pytest -q
```
Набор включает REST auth и REST-путь через `TestClient`, сезонный режим, алерты и подписки, LocalProvider (структурированный report, None-guard), effective-layer, формулы `storm_indices` и RainViewer tile/stub обработку. Текущий результат: **161 passed, 3 skipped**, покрытие **73.64 %** (`python -m pytest --cov=. --cov-report=term`).

---

## 📂 Структура проекта

В корне только точки входа, конфиги и документация. Весь код живёт в пакете `stormlab/` (обычные пакеты с `__init__.py`), логи — в `logs/`, рабочие планы — в `docs/plans/`. Команды запуска не изменились: `python bot.py` и `python api.py`.

```text
StormLab/
├── bot.py                    # тонкий wrapper -> stormlab.bot.main()
├── api.py                    # тонкий wrapper -> stormlab.api.main()
├── stormlab/
│   ├── __init__.py
│   ├── paths.py              # PROJECT_ROOT / DATA_DIR / LOGS_DIR
│   ├── bot.py                # Telegram-логика, callbacks, JobQueue, авто-рестарт
│   ├── api.py                # FastAPI endpoints + main()
│   ├── config.py             # конфигурация из .env
│   ├── logging_config.py     # ротация логов в logs/bot.log
│   ├── persistence.py        # AtomicPicklePersistence
│   ├── rate_limiter.py       # кулдауны команд
│   ├── alert_manager.py      # подписки и SQLite
│   ├── core/                 # storm_indices, effective_layer, season_regime, locks,
│   │                         # text_safety, async_helpers + __init__.py
│   ├── clients/              # openmeteo, openweathermap, data_fusion, geocoding,
│   │                         # sounding_api, radar_api + __init__.py
│   ├── render/               # chart_builder, skewt_builder, radar_builder + __init__.py
│   └── ai/                   # ai_analysis, ai_providers + __init__.py
├── docs/
│   ├── plans/                # PLAN.md, F06_FIX_PLAN.md, STRUCTURE_PLAN.md
│   ├── api_docs.html         # публичная страница GET /
│   └── AUDIT / CHARTS_AUDIT / DEAD_CODE* / CONCURRENCY / PERSISTENCE / VERIFICATION
├── tests/
├── scripts/sync_agents.py
├── agents/                   # канонические architect/coder/reviewer
├── skills/stormlab-dev.md
├── data/                     # gitignored: alerts.db, persistence.pkl
├── logs/                     # gitignored: bot.log + ротация 5 МБ × 3
├── graphify-out/, venv/
└── .claude/, .opencode/      # генерируются только через sync_agents.py
```

---

## 🎯 Примеры использования

**Грозовые индексы:**
`/storm Москва`
> Бот покажет CAPE, CIN, K-Index, STP, SCP и визуальную шкалу уровня угрозы + профиль атмосферы. Кнопками можно пересчитать на +3/+6/+12/+24 ч.

**Skew-T диаграмма:**
`/skewt Сочи`
> Бот построит аэрологическую диаграмму по модельным данным и предложит выбрать реальный зонд из ближайших станций — тогда будет построена двухпанельная картинка «модель vs зонд».

**AI-анализ:**
`/ai Казань`
> Все индексы и Skew-T контекст отправляются в LLM (первый доступный провайдер в цепочке), который даёт развёрнутый анализ на естественном языке.

**Радар:**
`/radar Екатеринбург`
> Склеенный радар осадков RainViewer с маркером города (кулдаун 300 с).

---

## 🔧 Особенности архитектуры

1. **Fallback-цепочки everywhere**: CAPE считается как MU → ML → SB (при ограничении числа уровней); AI — по цепочке провайдеров вплоть до локального rule-based анализа; зонды — перебор запусков 12Z/00Z по 4 ближайшим станциям.
2. **Защита от артефактов**: DCAPE интерпретируется по SPC (`params2.html`: >1000 Дж/кг — рост потенциала сильных нисходящих потоков), значения ≥1500 Дж/кг помечаются как экстремальные, но не отбрасываются; круговое среднее направления ветра при фьюже.
3. **Кэширование**: TTL-кэш ответов Open-Meteo, кэш геокодера, кэш каталога станций IGRA2 (7 дней), кэш радарных фреймов.
4. **Rate limiting**: in-memory кулдауны в `rate_limiter.py` для команд, inline-кнопок (refresh/Skew-T/AI/радар/выбор времени/станция), `/alert`, `/alerts`, `/unalert` и геокодинга; обход для `ADMIN_USER_IDS`. Concurrent updates отключены — общие кэши без блокировок (п.6b отложен).
5. **Лимиты Telegram**: callback-данные оптимизированы (макс. 64 байта) за счёт хранения контекста в `user_data`.
6. **Отказоустойчивость**: `bot.py` перезапускает Application при падениях с защитой от бесконечных fast-fail циклов; запросы к Open-Meteo защищены `CircuitBreaker` (после 3 подряд неудач «открывается» на 5 минут), ретраями и переиспользованием TCP/TLS-сессий (`requests.Session`).
7. **Безопасность REST API**: сравнение единого `API_ACCESS_KEY` через `hmac.compare_digest`, оконный rate-limit по хэшу ключа (один общий ключ, не per-key auth), отключённые Swagger/ReDoc в пользу собственной страницы документации.

---

## 📝 История изменений (changelog)

### 2026-11-28 — приёмка 3A/3B и Dead Code Elimination
- **3A**: защита REST (`time_index` → 422, `slot is None`), redaction секретов в логах/AI-тексте, escape только динамики, изоляция Skew-T-контекста по `(chat_id, message_id)`, обработка `Forbidden` без удаления подписок по другим ошибкам.
- **3B**: именованные/keyed локи для кэшей, ограниченный LRU-контекст, блокировки rate-limiter, атомарная запись persistence (temp + `fsync` + `os.replace`). `concurrent_updates(False)` сохранён; включение обсуждается отдельно (`docs/CONCURRENCY.md`).
- **Dead Code**: удалены неиспользуемые импорты/константы/функции, legacy `verify_batch1.py`, плагин `.opencode/plugins/graphify.js`, мусорные файлы и 4 зависимости (`groq`, `colorlog`, `Cartopy`, `scipy` — последний приходит транзитивно через MetPy). Подробности — `docs/DEAD_CODE_REPORT.md` и `PLAN.md`.
- **Метрики**: 161 passed / 3 skipped, покрытие 73.64 %, граф 761 → 747 узлов. Чистая установка `requirements.txt` и импорт `bot`/`api` проверены.

### 2026-11-26 — SPC formula corrections (read-only audit → applied)
- **Fixed-layer STP (`calculate_stp`)**: приведен в точное соответствие SPC (Thompson et al., begin.html): используется sbCAPE, sbLCL, SRH 0–1 км, 6BWD; CIN-член удалён (SPC fixed-STP не содержит CIN); 6BWD < 12.5 м/с → 0, > 30 м/с → cap 1.5.
- **Fixed-layer SCP**: переименована в `scp_fixed_local`, docstring: «не SPC» — первоисточник (help_scp.html, begin.html) определяет SCP только через effective-layer ингредиенты (muCAPE, ESRH, EBWD).
- **Effective inflow layer (`find_effective_layer`)**: реализован по SPC (begin.html, help_esrh.html) — base = первый уровень с parcel CAPE ≥ 100 И CIN ≥ −250; top = первый уровень выше где CAPE < 100 ИЛИ CIN < −250; fallback = parcel EL.
- **Effective SRH**: интегрируется от base до top effective inflow layer.
- **EBWD (`effective_bulk_shear`)**: теперь |V(0.5 × EL) − V(base)|, а не |V(EL) − V(base)| — по определению SPC (begin.html).
- **Effective STP (`stp_effective`)**: использует mlCAPE, mlLCL, mlCIN (SPC effective-STP); обнуляется, когда effective inflow base выше поверхности («the entire index is set to 0.0 when the effective inflow base is above the ground»).
- **Effective SCP (`scp_effective`)**: приведена к текущей help-странице SCP (help_scp.html) — EBWD lower bound 10 м/с (было 12.5), cap 1.0 при > 20 м/с (было 1.5 при 30); CIN-член `(-40/muCIN)` с cap 1.0 при muCIN ≥ −40.
- **Unity pins сохранены**: ESRH=100, EBWD=10 (EL=6000→0.5EL=3000), STP_eff=1.0 (ml-входы, base у земли), SCP_eff=4.5 (muCIN=−40).
- **Discriminating pins добавлены**: CIN=−300 внизу → effective layer None; EL=8000 → EBWD измеряется на 4000 м; muCIN=−80 → SCP_eff вдвое меньше; sbCIN не влияет на fixed STP; профиль с SRH 0–1 ≠ SRH 0–3 → fixed STP использует 0–1; 6BWD=10 → fixed STP=0.

---

## 🐛 Известные ограничения

- Высоты рассчитываются из стандартной атмосферы, а не из реальных данных (ограничение модельных API).
- Радар RainViewer иногда недоступен во время глобальных обновлений их серверов.
- AI-анализ зависит от доступности и квот внешних API (автоматически переключается на fallback-провайдеров вплоть до локального анализа).
- Автоматические тесты покрывают REST auth и REST-путь через `TestClient` (включая сезон в `/api/storm` и `/api/ai-analysis`), сезонный режим, логику алертов (включая зимний CAPE 200–250), подписки/лимиты, effective-layer, формулы `storm_indices`, LocalProvider (структурированный report, None-guard, regime-зависимые hazards), Radar API и tile/stub detection. Покрытие: `tests/test_batch2.py`, `tests/test_batch2_5.py`, `tests/test_local_provider.py` и базовые тесты. Планировщик (`JobQueue`) и реальная Telegram-доставка проверяются живьём оператором, unit-покрытие здесь частичное. `prune_history()` определён в `alert_manager.py`, но автоматически не вызывается; `_self_check()` удалён как мёртвый код. Покрытие кода — 73.1 %.
- **Три разных CAPE-числа — не опечатка:** floor алерта (`CAPE_FLOOR`, early exit «есть ли конвекция вообще») = warm 250 / cool 100; порог алерта (`cape_min`, одно из ≥3 условий) = warm 1000 / cool 200; первый балл угрозы в отчёте (`calculate_threat_level`) = warm 250 / cool 150. Балл угрозы не является gate для алерта.
- REST `/api/storm`, `/api/chart/skewt` и `/api/ai-analysis` теперь передают сезон, вычисленный из широты и месяца UTC (раньше был silent-warm). Южное полушарие инвертирует месяцы, границы 45°/55° — эвристика, не физическая модель.
- **Дисклеймер**: Расчёт по доступному модельному профилю. Не заменяет официальный прогноз метеослужб.

---

## 🤝 Вклад в проект

Pull requests приветствуются! Для крупных изменений сначала откройте issue для обсуждения.

---

## 💡 Поддержка

Если бот полезен, вы можете поддержать оплату серверов:
- **TON**: `UQC-plwq4_uIPlVxTSba2IAm3L805D6iWxdMCMaVXeqwz5CZ`
- **Boosty**: [Поддержать проект](https://boosty.to/lixynyt167/purchase/1865325)
