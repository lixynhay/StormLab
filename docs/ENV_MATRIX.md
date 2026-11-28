# ENV_MATRIX — совместимость окружений (AUTO)

Дата: 2026-11-28. Репозиторий: `main` @ `f0919cc`. Read-only проверки, фиксов нет.

## Python

| Версия | Доступна | Чистый venv + `pip install --only-binary=:all: -r requirements.txt` | pytest | `import bot, api` |
|---|---|---|---|---|
| 3.11.9 (`py -0` → `-V:3.11 *`, system + `venv`) | да | да (`%TEMP%\stormlab-clean`, без `--only-binary`; все пакеты поставились бинарниками) | **155 passed / 3 skipped** | OK |
| 3.12 | нет | не проверялось — интерпретатор отсутствует | — | — |
| 3.13 | нет | не проверялось — интерпретатор отсутствует | — | — |

**Критерий «≥2 версии Python» НЕ выполнен по причине окружения:** на машине установлен только Python 3.11.9. Это не блокер кода, но пробел в матрице — на 3.12/3.13совместимость не подтверждена.

`pip check` в обоих venv: **No broken requirements found**.

Версии в чистом venv: numpy 2.4.6, pandas 3.1.1, MetPy 1.7.1, pint 0.25.3, scipy 1.17.1 (транзитивно через MetPy после удаления прямой зависимости), python-telegram-bot 22.x, fastapi, uvicorn, google-genai, openai.

## ОС

| Проверка | Windows (dev) | Linux (прод) |
|---|---|---|
| `sys.platform` / event loop | `win32` / `WindowsProactorEventLoopPolicy` | нет Linux-окружения — **не проверено** |
| Matplotlib backend | по умолчанию `tkagg`; после импорта `render.skewt_builder` / `render.chart_builder` → `Agg` (принудительно `matplotlib.use("Agg")`) | ожидается Agg, но **не проверено**; GUI-бэкенд в коде не встречается |
| Namespace packages | импорт из `__main__` и из другого cwd через `PYTHONPATH=C:\StormLab` — OK (`bot`, `api`, `core.*`, `clients.*`, `render.*`) | **не проверено** |
| SQLite путь | `data/alerts.db` через `pathlib`; `git status` confirms `data/` игнорируется | **не проверено** |
| Кодировка логов | `RotatingFileHandler(..., encoding="utf-8")`, 5 МБ × 3 бэкапа | **не проверено**; cp1251-ловушки в коде не найдены |
| `RESTART_DELAY_SECONDS` / fast-fail | статически присутствует в точке входа; живой краш/рестарт — **OPERATOR** | **не проверено** |
| Порт 8000 занят | `uvicorn` пишет явный `[Errno 10048] error while attempting to bind on address`, выход с кодом 3 — тихого краша нет | **не проверено** |

## Удалённые зависимости (batch D) — контрольный выстрел

| Пакет | Проверка | Результат |
|---|---|---|
| `colorlog` | grep по всем `.py`: 0 вхождений; `stormlab/logging_config.py` использует stdlib `logging.Formatter` + `RotatingFileHandler`; `import bot, api` стартует | **PASS** |
| `groq` | grep: 0 `import groq`; провайдер использует OpenAI-совместимый клиент с `base_url=https://api.groq.com/openai/v1` (`stormlab/ai/ai_providers.py:320`). Проверка с реальным ключом — OPERATOR | **STATIC PASS / LIVE=PENDING** |
| `Cartopy` | grep: 0 `import cartopy`, даже в try/except | **PASS** |
| `scipy` | прямого импорта нет; в чистом venv установлен транзитивно: scipy 1.17.1, совместим с numpy 2.4.6 / MetPy 1.7.1 / pint 0.25.3; `pip check` чистый | **PASS** |

## Итог матрицы

- Полностью подтверждено: Python 3.11 + Windows + чистый venv + pytest + импорты + pip check.
- Не подтверждено из-за отсутствия окружения: Python 3.12/3.13, Linux, живой рестарт/сигналы, живой Groq-провайдер.
- Зафиксированный риск: если прод работает на 3.12/3.13 или Linux, совместимость **не верифицирована** — только статические пруфы.
