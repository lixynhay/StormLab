import logging
import httpx
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

RAVIEWER_API_URL = "https://api.rainviewer.com/public/weather-maps.json"
TILE_BASE_URL = "https://tilecache.rainviewer.com"

# Кэш состояния API (чтобы не дёргать его каждый раз)
_cache = {
    "last_check": 0,
    "is_valid": False,
    "last_valid_path": None,
    "last_valid_time": None,
    "ttl": 300  # 5 минут
}

def get_latest_radar_frame(force_check=False):
    """
    Запрашивает у RainViewer список снимков и возвращает путь к последнему ВАЛИДНОму.
    Кэширует результат на 5 минут, чтобы не спамить API.
    Возвращает (path, timestamp_utc, is_cached)
    """
    now = time.time()
    
    # Если кэш ещё валиден и не принудительная проверка — возвращаем кэш
    if not force_check and (now - _cache["last_check"]) < _cache["ttl"]:
        if _cache["is_valid"]:
            logger.info(f"RainViewer: используем кэш ({_cache['last_valid_path']})")
            return _cache["last_valid_path"], _cache["last_valid_time"], True
        else:
            logger.info("RainViewer: кэш показывает недоступность")
            return None, None, True
    
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(RAVIEWER_API_URL)
            response.raise_for_status()
            data = response.json()

        past_frames = data.get("radar", {}).get("past", [])
        if not past_frames:
            logger.error("RainViewer: список past пуст")
            _cache["is_valid"] = False
            _cache["last_check"] = now
            return None, None, False

        # Ищем первый валидный путь (с минимум 4 слэшами)
        for frame in reversed(past_frames):
            path = frame.get("path", "")
            if path.count('/') >= 4:
                timestamp_unix = frame["time"]
                dt_utc = datetime.fromtimestamp(timestamp_unix, tz=timezone.utc)
                
                # Обновляем кэш
                _cache["is_valid"] = True
                _cache["last_valid_path"] = path
                _cache["last_valid_time"] = dt_utc
                _cache["last_check"] = now
                
                logger.info(f"RainViewer: найден валидный фрейм {path}")
                return path, dt_utc, False
        
        # Все пути — мусор
        logger.warning("RainViewer: API временно отдает только заглушки")
        _cache["is_valid"] = False
        _cache["last_check"] = now
        return None, None, False

    except Exception as e:
        logger.error(f"Ошибка RainViewer API: {e}", exc_info=True)
        _cache["is_valid"] = False
        _cache["last_check"] = now
        return None, None, False

def is_radar_available():
    """Быстрая проверка без запроса к API (использует кэш)."""
    now = time.time()
    if (now - _cache["last_check"]) >= _cache["ttl"]:
        # Кэш устарел, делаем быструю проверку
        get_latest_radar_frame()
    return _cache["is_valid"]
