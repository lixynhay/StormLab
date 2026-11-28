import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
# BOT_TOKEN обязателен только для bot.py; REST API (api.py) работает без него.
# Проверка перенесена в bot.main(), чтобы импорт config не падал в API-режиме.

# Ключ доступа к REST API (защита эндпоинтов). Если не задан — API закрыт (401).
API_ACCESS_KEY = os.getenv("API_ACCESS_KEY")
API_HOST = os.getenv("API_HOST", "127.0.0.1")

DEFAULT_LAT = 56.8333
DEFAULT_LON = 60.5833

API_TIMEOUT = 10
API_RETRY_ATTEMPTS = 3
API_RETRY_DELAY = 2

# Явные таймауты для внешних сервисов, которые не должны вешать event loop/воркеры.
WYOMING_TIMEOUT = 20          # один запрос к Wyoming/IGRA2 (siphon)
SOUNDING_PROBE_TIMEOUT = 75   # весь probe_stations: 3 срока × 20 с + запас
LLM_REQUEST_TIMEOUT = 20      # один вызов LLM-провайдера
AI_ANALYSIS_TIMEOUT = 60      # вся цепочка AI-провайдеров
IO_TIMEOUT = 45               # прочие to_thread-вызовы (геокод, данные, радар)

RESTART_DELAY_SECONDS = 5

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_API_TIMEOUT = 30

# Лимит подписок на пользователя (уникальные координаты, округлённые до 0.01°).
MAX_ALERTS_PER_USER = int(os.getenv("MAX_ALERTS_PER_USER", "5"))

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


GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

def _parse_admin_user_ids(value):
    admin_ids = []
    for uid in value.split(","):
        uid = uid.strip()
        if not uid:
            continue
        try:
            admin_ids.append(int(uid))
        except ValueError:
            continue
    return admin_ids


ADMIN_USER_IDS = _parse_admin_user_ids(os.getenv("ADMIN_USER_IDS", ""))