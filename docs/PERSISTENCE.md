# Persistence — дизайн замены (Batch 4, пока НЕ реализовано)

## Текущее состояние (3B)
- `stormlab/bot.py::build_application` создаёт `AtomicPicklePersistence` (graphify: `callers:build_application`).
- `stormlab/persistence.py::_dump_singlefile` пишет temp-файл → `fsync` → `os.replace`; `flush()` PTB v22 вызывает `_dump_singlefile`, семантика сохранена.
- `stormlab/bot.py` при первом старте всё ещё делает `pickle.dump({...})` в `data/persistence.pkl` (graphify: `find "pickle.dump"` → `stormlab/bot.py:L805`, `stormlab/persistence.py`).
-Unit-тесты `tests/test_persistence_atomic.py`: валидный файл, прерывание записи → старый файл цел, `.persist_*` не остаются. Живой рестарт оператором не проверен.

## Проблема
- Атомарная запись закрывает краш-коррапт, но **не закрывает RCE** при подмене `.pkl` (pickle исполняет код при загрузке).
- Один инстанс бота сейчас — конкурентная запись не критична; при нескольких инстансах pickle-файл — общая точка записи.
- `callback_data` содержит `datetime`/`tuple`; pickle сериализует их неявно — нужен явный контракт.

## Матрица вариантов

| Вариант | Риск | Стоимость | Откат |
|---|---|---|---|
| **SQLite** (`sqlite3` под тем же `threading.RLock`, либо `aiosqlite` — новой зависимости нет в `requirements.txt`) | низкий: транзакции, нет произвольного кода, параллельные читатели | средняя: схема, кодексы, тесты миграции | высокий: `.pkl` остаётся, флаг переключения формата |
| **JSON** (`orjson` — зависимости нет; stdlib `json` доступен) | низкий/средний: нет RCE, но нужна原子的 перезапись и явные кодексы | низкая/средняя: ручные кодексы `datetime`/`tuple` | высокий: `.pkl` остаётся, читаем старый формат |
| **Оставить pickle + atomic** | высокий: RCE при подмене файла | минимальная | не требуется |

## Требования к миграции
- Скрипт `tools/migrate_stormlab/persistence.py` (ещё не создан): `dry-run` по умолчанию, читает `.pkl` через `_BotUnpickler`, пишет новый формат, печатает diff ключей.
- Схема/ключи обязаны покрыть: `bot_data`, `chat_data`, `user_data`, `conversations`, `callback_data`.
- Контракт сериализации: `datetime` → ISO-8601 (`datetime.isoformat()`), `tuple` → список с явной типизацией в схеме; **без pickle**.
- Откат: новый формат не удаляет `data/persistence.pkl`, пока не пройден один полный цикл `alerts_background_task` (30 мин) и рестарт.
- Решение — за оператором; Batch 4 кодом не стартует.

## Что проверено / не проверено
- Проверено: graphify `find "pickle.dump"`, `usages:pickle.load`, `callers:_dump_singlefile`, unit-тесты.
- Не проверено: живой `/start` + перезапуск, `kill -9` во время `_dump_singlefile` (требует оператора, §3.4).
