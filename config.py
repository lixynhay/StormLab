import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не найден. Создай файл .env на основе .env.example "
        "и укажи токен бота."
    )

DEFAULT_CITY = "Екатеринбург"
DEFAULT_LAT = 56.8333
DEFAULT_LON = 60.5833

SOUNDING_STATION_ID = "28440"
SOUNDING_STATION_NAME = "Екатеринбург (Кольцово)"

API_TIMEOUT = 10
API_RETRY_ATTEMPTS = 3
API_RETRY_DELAY = 2

RESTART_DELAY_SECONDS = 5

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_API_TIMEOUT = 30
GEMINI_RETRY_ATTEMPTS = 2
GEMINI_RETRY_DELAY = 3

if not GEMINI_API_KEY:
    import logging
    logging.getLogger(__name__).warning(
        "GEMINI_API_KEY не задан — команда /ai будет недоступна."
    )

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

LOG_FILE = "bot.log"
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 МБ
LOG_BACKUP_COUNT = 3

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

RADAR_COOLDOWN = 300

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

ADMIN_USER_IDS = [int(uid.strip()) for uid in os.getenv("ADMIN_USER_IDS", "").split(",") if uid.strip()]