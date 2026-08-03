# 🌩 StormLab — Telegram-бот для анализа грозовой обстановки

Профессиональный метеорологический бот для анализа конвективной неустойчивости атмосферы, построения аэрологических диаграмм и прогнозирования опасных явлений. Проект находится в **production-ready** состоянии с полным покрытием unit-тестами.

---

## 🚀 Возможности

### Основные команды
| Команда | Описание |
| --- | --- |
| `/start` | Начать работу с ботом |
| `/storm [город]` | Грозовые индексы + вертикальный профиль атмосферы |
| `/skewt [город]` | Skew-T Log-P диаграмма + выбор реального зонда |
| `/radar [город]` | Радар осадков (RainViewer API) |
| `/ai [город]` | AI-анализ грозовой обстановки (Gemini/Groq/GitHub Models с fallback) |
| `/alert [город]` | Подписка на уведомления об опасной погоде |
| `/unalert [город]` | Отписка от уведомлений |
| `/alerts` | Список активных подписок |
| `/help` | Справка по командам |

### Рассчитываемые индексы (по стандартам SPC)
**Термодинамика:**
- **CAPE** (SB/ML/MU) — Convective Available Potential Energy
- **CIN** — Convective Inhibition (крышка)
- **LCL** — Lifted Condensation Level

**Индексы устойчивости:**
- K-Index, Total Totals, **Lifted Index** (точный расчёт через MetPy)
- Showalter Index, SWEAT Index, Mid-layer spread

**Динамика (важно для суперячеек):**
- Bulk Wind Shear 0-6 км и 0-3 км
- Storm Relative Helicity (SRH) с расчётом Bunkers Storm Motion

**Композитные индексы (шторм-чейзинг):**
- **STP** (Significant Tornado Parameter) — риск торнадо (использует MLCAPE)
- **SCP** (Supercell Composite) — потенциал суперячеек (использует MUCAPE)
- **DCAPE** (Downdraft CAPE) — риск микропорывов/шквалов (с санкчеком артефактов >1500 Дж/кг)
- EHI (Energy-Helicity Index), BRN (Bulk Richardson Number)
- MCS Maintenance — устойчивость линий шквалов

**Уровень угрозы:** Визуальная шкала 0-5 с учётом всех параметров.

### Система алертов
Бот каждые 30 минут проверяет условия для всех подписанных городов и отправляет уведомления при:
- STP ≥ 1.0 (риск торнадо)
- SCP ≥ 4.0 (суперячейки)
- DCAPE ≥ 1000 Дж/кг (шквалы)
- CAPE ≥ 2500 Дж/кг + сильный сдвиг

---

## 🛠 Технологический стек

- **Язык**: Python 3.14 + `asyncio`
- **Framework**: `python-telegram-bot` (v21+)
- **Метеорология**: `MetPy`, `NumPy`, `SciPy`, `Siphon` (Wyoming/IGRA2)
- **Визуализация**: `Matplotlib`, `Pillow`
- **Хранение**: `SQLite` (асинхронный, без блокировки Event Loop)
- **API**: Open-Meteo (основной), OpenWeatherMap (fallback), RainViewer
- **AI**: Gemini, Groq, GitHub Models (с умной цепочкой fallback и `retry_with_backoff`

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

### 4. Настройка окружения
Создай файл `.env` на основе `.env.example`:
```bash
cp .env.example .env
nano .env
```
Заполни переменные:
```env
BOT_TOKEN=твой_токен_от_BotFather
OPENWEATHERMAP_API_KEY=твой_ключ_от_OWM (опционально)
GEMINI_API_KEY=твой_ключ_от_Google_AI
GROQ_API_KEY=твой_ключ_от_Groq
GITHUB_TOKEN=твой_токен_от_GitHub
```

### 5. Запуск бота
**Для разработки:**
```bash
python bot.py`
```

## 📂 Структура проекта

```text
StormLab/
 ├── bot.py                    # Точка входа, инициализация Application
 ├── config.py                 # Централизованная конфигурация
 ├── ai_analysis.py            # AI-анализ с fallback цепочкой
 ├── ai_providers.py           # Gemini/Groq/GitHub/Local провайдеры
 ├── ai_coder.py               # 🔧 Локальный AI-агент для рефакторинга кода
 ├── core/
 │   ├── storm_indices.py      # Расчёт всех метеорологических индексов (SPC standards)
 │   ├── data_fusion.py        # Слияние данных из разных источников
 │   ├── skewt_builder.py      # Построение Skew-T диаграмм
 │   └── chart_builder.py      # Построение вертикальных профилей
 ├── api/
 │   ├── openmeteo_api.py      # API Open-Meteo (модельные данные)
 │   ├── openweathermap_api.py # API OpenWeatherMap (текущая погода)
 │   ├── radar_api.py          # RainViewer API (радар)
 │   ├── sounding_api.py       # Зондирование (реальные станции Wyoming/IGRA2)
 │   └── geocoding.py          # Геокодирование городов
 ├── handlers/                 # Обработчики команд Telegram
 ├── utils/
 │   ├── alert_manager.py      # Асинхронное управление подписками (SQLite)
 │   ├── metrics.py            # Асинхронная метрика команд
 │   ├── rate_limiter.py       # Ограничение частоты запросов
 │   └── retry.py              # Универсальный декоратор retry_with_backoff
 ├── data/                     # SQLite БД и кэш
 ├── requirements.txt          # Зависимости Python
 └── .env                      # Секреты (не коммитится!)
```

---

## 🎯 Примеры использования

**Грозовые индексы:**
`/storm Москва`
> Бот покажет CAPE, CIN, K-Index, STP, SCP и визуальную шкалу уровня угрозы.

**Skew-T диаграмма:**
`/skewt Сочи`
> Бот построит аэрологическую диаграмму и предложит выбрать реальный зонд из ближайших станций.

**AI-анализ:**
`/ai Казань`
> Бот отправит все индексы и Skew-T контекст в AI, который даст развёрнутый анализ на естественном языке.

---

## 🔧 Особенности архитектуры

1. **Неблокирующий Event Loop**: Все операции с SQLite и внешними API обернуты в `asyncio.to_thread`, что гарантирует мгновенный отклик бота даже под нагрузкой.
2. **Защита от артефактов**: Реализован санкчек для DCAPE (игнорирует значения >1500 Дж/кг на разреженной сетке Open-Meteo).
3. **Умный fallback**: Если ML/MU CAPE не могут быть рассчитаны из-за ограничения в 6 уровней давления Open-Meteo, система автоматически и безопасно переходит на SBCAPE.
4. **Лимиты Telegram**: Callback-данные оптимизированы (макс. 64 байта) за счет хранения контекста в `user_data`.

---

## 🐛 Известные ограничения

- Высоты рассчитываются из стандартной атмосферы, а не из реальных данных (ограничение модельных API).
- Радар RainViewer иногда недоступен во время глобальных обновлений их серверов.
- AI-анализ зависит от доступности и квот внешних API (автоматически переключается на fallback-провайдеров).
- **Дисклеймер**: Расчёт по доступному модельному профилю. Не заменяет официальный прогноз метеослужб.

---

## 🤝 Вклад в проект

Pull requests приветствуются! Для крупных изменений сначала откройте issue для обсуждения.

---

## 💡 Поддержка

Если бот полезен, вы можете поддержать оплату серверов:
- **TON**: `UQC-plwq4_uIPlVxTSba2IAm3L805D6iWxdMCMaVXeqwz5CZ`
- **Boosty**: [Поддержать проект](https://boosty.to/lixynyt167/purchase/1865325)
