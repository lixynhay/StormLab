# LIVE_SMOKE_CHECKLIST — живая приёмка (OPERATOR)

Статус: **живой Telegram НЕ ВЫПОЛНЕНО агентом** — в среде нет тестового токена. Это последний непроверенный контур: F-01 (radar path/tile) и F-06 (async/offload) закрыты юнит-тестами и замерами, но реальную картинку в чате и реальный `/storm` никто не видел. Порядок приёмки: **сначала `/radar`**, затем остальные команды.

AUTO-пруф агента (без Telegram): живой запрос RainViewer + рендер выполнены — path `/v2/radar/27e966f6628e`, PNG **600×558 RGBA, 1563 B**, `no_echo=True` (в момент запроса эхо над Москвой отсутствовало; это валидный PNG, не "unavailable"). Доставка в Telegram и кадр с реальным эхо подтверждаются оператором.

Условные обозначения: `[ ]` — не проверено, `[x]` — подтверждено оператором, `AUTO` — подтверждено агентом статически/юнит-тестами или живым запросом без Telegram (см. `VERIFICATION_REPORT.md`).

## 3.1 Старт и жизненный цикл
- [ ] `python bot.py` стартует, JobQueue жив, первый alert-прогон в логе через 60 с.
- [ ] Авто-рестарт: искусственный краш → перезапуск через `RESTART_DELAY_SECONDS` (5 с).
- [ ] Fast-fail: 5 быстрых падений подряд → процесс завершается, нет бесконечного цикла.
- [ ] Graceful shutdown (Ctrl+C): SQLite/сессии закрыты, нет висящих задач.

## 3.2 Команды (реальная сеть) — `/radar` ПЕРВЫМ
- [ ] **`/radar Москва`** — реально отдаёт картинку, а не "unavailable" (F-01). `AUTO`: сеть + рендер OK (PNG 600×558, `no_echo=True`); `OPERATOR`: доставка в Telegram и кадр с эхо.
- [ ] `/start`, `/help` — отвечают, MarkdownV1 не ломается.
- [ ] `/storm Москва` — индексы не `None`, шкала угрозы, профиль.
- [ ] `/storm Сочи` + кнопки +3/+6/+12/+24 ч — пересчёт и callback.
- [ ] `/skewt Москва` — PNG рендерится, выбор станции, сравнение модель vs зонд.
- [ ] `/ai Москва` — ответ провайдера; какой именно — по логу.
- [ ] `/alert` → `/alerts` → `/unalert` — подписка/список/отписка, дедупликация.
- [ ] Несуществующий город — понятная ошибка, не краш.
- [ ] Валидация: пустой аргумент, 200 символов, emoji, SQL-строка — не краш.

## 3.3 Алерты end-to-end
- [ ] Подписка → фоновый цикл (30 мин) → уведомление пришло.
- [ ] Кулдаун 2 ч: повтор не спамит.
- [ ] Лимит 5 подписок на пользователя.
- [ ] `prune_history()` реально чистит `alert_history` (SQL count до/после) — AUTO-STATIC: функция определена, автоматически не вызывается; живое подтверждение требуется.

## 3.4 REST API (живой uvicorn)
- [ ] `/api/health` без ключа → 200.
- [ ] `/api/storm` без ключа → 401, с ключом → 200.
- [ ] Неверный ключ → 401 (timing-safe — `hmac.compare_digest`, AUTO-CODE).
- [ ] 61 запрос за минуту → 429 (AUTO: `tests/test_api_auth.py::test_api_rate_limit` — PASS).
- [ ] Все endpoints: geocode/storm/profile/skewt/radar/ai-analysis/time-offsets.
- [ ] Сезон ноябрь + Москва → cool-пороги в ответе (AUTO-PURE: `get_regime(55.75, 11) == "cool"`).

## 3.5 AI fallback-цепочка
- [ ] Все ключи есть → Groq (приоритет 1).
- [ ] Битый Groq → GitHub → Gemini → OpenRouter.
- [ ] Все ключи убраны → LocalProvider, осмысленный сезонный ответ.
- [ ] Таймаут провайдера → переход дальше, без зависания.

## 4 Async/concurrency (живая часть)
- [ ] Два пользователя: `/storm` (тяжёлый рендер) и `/help` — замерить latency `/help`.
  - **AUTO-ПРУФ уже есть**: `/api/health` ждал 328 мс пока выполнялся `/api/storm` с sync-задержкой 300 мс; 10 параллельных `/api/storm` уложились в 3016 мс ≈ 10×300 мс (полная сериализация). См. `docs/CONFLICTS.md` F-06.
- [ ] 10 одновременных `/storm` — живые p50/p95 (AUTO-замер на REST см. выше).
- [ ] SQLite: фоновый alert-цикл пишет + handler читает — `database is locked`?
- [ ] Общие кэши под нагрузкой (AUTO: `tests/test_locks.py` — PASS; 2 потока).
- [ ] `user_data` изоляция (AUTO: `test_ctx_is_keyed_by_chat_and_message` — PASS).
- [ ] Callback tampering: `time:5`, `time:-1` — **AUTO-НАХОДКА: нет bounds check** (`bot.py:596`), живой краш подтвердить оператором.
- [ ] Rate limiter: 100 запросов, pruning (AUTO: 100/100 allowed, 20×same-user → 1 allowed, prune удалил 50 простроченных).
- [ ] JobQueue vs авто-рестарт: job не задваивается.

## 5 Отказоустойчивость (живая часть)
- [ ] Open-Meteo недоступен → retries → CircuitBreaker open → понятное сообщение → recovery.
- [ ] RainViewer лежит → graceful "недоступен" (AUTO: `test_unavailable_radar_is_503` — PASS).
- [ ] Wyoming/IGRA2 недоступны → fallback станции.
- [ ] OWM ключ битый → только Open-Meteo (AUTO: импорт без ключа проходит).
- [ ] Telegram flood control (`retry_after`) → бот ждёт.
- [ ] SQLite битый/заблокирован → понятная ошибка.
- [ ] NaN/missing fields → "н/д", не литерал `None` (AUTO: 37 тестов failure-injection — PASS).
- [ ] Сеть пропала посреди запроса → timeout.

## 6 Нагрузка (живая часть)
- [ ] Matplotlib figure leak: 50 рендеров → `plt.get_fignums()` не растёт. **AUTO: 50/50 рендеров, fignums 0→0, 138.9 с (~2.8 с/рендер)**.
- [ ] Radar mosaic: память на склейке тайлов.
- [ ] LRU-кэши: 600 городов → `_GEO_CACHE` ≤500. **AUTO (с WIP): 600 вызовов с моком сети → ровно 500, oldest evicted, newest kept.**
- [ ] requests.Session: переиспользование, нет утечки FD.
- [ ] Soak 12–24 ч: RSS, SQLite, ротация логов (5 МБ × 3).
- [ ] REST 60 req/min на ключ — точность лимитера (AUTO-юнит: PASS).

## 7 Метео-корректность (живая часть)
- [ ] Москва (55°N, ноябрь) → cool; Сочи (43°N) → warm; Мурманск (69°N) → cool; Сидней (−33.87°, ноябрь) → warm. **AUTO-PURE: все 4 совпали.**
- [ ] CAPE-числа (floor/threshold/first ball) соответствуют README.
- [ ] STP/SCP на реальном профиле — физически разумные диапазоны.
- [ ] Skew-T модель vs зонд — сравнение строится.
- [ ] None-поля → "н/д" везде (AUTO: `tests/test_local_provider.py` — PASS).

## 8 Security (живая часть)
- [ ] Ключ не утекает в логи/500-ответы. **AUTO: `_internal_error()` возвращает только request_id; `detail=str(e)` отсутствует; `test_calculation_error_hides_internals` — PASS.**
- [ ] Markdown-инъекция: `*_[]()` в городе и AI-ответе — escape (AUTO: `test_text_safety.py` — PASS).
- [ ] Callback tampering (AUTO-НАХОДКА: см. п. 4).
- [ ] SQL injection в `/alert` — параметризованные запросы (AUTO-STATIC: все `execute()` с `?`).
- [ ] Path traversal в radar tile — regex `^/v2/radar/[A-Za-z0-9_-]{1,64}$` (AUTO: 10 parametrized tests — PASS).
- [ ] `ADMIN_USER_IDS` не обходит REST-авторизацию (AUTO-STATIC: только `rate_limiter.py`).
- [ ] Секреты в логах: `redact_secrets()` (AUTO: `test_batch3a.py::test_redact_secrets_removes_appid` — PASS).

---

**Итог:** AUTO-часть выполнена и документирована; OPERATOR-часть ожидает тестового токена и внешних ключей. Ни один живой пункт не отмечен `[x]` агентом — это было бы недостоверно.
