import logging
import time
from config import ADMIN_USER_IDS

logger = logging.getLogger(__name__)

COOLDOWNS = {
    "storm": 30,
    "skewt": 60,
    "ai": 60,
    "radar": 300,
}

_rate_limits = {}

def check_rate_limit(user_id: int, operation: str) -> tuple[bool, int]:
    # Admin bypass
    if user_id in ADMIN_USER_IDS:
        logger.debug(f"Admin {user_id} bypasses rate limit for {operation}")
        return True, 0
    
    cooldown = COOLDOWNS.get(operation, 60)
    key = (user_id, operation)
    now = time.time()
    
    last_request = _rate_limits.get(key, 0)
    elapsed = now - last_request
    
    if elapsed < cooldown:
        remaining = int(cooldown - elapsed)
        return False, remaining
    
    _rate_limits[key] = now
    
    if len(_rate_limits) > 500:
        _prune_rate_limits()
    
    return True, 0

def _prune_rate_limits():
    now = time.time()
    expired = [
        key for key, ts in _rate_limits.items()
        if (now - ts) > max(COOLDOWNS.values())
    ]
    for key in expired:
        del _rate_limits[key]
    logger.debug(f"Rate limiter pruned: removed {len(expired)} entries")