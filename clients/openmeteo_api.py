import bisect
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import requests

from config import API_RETRY_ATTEMPTS, API_RETRY_DELAY, API_TIMEOUT, DEFAULT_LAT, DEFAULT_LON
from core.locks import get_lock
from core.storm_indices import SKEWT_LEVELS

logger = logging.getLogger(__name__)


def _as_utc(value) -> Optional[datetime]:
    """Parse an Open-Meteo hourly timestamp (naive ISO = UTC) into an aware datetime."""
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def current_hour_index(times, now: Optional[datetime] = None) -> int:
    """Index of the hourly slot covering ``now`` (UTC), not the midnight slot.

    Open-Meteo returns hourly arrays starting at 00:00 UTC, so index 0 is midnight;
    using it as "now" shifts every forecast button by the current hour of day.
    """
    if not times:
        return 0
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    parsed = [dt for dt in (_as_utc(t) for t in times) if dt is not None]
    if not parsed:
        return 0
    index = bisect.bisect_right(parsed, now) - 1
    return max(0, min(index, len(times) - 1))


def resolve_hour_index(times, offset_hours: int = 0, now: Optional[datetime] = None) -> int:
    """Base index for the current UTC hour plus a button offset (+3/+6/+12/+24)."""
    if not times:
        return 0
    base = current_hour_index(times, now)
    return max(0, min(base + max(0, int(offset_hours)), len(times) - 1))



class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, reset_timeout: int = 300):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.is_open = False

    def call(self, func, *args, **kwargs):
        if self.is_open:
            if time.time() - self.last_failure_time < self.reset_timeout:
                raise RuntimeError("Circuit breaker OPEN — API временно недоступен")
            else:
                self.is_open = False
                self.failure_count = 0
                logger.info("Circuit breaker CLOSED — восстановление работы API")

        try:
            result = func(*args, **kwargs)
            self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.is_open = True
                logger.warning(f"Circuit breaker OPEN после {self.failure_count} неудачных попыток")
            raise


class OpenMeteoAPI:
    def __init__(self):
        self.base_url = "https://api.open-meteo.com/v1/forecast"
        self.lat = DEFAULT_LAT
        self.lon = DEFAULT_LON

        # Circuit breaker: после 3 подряд неудачных запросов «открывается» на 5 минут,
        # чтобы не долбить API во время его деградации (защита от каскадных сбоев).
        self._breaker = CircuitBreaker(failure_threshold=3, reset_timeout=300)
        # Переиспользование TCP/TLS-соединений между запросами
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "StormLab-Weather-Bot/1.0 (+https://github.com/lixynhay/StormLab)"
        })

        self._cache: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
        self._max_cache_size = 50
        
        self._cache_ttl = {
            "current": 300,
            "forecast": 1800,
            "pressure_levels": 1800,
            "precipitation_nowcast": 300,
        }
        self._cache_lock = get_lock("openmeteo_api")

    def _cache_ttl_for(self, full_key: str) -> int:
        for name, ttl in self._cache_ttl.items():
            if full_key == name or full_key.startswith(name + "_"):
                return ttl
        return 300

    def _cleanup_cache(self):
        now = datetime.now()
        expired_keys = [
            key for key, timestamp in self._cache_timestamps.items()
            if (now - timestamp).total_seconds() >= self._cache_ttl_for(key)
        ]

        for key in expired_keys:
            # pop(..., None) is safe if a concurrent to_thread call already
            # evicted the key: a KeyError here used to bubble out of
            # _make_request and look like a spurious CircuitBreaker/API failure.
            self._cache.pop(key, None)
            self._cache_timestamps.pop(key, None)
            logger.debug(f"Cache expired: {key}")

        if len(self._cache) > self._max_cache_size:
            excess = len(self._cache) - self._max_cache_size
            sorted_keys = sorted(self._cache_timestamps.keys(), key=lambda k: self._cache_timestamps[k])
            for key in sorted_keys[:excess + 5]:
                self._cache.pop(key, None)
                self._cache_timestamps.pop(key, None)
            logger.info(f"Cache pruned: удалено {excess + 5} старых записей, текущий размер: {len(self._cache)}")

    def _make_request(self, params: Dict[str, Any], cache_key: Optional[str] = None, lat: Optional[float] = None, lon: Optional[float] = None) -> Dict[str, Any]:
        if lat is not None:
            params["latitude"] = lat
        if lon is not None:
            params["longitude"] = lon

        full_key = None
        if cache_key:
            full_key = f"{cache_key}_{params.get('latitude', '')}_{params.get('longitude', '')}"
            if full_key in self._cache:
                with self._cache_lock:
                    ttl = self._cache_ttl_for(full_key)
                    age = (datetime.now() - self._cache_timestamps.get(full_key, datetime.min)).total_seconds()

                    if age < ttl:
                        logger.debug(f"Cache HIT: {full_key} (age: {age:.0f}s, TTL: {ttl}s)")
                        return self._cache[full_key]
                    logger.debug(f"Cache EXPIRED: {full_key} (age: {age:.0f}s, TTL: {ttl}s)")

        last_error = None
        for attempt in range(API_RETRY_ATTEMPTS):
            try:
                logger.info(f"API request to Open-Meteo (attempt {attempt + 1})")
                response = self._breaker.call(
                    lambda: self._session.get(
                        self.base_url, params=params, timeout=(API_TIMEOUT, API_TIMEOUT * 2)
                    )
                )

                if response.status_code == 429:
                    retry_after = min(int(response.headers.get("Retry-After", 5)), 30)
                    logger.warning(f"Rate limited, ожидание {retry_after}s")
                    time.sleep(retry_after)
                    continue

                if response.status_code >= 500:
                    logger.warning(f"Server error {response.status_code}, повторная попытка...")
                    if attempt < API_RETRY_ATTEMPTS - 1:
                        time.sleep(API_RETRY_DELAY * (attempt + 1))
                        continue

                response.raise_for_status()
                data = response.json()

                if "hourly" not in data and "current" not in data:
                    raise ValueError("Invalid response: missing hourly/current data")

                if full_key:
                    with self._cache_lock:
                        self._cache[full_key] = data
                        self._cache_timestamps[full_key] = datetime.now()
                        self._cleanup_cache()
                    logger.info(f"Data cached: {full_key}")

                return data

            except RuntimeError as e:
                # Circuit breaker открыт — не долбим API, сразу отдаём ошибку наружу
                logger.error(f"Circuit breaker: {e}")
                raise
            except requests.exceptions.Timeout as e:
                last_error = e
                logger.warning(f"API timeout (attempt {attempt + 1}/{API_RETRY_ATTEMPTS})")
                if attempt < API_RETRY_ATTEMPTS - 1:
                    time.sleep(API_RETRY_DELAY * (attempt + 1))
            except requests.exceptions.RequestException as e:
                last_error = e
                logger.error(f"API error: {e}")
                if attempt < API_RETRY_ATTEMPTS - 1:
                    time.sleep(API_RETRY_DELAY * (attempt + 1))
            except ValueError as e:
                logger.error(f"Invalid API response: {e}")
                raise

        raise Exception(f"API request failed after {API_RETRY_ATTEMPTS} attempts: {last_error}")

    def get_forecast(self, days: int = 2, lat: Optional[float] = None, lon: Optional[float] = None) -> Dict[str, Any]:
        params = {
            "hourly": "temperature_2m,relative_humidity_2m,dew_point_2m,apparent_temperature,precipitation,weather_code,cloud_cover,wind_speed_10m,wind_direction_10m,surface_pressure,visibility,uv_index",
            "current": "temperature_2m,relative_humidity_2m,dew_point_2m,apparent_temperature,precipitation,weather_code,cloud_cover,surface_pressure,wind_speed_10m,wind_direction_10m",
            "temperature_unit": "celsius",
            "wind_speed_unit": "ms",
            "pressure_unit": "hPa",
            "timezone": "UTC",
            "forecast_days": max(int(days), 2),
        }
        return self._make_request(params, cache_key=f"forecast_{days}", lat=lat, lon=lon)

    def get_current(self, lat: float, lon: float) -> Dict[str, Any]:
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,dew_point_2m,apparent_temperature,precipitation,weather_code,cloud_cover,surface_pressure,wind_speed_10m,wind_direction_10m",
            "wind_speed_unit": "ms",
            "timezone": "UTC"
        }
        return self._make_request(params, cache_key="current", lat=lat, lon=lon)

    def get_pressure_levels(self, lat: Optional[float] = None, lon: Optional[float] = None) -> Dict[str, Any]:
        # Surface variables are part of the hourly payload so forecast buttons
        # (time_index > 0) still have a valid surface parcel; otherwise the
        # surface point disappears and 1000 hPa leaks below ground.
        hourly_vars = [
            "surface_pressure",
            "temperature_2m",
            "dew_point_2m",
            "wind_speed_10m",
            "wind_direction_10m",
        ]
        for lvl in SKEWT_LEVELS:
            hourly_vars.extend([
                f"temperature_{lvl}hPa",
                f"dew_point_{lvl}hPa",
                f"wind_speed_{lvl}hPa",
                f"wind_direction_{lvl}hPa"
            ])

        params = {
            "hourly": ",".join(hourly_vars),
            "temperature_unit": "celsius",
            "wind_speed_unit": "ms",
            "timezone": "UTC",
            # 2 days are required: "now" may be 23 UTC, and +24h then lands on
            # tomorrow's last hourly slot.
            "forecast_days": 2,
        }
        return self._make_request(params, cache_key="pressure_levels", lat=lat, lon=lon)

    def get_precipitation_nowcast(self, lat: Optional[float] = None, lon: Optional[float] = None) -> Dict[str, Any]:
        params = {
            "hourly": "precipitation",
            "current": "precipitation",
            "timezone": "UTC",
            "forecast_days": 1,
        }
        return self._make_request(params, cache_key="precipitation_nowcast", lat=lat, lon=lon)

    def clear_cache(self):
        with self._cache_lock:
            self._cache.clear()
            self._cache_timestamps.clear()
        logger.info("Cache cleared")