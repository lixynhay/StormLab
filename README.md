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
Для грозового отчёта режим определяется по широте и месяцу: cool — ноябрь–март от 45° и апрель/октябрь от 55°; в остальных случаях warm. Пороги warm: CAPE 1000, shear 0-6 км 15 м/с, LCL 1500 м, CIN 150; cool: CAPE 200, shear 20 м/с, LCL 2500 м, CIN 100. В cool сочетание CAPE ≥ 200 и shear ≥ 20 м/с добавляет балл угрозы; при таком сочетании выводится предупреждение о проверке прокси thundersnow/snow-squall.

### Система алертов
Подписки хранятся в SQLite (`data/alerts.db`, таблицы `alerts` и `alert_history`, кулдаун повторной отправки — 2 часа). Пороги опасной погоды в `alert_manager.py`:

```python
THRESHOLDS = {
    "cape_min": 1000,     # Дж/кг
    "shear_06_min": 15,   # м/с (bulk shear 0-6 км)
    "lcl_max": 1500,      # м
    "cin_max": 150,       # Дж/кг
}
```

Алерт формируется при совпадении ≥3 условий либо при сочетании CAPE ≥ 2000 Дж/кг + сдвиг ≥ 20 м/с (риск суперячеек).

> ✅ **Статус:** рассылка подключена — фоновая задача `alerts_background_task` запускается через `JobQueue.run_repeating` в `bot.py` каждые 30 минут (первый запуск через 60 с после старта). Для каждой подписки обновляются данные, считается отчёт, и при опасной обстановке пользователю приходит уведомление с кулдауном 2 часа; между подписками выдерживается пауза 2 с для защиты от rate-limit внешних API. В `alert_manager.py` есть `prune_history()`, но фоновая задача её не вызывает, поэтому автоматическая очистка истории сейчас не выполняется.

---

## 🛠 Технологический стек

- **Язык**: Python 3 (async/sync-микс: хендлеры `async def`, HTTP-запросы синхронные через `requests`/`httpx`)
- **Framework**: `python-telegram-bot` (v22+)
- **Метеорология**: `MetPy`, `NumPy`; для sounding данных — `pandas`, `Siphon` (Wyoming Upper Air / IGRA2)
- **Визуализация**: `Matplotlib`, `Pillow`
- **Хранение**: `SQLite` (стандартная библиотека `sqlite3`)
- **API**: Open-Meteo (основной источник), OpenWeatherMap (фьюжн приземных данных), RainViewer (радар)
- **AI**: цепочка fallback Groq (llama-3.3-70b) → GitHub Models (gpt-4o-mini) → Gemini → OpenRouter → LocalProvider (rule-based анализ без внешних API)
- **Логирование**: `colorlog` + ротационный файл `bot.log` (5 МБ × 3 бэкапа)
- **REST API**: `api.py` на FastAPI + Uvicorn (`fastapi`, `uvicorn` включены в `requirements.txt`)

---

## 📦 Установка

### 1. Клонирование репозитория
```bash
git clone https://github.com/lixynhay/StormLab.git
cd StormLab
```

### 2. Создание виртуального окружения
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Установка зависимостей
```bash
pip install --upgrade pip
pip install -r requirements.txt
```
*(Рекомендуется использовать `--only-binary=:all:` для избежания компиляции C-расширений на свежих версиях Python).*

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
В `.env.example` также присутствуют зарезервированные переменные AiTunnel (`AITUNNEL_API_KEY/BASE_URL/MODEL`) — в текущей версии `config.py` они не читаются.
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
- К остальным эндпоинтам `/api/*`, кроме публичного `/api/health`, требуется заголовок `X-API-Key`. Если `API_ACCESS_KEY` не задан — ответ `401`.
- Действует rate-limit `REST_RATE_LIMIT = 60` запросов в минуту на ключ (сверх лимита — `429`).

Эндпоинты: `/api/health`, `/api/geocode`, `/api/storm`, `/api/chart/profile`, `/api/chart/skewt`, `/api/radar`, `POST /api/ai-analysis`, `/api/time-offsets`.

### 6. Тесты
```bash
python -m pytest -q
```
Набор включает REST auth, сезонный режим, effective-layer, формулы `storm_indices` и RainViewer tile/stub обработку.

---

## 📂 Структура проекта

Точки входа и конфигурация остаются в корне; внутренние модули сгруппированы по назначению. Каталоги Python-модулей работают как namespace packages и не содержат `__init__.py`.

```text
StormLab/
 ├── bot.py                    # Telegram entrypoint, команды, callbacks, JobQueue, авто-рестарт
 ├── api.py                    # REST entrypoint: FastAPI auth/rate-limit и endpoints
 ├── config.py                 # Конфигурация из .env
 ├── logging_config.py         # Логирование с ротацией
 ├── alert_manager.py          # Подписки и SQLite alert history
 ├── rate_limiter.py           # Кулдауны команд
 ├── core/
 │   ├── storm_indices.py      # Метеорологические индексы и storm report
 │   ├── effective_layer.py    # SPC effective layer, ESRH/EBWD, STP(eff)/SCP(eff)
 │   └── season_regime.py      # Warm/cool thresholds и интерпретация
 ├── clients/
 │   ├── openmeteo_api.py      # Профили Open-Meteo, cache/retries/CircuitBreaker
 │   ├── openweathermap_api.py # Опциональные приземные данные OWM
 │   ├── data_fusion.py        # Слияние текущих погодных данных
 │   ├── geocoding.py          # Геокодирование Open-Meteo
 │   ├── sounding_api.py       # Поиск и загрузка Wyoming/IGRA2 soundings
 │   └── radar_api.py          # RainViewer frame discovery/cache
 ├── render/
 │   ├── chart_builder.py      # Skew-T профиль с parcel/CAPE/CIN
 │   ├── skewt_builder.py      # Skew-T, hodograph, sounding comparison
 │   └── radar_builder.py      # RainViewer tile mosaic и marker
 ├── ai/
 │   ├── ai_analysis.py        # AI prompt и fallback orchestration
 │   └── ai_providers.py       # Groq/GitHub/Gemini/OpenRouter/Local providers
 ├── docs/
 │   ├── api_docs.html         # Публичная страница GET /
 │   ├── AUDIT.md              # Технический аудит
 │   ├── CHARTS_AUDIT.md       # Аудит chart/render систем
 │   ├── DEAD_CODE.md          # Импортёры и inventory модулей
 │   └── VERIFICATION.md       # Результаты проверок
 ├── tests/
 │   ├── test_api_auth.py      # REST auth/docs/health/rate-limit
 │   ├── test_effective_layer.py
 │   ├── test_radar_api.py
 │   ├── test_radar_builder.py # RainViewer fixtures: echo/transparent/stub
 │   ├── test_season_regime.py
 │   ├── test_skewt_builder.py
 │   └── test_storm_indices_core.py
 ├── requirements.txt
 └── data/                     # Локальная SQLite и persistence; игнорируется Git
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
2. **Защита от артефактов**: санкчек для DCAPE (игнорирует значения >1500 Дж/кг на разреженной сетке Open-Meteo); круговое среднее направления ветра при фьюже.
3. **Кэширование**: TTL-кэш ответов Open-Meteo, кэш геокодера, кэш каталога станций IGRA2 (7 дней), кэш радарных фреймов.
4. **Rate limiting**: in-memory кулдауны на каждую команду (`rate_limiter.py`), обход для `ADMIN_USER_IDS`.
5. **Лимиты Telegram**: callback-данные оптимизированы (макс. 64 байта) за счёт хранения контекста в `user_data`.
6. **Отказоустойчивость**: `bot.py` перезапускает Application при падениях с защитой от бесконечных fast-fail циклов; запросы к Open-Meteo защищены `CircuitBreaker` (после 3 подряд неудач «открывается» на 5 минут), ретраями и переиспользованием TCP/TLS-сессий (`requests.Session`).
7. **Безопасность REST API**: сравнение ключа через `hmac.compare_digest`, оконный rate-limit по хэшу ключа, отключённые Swagger/ReDoc в пользу собственной страницы документации.

---

## 📝 История изменений (changelog)

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
- Автоматические тесты покрывают REST auth, season regime, effective-layer, основные формулы `storm_indices`, Radar API и tile/stub detection. Логика условий алертов и планировщик не имеют отдельных unit-тестов; `_self_check()` в `alert_manager.py` определён, но автоматически не запускается.
- **Дисклеймер**: Расчёт по доступному модельному профилю. Не заменяет официальный прогноз метеослужб.

---

## 🤝 Вклад в проект

Pull requests приветствуются! Для крупных изменений сначала откройте issue для обсуждения.

---

## 💡 Поддержка

Если бот полезен, вы можете поддержать оплату серверов:
- **TON**: `UQC-plwq4_uIPlVxTSba2IAm3L805D6iWxdMCMaVXeqwz5CZ`
- **Boosty**: [Поддержать проект](https://boosty.to/lixynyt167/purchase/1865325)
