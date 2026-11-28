import functools
import logging
import threading
import time
from stormlab.config import ADMIN_USER_IDS

logger = logging.getLogger(__name__)

COOLDOWNS = {
    "storm": 30,
    "skewt": 60,
    "ai": 60,
    "radar": 300,
    # Menu commands only open the time picker; they must not consume the
    # cooldown of the actual report, otherwise the first button click is blocked.
    "storm_menu": 5,
    "skewt_menu": 5,
    "alert": 10,
    "alerts": 10,
    "sounding": 30,
    "geocode": 10,
    "unalert": 10,
}

# Callback button -> operation. Anything absent (help, change_city, start) is free.
_CALLBACK_OPERATIONS = {
    "refresh": "storm",
    "storm": "storm_menu",
    "skewt": "skewt",
    "ai": "ai",
    "radar": "radar",
    "alerts": "alerts",
}

_rate_limits = {}
_lock = threading.RLock()
_calls_since_prune = 0
_PRUNE_EVERY = 1000


def operation_for_update(update, context) -> str | None:
    """Resolve the rate-limit operation for a command or an inline-button click."""
    query = getattr(update, "callback_query", None)
    if query is not None:
        data = getattr(query, "data", "") or ""
        if data.startswith("time:"):
            return (getattr(context, "user_data", None) or {}).get("pending_action", "storm")
        if data.startswith("stn:"):
            return "sounding"
        return _CALLBACK_OPERATIONS.get(data)

    message = getattr(update, "effective_message", None)
    text = (getattr(message, "text", "") or "").strip()
    if text.startswith("/"):
        return text[1:].split()[0].split("@")[0]
    return None


def check_rate_limit(user_id: int, operation: str) -> tuple[bool, int]:
    # Admin bypass
    if user_id in ADMIN_USER_IDS:
        logger.debug(f"Admin {user_id} bypasses rate limit for {operation}")
        return True, 0
    
    cooldown = COOLDOWNS.get(operation, 60)
    key = (user_id, operation)
    now = time.time()

    global _calls_since_prune
    with _lock:
        last_request = _rate_limits.get(key, 0)
        elapsed = now - last_request

        if elapsed < cooldown:
            remaining = int(cooldown - elapsed)
            _calls_since_prune += 1
            if _calls_since_prune >= _PRUNE_EVERY:
                _calls_since_prune = 0
                _prune_rate_limits()
            return False, remaining

        _rate_limits[key] = now
        _calls_since_prune += 1
        if _calls_since_prune >= _PRUNE_EVERY:
            _calls_since_prune = 0
            _prune_rate_limits()
        if len(_rate_limits) > 500:
            _prune_rate_limits()
        return True, 0


def rate_limited(operation: str | None = None, message: str | None = None):
    """Decorator for both CommandHandlers and CallbackQueryHandler branches.

    With no explicit ``operation`` it is derived from the command name or
    callback_data (``time:`` uses the pending storm/skewt action, ``stn:`` uses
    the sounding cooldown). This keeps limits on buttons such as Refresh,
    Skew-T, AI, Radar and station selection, not just on slash commands.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(update, context, *args, **kwargs):
            op = operation or operation_for_update(update, context)
            user = getattr(update, "effective_user", None)
            user_id = getattr(user, "id", None)
            if op and user_id is not None:
                allowed, remaining = check_rate_limit(user_id, op)
                if not allowed:
                    text = message or f"⏳ Слишком часто. Подожди {remaining} с."
                    query = getattr(update, "callback_query", None)
                    try:
                        if query is not None:
                            await query.answer(text, show_alert=True)
                        else:
                            await update.effective_message.reply_text(text)
                    except Exception:
                        logger.debug("rate-limit reply failed", exc_info=True)
                    return None
            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator


def _prune_rate_limits():
    now = time.time()
    expired = [
        key for key, ts in _rate_limits.items()
        if (now - ts) > max(COOLDOWNS.values())
    ]
    for key in expired:
        del _rate_limits[key]
    logger.debug(f"Rate limiter pruned: removed {len(expired)} entries")
