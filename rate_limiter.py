"""
Глобальный rate limiter с admin whitelist.
"""
import logging
import time
from config import ADMIN_USER_IDS

logger = logging.getLogger(__name__)

# cooldowns в секундах для разных операций
COOLDOWNS = {
    "storm": 30,      # 30 секунд между запросами индексов
    "skewt": 60,      # 1 минута для Skew-T
    "ai": 60,         # 1 минута для AI-анализа
    "radar": 300,     # 5 минут для радара (уже реализовано отдельно)
}

_rate_limits = {}  # {(user_id, operation): last_request_time}

def check_rate_limit(user_id: int, operation: str) -> tuple[bool, int]:
    """
    Проверяет, может ли пользователь выполнить операцию.
    Возвращает (allowed: bool, remaining_seconds: int)
    
    Admin пользователи (из ADMIN_USER_IDS) обходят все лимиты.
    """
    # Admin bypass
    if user_id in ADMIN_USER_IDS:
        logger.debug(f"Admin {user_id} bypasses rate limit for {operation}")
        return True, 0
    
    cooldown = COOLDOWNS.get(operation, 60)  # дефолт 60 сек
    key = (user_id, operation)
    now = time.time()
    
    last_request = _rate_limits.get(key, 0)
    elapsed = now - last_request
    
    if elapsed < cooldown:
        remaining = int(cooldown - elapsed)
        return False, remaining
    
    # Обновляем timestamp
    _rate_limits[key] = now
    
    # Периодическая очистка (раз в 500 запросов)
    if len(_rate_limits) > 500:
        _prune_rate_limits()
    
    return True, 0

def _prune_rate_limits():
    """Удаляет устаревшие записи."""
    now = time.time()
    expired = [
        key for key, ts in _rate_limits.items()
        if (now - ts) > max(COOLDOWNS.values())
    ]
    for key in expired:
        del _rate_limits[key]
    logger.debug(f"Rate limiter pruned: removed {len(expired)} entries")
