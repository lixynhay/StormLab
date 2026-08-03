"""
Единая точка настройки логирования для всего проекта.
Вызывается один раз при старте (в bot.py), остальные модули просто
делают logging.getLogger(__name__) и наследуют настройку.
"""

import logging
from logging.handlers import RotatingFileHandler

from config import LOG_BACKUP_COUNT, LOG_FILE, LOG_MAX_BYTES


def setup_logging() -> None:
    root_logger = logging.getLogger()
    if root_logger.handlers:
        # Уже настроено (например, повторный вызов при auto-restart) — не дублируем хендлеры
        return

    root_logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Приглушаем избыточные логи сторонних библиотек
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)