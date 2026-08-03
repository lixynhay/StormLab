"""
Централизованная конфигурация метеобота.
Все секреты — через .env, все "магические числа" — здесь, а не разбросаны по коду.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не найден. Создай файл .env на основе .env.example "
        "и укажи токен бота."
    )

# ---------------------------------------------------------------------------
# Локация (по умолчанию)
# ---------------------------------------------------------------------------
DEFAULT_CITY = "Карпинск"
DEFAULT_LAT = 59.7667
DEFAULT_LON = 60.0167

# Ближайшая станция радиозондирования (реальные измерения, не модель)
SOUNDING_STATION_ID = "28440"
SOUNDING_STATION_NAME = "Екатеринбург (Кольцово)"

# ---------------------------------------------------------------------------
# Open-Meteo API: таймауты и retry
# ---------------------------------------------------------------------------
API_TIMEOUT = 10  # секунд на попытку (connect timeout; read timeout = x2 в клиенте)
API_RETRY_ATTEMPTS = 3
API_RETRY_DELAY = 2  # базовая задержка (сек) для линейного/степенного backoff

# ---------------------------------------------------------------------------
# Устойчивость процесса бота
# ---------------------------------------------------------------------------
RESTART_DELAY_SECONDS = 5

# ---------------------------------------------------------------------------
# Gemini AI (анализ грозовых индексов, команда /ai)
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_TIMEOUT = 30  # LLM отвечает медленнее, чем погодный API
GEMINI_RETRY_ATTEMPTS = 2
GEMINI_RETRY_DELAY = 3

if not GEMINI_API_KEY:
    import logging
    logging.getLogger(__name__).warning(
        "GEMINI_API_KEY не задан — команда /ai будет недоступна."
    )

# ---------------------------------------------------------------------------
# OpenWeatherMap (слияние приземных данных с Open-Meteo для повышения точности)
# ---------------------------------------------------------------------------
OPENWEATHERMAP_API_KEY = os.getenv("OPENWEATHERMAP_API_KEY")
OWM_API_TIMEOUT = 10
OWM_RETRY_ATTEMPTS = 3
OWM_RETRY_DELAY = 2

if not OPENWEATHERMAP_API_KEY:
    import logging
    logging.getLogger(__name__).warning(
        "OPENWEATHERMAP_API_KEY не задан — слияние данных отключено, "
        "используется только Open-Meteo."
    )

# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------
LOG_FILE = "bot.log"
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 МБ
LOG_BACKUP_COUNT = 3

# ---------------------------------------------------------------------------
# Слияние Open-Meteo + OpenWeatherMap: inverse-variance weighting
# ---------------------------------------------------------------------------
FUSION_SIGMA = {
    "temperature_2m": {"openmeteo": 1.0, "openweathermap": 1.0},
    "apparent_temperature": {"openmeteo": 1.0, "openweathermap": 1.0},
    "relative_humidity_2m": {"openmeteo": 5.0, "openweathermap": 5.0},
    "dew_point_2m": {"openmeteo": 1.0, "openweathermap": 1.5},
    "surface_pressure": {"openmeteo": 1.0, "openweathermap": 1.0},
    "cloud_cover": {"openmeteo": 10.0, "openweathermap": 10.0},
    "precipitation": {"openmeteo": 0.5, "openweathermap": 0.5},
    "wind_speed_10m": {"openmeteo": 1.0, "openweathermap": 1.0},
}

FUSION_DIVERGENCE_WARN_THRESHOLD = {
    "temperature_2m": 5.0,  # °C
    "surface_pressure": 5.0,  # гПа
    "wind_speed_10m": 5.0,  # м/с
}

# ---------------------------------------------------------------------------
# Радар (Rate Limiting)
# ---------------------------------------------------------------------------
RADAR_COOLDOWN = 300  # 5 минут между запросами для одного пользователя

# ---------------------------------------------------------------------------
# Дополнительные AI-провайдеры (цепочка fallback в ai_providers.py)
# ---------------------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# GitHub Models
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# ---------------------------------------------------------------------------
# Rate Limiting: Admin whitelist (обходят все cooldown'ы)
# ---------------------------------------------------------------------------
# Твой Telegram user ID можно узнать через @userinfobot
ADMIN_USER_IDS = [int(uid.strip()) for uid in os.getenv("ADMIN_USER_IDS", "").split(",") if uid.strip()]
