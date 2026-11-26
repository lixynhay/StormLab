import logging
import os
import platform
import sqlite3
import subprocess
import sys
from importlib.util import find_spec
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

    from config import LOG_BACKUP_COUNT, LOG_FILE, LOG_MAX_BYTES

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
            cwd=Path(__file__).resolve().parent,
            check=True,
            capture_output=True,
            text=True,
            timeout=1,
        )
        return result.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def setup_banner(mode: str, host: str | None = None, port: int | None = None) -> None:
    # Emit startup facts as one structured INFO record; no prints or missing-key warnings.
    from config import (
        API_HOST,
        API_ACCESS_KEY,
        GEMINI_API_KEY,
        GROQ_API_KEY,
        GITHUB_TOKEN,
        OPENROUTER_API_KEY,
        OPENWEATHERMAP_API_KEY,
    )

    repository_root = Path(__file__).resolve().parent
    db_path = repository_root / "data" / "alerts.db"
    persistence_path = repository_root / "data" / "persistence.pkl"
    subscriptions = _subscription_count(db_path)
    database_size = db_path.stat().st_size if db_path.is_file() else 0
    persistence_size = persistence_path.stat().st_size if persistence_path.is_file() else 0

    providers = []
    if GEMINI_API_KEY:
        providers.append("Gemini")
    if GROQ_API_KEY:
        providers.append("Groq")
    if GITHUB_TOKEN:
        providers.append("GitHub")
    if OPENROUTER_API_KEY:
        providers.append("OpenRouter")
    providers.append("Local")
    ai_status = ", ".join(providers)
    if not any((GEMINI_API_KEY, GROQ_API_KEY, GITHUB_TOKEN, OPENROUTER_API_KEY)):
        ai_status += " (cloud providers disabled; local fallback active)"

    jobs = "none"
    if mode.upper() == "BOT":
        jobs = (
            "alerts_check every 30m"
            if find_spec("apscheduler") is not None
            else "alerts_check disabled (JobQueue extra unavailable)"
        )

    host = host or API_HOST
    service = f"listening={host}:{port}" if mode.upper() == "REST" and port else ""
    api_access = "API key configured" if API_ACCESS_KEY else "API key missing (protected routes return 401)"
    disabled = "OWM disabled (no OPENWEATHERMAP_API_KEY)" if not OPENWEATHERMAP_API_KEY else "OWM enabled"
    lines = [
        "╔══════════════════════════════════════════════════════════════╗",
        f"║ StormLab | MODE {mode.upper()}",
        f"║ Version: {_repository_version()} | Python: {platform.python_version()} | {platform.platform()}",
        f"║ Sources: Open-Meteo OK | RainViewer OK | {disabled}",
        f"║ AI providers: {ai_status}",
        f"║ Storage: {db_path.relative_to(repository_root)} ({database_size} B), subscriptions={subscriptions}; "
        f"{persistence_path.relative_to(repository_root)} ({persistence_size} B)",
        f"║ Jobs: {jobs} | {api_access}" + (f" | {service}" if service else ""),
        "╚══════════════════════════════════════════════════════════════╝",
    ]
    banner = "\n".join(lines)
    if sys.stdout.isatty():
        banner = f"\033[36m{banner}\033[0m"
    logging.getLogger("stormlab.startup").info("\n%s", banner)
