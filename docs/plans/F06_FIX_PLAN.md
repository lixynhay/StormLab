# План фикса F-06 — разблокировка event loop (architect, НЕ реализовано)

Статус: **ОЖИДАЕТ ОДОБРЕНИЯ**. Код не менялся.

## 1. Проблема и пруф (до фикса)

Синхронные сетевые/вычислительные вызовы внутри `async def` REST-эндпоинтов:

| Файл:строка | Вызов |
|---|---|
| `api.py:236` | `resolve_city(query)` — HTTP requests |
| `api.py:251-254` | `_get_fused_data(...)`, `build_storm_report(...)`, `format_storm_text(...)` |
| `api.py:343-347` | `_get_fused_data`, `build_storm_report`, `build_skewt_context_for_ai`, `generate_storm_analysis` (AI + HTTP) |

Синхронные `def`-эндпоинты (`api.py:270 get_profile_chart`, `:291 get_skewt_chart`, `:316 get_radar`) **уже выполняются FastAPI в threadpool** — их трогать не нужно.

Пруф воспроизведения (`graphify-out/verify/loop_block.py`, ASGITransport, `_get_fused_data` → `time.sleep(0.30)`):
```
до фикса:
F-06 blocking: health=328.0 ms while /api/storm=328.0 ms
VERDICT: EVENT LOOP BLOCKED
10x /api/storm: p50=3016.0 ms p95=3016.0 ms wall=3016.0 ms  (≈ 10 × 300 мс — полная сериализация)
```
Реальный Skew-T-рендер ~2.8 с/вызов (50 рендеров за 138.9 с), поэтому цена ошибки в проде выше синтетической.

## 2. Thread-safety matplotlib — важное уточнение

`(graphify explain "_serialized_matplotlib_render")`:
- `render/chart_builder.py:18` — `_MATPLOTLIB_RENDER_LOCK = threading.Lock()`;
- `render/chart_builder.py:21-26` — декоратор `_serialized_matplotlib_render`, который оборачивает **оба** рендера (`build_profile_chart` @ `chart_builder.py:82`, `build_skewt_chart` @ `skewt_builder.py:399`);
- в обоих рендерах есть `finally: plt.close(fig)`.

**Вывод:** параллельные `to_thread`-рендеры уже сериализуются существующим локом — нового лока добавлять нельзя (риск deadlock/coarse-grained двойной сериализации). Переход на Figure API без pyplot — отдельная будущая работа, в этот батч не входит.

## 3. Дизайн правки

### Шаг 1 — helpers (новый файл `core/async_helpers.py`)
```python
async def run_sync(fn, *args, **kwargs):
    """Offload blocking sync work to the default thread pool."""
    return await asyncio.to_thread(fn, *args, **kwargs)
```
Причины: единая точка вызова, легко грепается при аудите, не меняет сигнатуры. `contextvars` копируются `to_thread` автоматически (Python 3.11).

### Шаг 2 — `api.py` (только async-эндпоинты)
Ввести модульный sync-агрегатор, чтобы не делать три переключения контекста на запрос:
```python
def _storm_report_sync(lat, lon, time_index, city):
    current, pressure, source, regime = _get_fused_data(lat, lon, time_index)
    report = build_storm_report(current, pressure, regime=regime)
    text = format_storm_text(report, city, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    return current, pressure, source, regime, report, text
```
- `get_storm_report` (`:251-254`) → `await run_sync(_storm_report_sync, lat, lon, time_index, city)`.
- `geocode` (`:236`) → `await run_sync(resolve_city, query)`.
- `get_ai_analysis` (`:343-347`) → отдельный sync-агрегатор `_ai_analysis_sync(...)`, объединяющий `_get_fused_data` + `build_storm_report` + `build_skewt_context_for_ai` + `generate_storm_analysis`; endpoint остаётся `async def`, меняется только способ вызова.
- `get_profile_chart` / `get_skewt_chart` / `get_radar` **не трогать** (уже sync def → FastAPI threadpool).
- Middleware `require_api_key` не трогать (hmac + dict, микросекунды).

Ответные модели, статусы, redaction и `_internal_error` — без изменений.

### Шаг 3 — `bot.py` (только оставшиеся синхронные вызовы расчёта)
Остальные тяжёлые вызовы уже обёрнуты (`bot.py:168,242,277,295,316,323,345,353,386,398,559,560,638,654,667,741`). Осталось обернуть `build_storm_report` в пяти местах:
- `bot.py:256` (`_send_storm_report`),
- `bot.py:309` (`_send_skewt`),
- `bot.py:388` (`_send_ai_analysis`),
- `bot.py:564` (`_alerts_list_text`),
- `bot.py:745` (`alerts_background_task`).

Формат: `report = await run_sync(build_storm_report, current_data, pressure_data, regime=regime)`.
`format_storm_text` при необходимости оборачивается тем же способом (дешёвый вызов, но внутри `report`-агрегата). JobQueue registration и `concurrent_updates(False)` не трогать.

### Шаг 4 — регрессионный тест
Новый `tests/test_api_async_nonblocking.py` (без внешней сети):
1. monkeypatch `api._get_fused_data` → `time.sleep(0.25)` + поднятый `HTTPException(503)` (как в verify-скрипте), `api.API_ACCESS_KEY = "test-key"`.
2. `heavy = create_task(client.get("/api/storm?...", headers=...))`, затем замерить `await client.get("/api/health")`;	assert latency < **50 мс** (порог с запасом для CI; локальный критерий — <10 мс).
3. 10 параллельных `/api/storm` через `asyncio.gather`:	assert wall < **1.5 с** в тесте (локальный критерий p95 < 1000 мс).
4. Проверить, что ни один ответ не содержит секретов и что `/api/health` = 200.

Тест детерминированный: сравнение latencies, а не «по ощущениям».

## 4. Критерии приёмки (прогон `verify/loop_block.py` ДО/ПОСЛЕ)

| Метрика | До (факт) | Ожидаемо после |
|---|---|---|
| `/api/health` при параллельном `/api/storm` | 328 мс | **< 10 мс** |
| 10 параллельных `/api/storm` p95 | 3016 мс | **< 1000 мс** |

Дополнительно: `pytest -q` ≥ 155 passed / 3 skipped; coverage ≥ 73.1 %; `ruff check --select F401,F841` — 0 новых находок; `python -X dev -c "import bot, api"` без Python-warnings.

## 5. Риски и меры

| Риск | Мера |
|---|---|
| Насыщение threadpool | Default executor = min(32, CPU+4); 10 параллельных запросов помещаются. При росте — явный `ThreadPoolExecutor(max_workers=...)` отдельным батчем. |
| `asyncio.wait_for` не отменяет поток | Не добавлять `wait_for` вокруг `to_thread` в этом батче; таймауты HTTP остаются внутри `requests`/AI-клиентов. |
| Гонка pyplot | Уже есть `_MATPLOTLIB_RENDER_LOCK`; второй лок не добавляем. |
| Изменение(sqlite) соединений в потоках | `alert_manager._connect()` создаёт соединение на вызов — потокобезопасно. |
| `concurrent_updates(True)` | Не включать; батч не меняет модель конкуренции PTB. |
| Регрессия SPC/рендера | В батче только обёртки вызовов; формулы и `render/*` не меняются (кроме отсутствующих правок). |

## 6. Порядок работ и откат

1. Ветка `fix-f06-async`, один коммит: `core/async_helpers.py`, `api.py`, `bot.py`, `tests/test_api_async_nonblocking.py`.
2. Прогон `verify/loop_block.py` до (уже есть: 328 мс / 3016 мс) и после, записать оба вывода в `docs/CONFLICTS.md`.
3. Полный pytest + ruff + smoke import; `graphify update .` после коммита.
4. Откат при провале любого критерия: `git revert` коммита; finding остаётся OPEN.
5. Мёрж в `main` — по решению оператора (в этот батч не входит).

**Не делаем в этом батче:** `concurrent_updates(True)`, Figure API rewrite, второй render lock, изменение формул/порогов, смену HTTP-клиентов.
