import logging
import os
import sqlite3
import subprocess
from stormlab.paths import PROJECT_ROOT
from logging.handlers import RotatingFileHandler
from pathlib import Path


class _OptionalKeyNoticeFilter(logging.Filter):
    # Optional-provider status belongs in the startup banner, not as warnings.
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not message.startswith((
            "GEMINI_API_KEY не задан",
            "OPENWEATHERMAP_API_KEY не задан",
        ))


def _configure_noisy_loggers() -> None:
    # Keep scheduler chatter out of INFO and route Uvicorn through the root formatter.
    for name in ("apscheduler", "apscheduler.scheduler", "apscheduler.executors"):
        logging.getLogger(name).setLevel(logging.WARNING)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(logging.INFO if name == "uvicorn.access" else logging.WARNING)


def setup_logging() -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s,%(msecs)03d | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    notice_filter = _OptionalKeyNoticeFilter()

    # Install handlers before importing config, which logs optional key notices.
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)
        handler.addFilter(notice_filter)
    if not any(type(handler) is logging.StreamHandler for handler in root_logger.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.addFilter(notice_filter)
        root_logger.addHandler(console_handler)

    from stormlab.config import LOG_BACKUP_COUNT, LOG_FILE, LOG_MAX_BYTES

    log_dir = os.path.dirname(LOG_FILE)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    if not any(isinstance(handler, RotatingFileHandler) for handler in root_logger.handlers):
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(notice_filter)
        root_logger.addHandler(file_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    _configure_noisy_loggers()


def _subscription_count(db_path: Path) -> int:
    if not db_path.is_file():
        return 0
    try:
        connection = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
        try:
            return int(connection.execute("SELECT COUNT(*) FROM alerts").fetchone()[0])
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return 0


def _repository_version() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=1,
        )
        return result.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


