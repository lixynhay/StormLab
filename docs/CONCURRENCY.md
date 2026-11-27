# Concurrency — матрица и предусловия (Batch 4, пока НЕ реализовано)

## Текущая модель
- `concurrent_updates=False` (`bot.py:828`), APPLY NO CHANGE. Обновления PTB сериализуются; воркеры `to_thread` всё равно могут перекрываться с `JobQueue`.
- History: batch 3B добавил `core/locks.py` (`get_lock`, `KeyedLocks`) и закрыл часть глобалов.

## Матрица «глобал / лок / тип / владелец»

| Глобал | Лок | Тип | Владелец | Статус |
|---|---|---|---|---|
| `OpenMeteoAPI._cache`, `_cache_timestamps` | `get_lock("openmeteo_api")` | `threading.RLock` | экземпляр API | закрыт |
| `_GEO_CACHE` (`clients/geocoding.py`) | `get_lock("geocoding")` | `threading.RLock` | модуль | закрыт |
| `_STATIONS_CACHE`, `_SOUNDING_CACHE`, `_SOUNDING_TS`, `_PROBE_CACHE` | `get_lock("sounding_api")` | `threading.RLock` | модуль | закрыт |
| Radar `_cache` | `get_lock("radar_api")` | `threading.RLock` | модуль | закрыт |
| `rate_limiter._rate_limits` | `_lock` | `threading.RLock` | модуль | закрыт; check-and-set + prune каждые 1000 вызовов |
| `bot._skewt_ctx` | `_skewt_ctx_lock`, `put/get/drop_skewt_ctx`, `OrderedDict` ≤512 | `threading.Lock` | модуль | закрыт; ключ `(chat_id, message_id)` |
| `alert_manager` SQLite | `_connect()` + SQLite транзакции | `threading`-совместимые соединения | модуль | соединения закрываются в `finally` |
| **`api._rest_rate_limits`** (`require_api_key`, async middleware) | **нет** | нужен `asyncio.Lock` | модуль | **НЕ закрыто** |
| **`sounding_api._NET_WARN_TS`** (`_log_network_unavailable`) | **нет** | `threading.RLock` (`_SOUNDING_LOCK`) | модуль | **НЕ закрыто** |
| `PicklePersistence` | `_io_lock` | `threading.RLock` | `AtomicPicklePersistence` | закрыт для одного процесса; мульти-процесс — открытый риск |

## Предусловия обсуждения `concurrent_updates(True)`
1. `_rest_rate_limits` обёрнут в `asyncio.Lock` (не `threading.Lock`!) — **не сделано**.
2. `_NET_WARN_TS` переведён под `_SOUNDING_LOCK` — **не сделано**.
3. Нагрузочный прогон N=50 параллельных `/storm` (2 чата) и `/api/storm`: нет `KeyError`, `database is locked`, потери инкрементов rate-limit — **не сделано** (есть только unit-тест 2 потоков).
4. `prune_history()` (job) и `_prune_user_data()` (хендлеры) не конкурируют: job не трогает `context.user_data`, хендлеры не вызывают SQLite напрямую — по графу конфликтов нет; живое подтверждение требуется.
5. Документ этой матрицы — создан; решение оператора.

## Что НЕ делать до отдельного батча
- Не включать `concurrent_updates(True)`.
- Не заменять `threading.Lock` на `asyncio.Lock` в синхронных модулях (`threading.Lock` в async-коде блокирует event loop).
- Не трогать метео-формулы, `render/*`, HTTP-клиент.

## Ссылки на граф
- `graphify query "get_lock KeyedLocks where are locks used in caches"`
- `graphify query "usages of _cache _rate_limits _rest_rate_limits _skewt_ctx concurrency globals"`
- `graphify query "where is _rest_rate_limits mutated in api.py middleware async"`
- `graphify explain "_log_network_unavailable" --all`
