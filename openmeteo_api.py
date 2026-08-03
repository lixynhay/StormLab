import logging
import time
from datetime import datetime

import requests

from config import API_RETRY_ATTEMPTS, API_RETRY_DELAY, API_TIMEOUT, DEFAULT_LAT, DEFAULT_LON

logger = logging.getLogger(__name__)



class CircuitBreaker:
    """Circuit Breaker: если API упал 3 раза, не дёргать 5 минут."""
    def __init__(self, failure_threshold=3, reset_timeout=300):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.last_failure_time = 0
        self.is_open = False
    
    def call(self, func, *args, **kwargs):
        if self.is_open:
            if time.time() - self.last_failure_time < self.reset_timeout:
                raise Exception("Circuit breaker OPEN — API temporarily disabled")
            else:
                self.is_open = False
                self.failure_count = 0
        
        try:
            result = func(*args, **kwargs)
            self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.is_open = True
                logger.warning(f"Circuit breaker OPEN after {self.failure_count} failures")
            raise

class OpenMeteoAPI:
    def __init__(self):
        self.base_url = "https://api.open-meteo.com/v1/forecast"
        self.lat = DEFAULT_LAT
        self.lon = DEFAULT_LON
        self._cache = {}
        self._cache_timestamps = {}

        self._cache_ttl = {
            "current": 300,
            "forecast": 1800,
            "pressure_levels": 1800,
            "precipitation_nowcast": 300,
        }
        self._max_cache_size = 50

    def _cleanup_cache(self):
        now = datetime.now()
        expired_keys = []

        for key, timestamp in list(self._cache_timestamps.items()):
            cache_type = key.split("_")[0] if "_" in key else "current"
            ttl = self._cache_ttl.get(cache_type, 300)

            if (now - timestamp).total_seconds() >= ttl:
                expired_keys.append(key)

        for key in expired_keys:
            del self._cache[key]
            del self._cache_timestamps[key]
            logger.debug(f"Cache expired: {key}")

        if len(self._cache) > self._max_cache_size:
            oldest_keys = sorted(
                self._cache_timestamps.keys(), key=lambda k: self._cache_timestamps[k]
            )[:5]
            for key in oldest_keys:
                del self._cache[key]
                del self._cache_timestamps[key]

    def _make_request(self, params, cache_key=None, lat=None, lon=None):
        if lat is not None:
            params["latitude"] = lat
        if lon is not None:
            params["longitude"] = lon

        if cache_key:
            full_key = f"{cache_key}_{params.get('latitude', '')}_{params.get('longitude', '')}"
            if full_key in self._cache:
                cache_type = cache_key.split("_")[0] if "_" in cache_key else "current"
                ttl = self._cache_ttl.get(cache_type, 300)
                age = (
                    datetime.now() - self._cache_timestamps.get(full_key, datetime.min)
                ).total_seconds()

                if age < ttl:
                    logger.debug(f"Cache HIT: {full_key} (age: {age:.0f}s, TTL: {ttl}s)")
                    return self._cache[full_key]
                else:
                    logger.debug(f"Cache EXPIRED: {full_key} (age: {age:.0f}s, TTL: {ttl}s)")
        else:
            full_key = None

        last_error = None
        for attempt in range(API_RETRY_ATTEMPTS):
            try:
                logger.info(f"API request to Open-Meteo (attempt {attempt + 1})")
                response = requests.get(
                    self.base_url, params=params, timeout=(API_TIMEOUT, API_TIMEOUT * 2)
                )

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 5))
                    logger.warning(f"Rate limited, waiting {retry_after}s")
                    time.sleep(retry_after)
                    continue

                if response.status_code >= 500:
                    logger.warning(f"Server error {response.status_code}, retrying...")
                    if attempt < API_RETRY_ATTEMPTS - 1:
                        time.sleep(API_RETRY_DELAY * (attempt + 1))
                        continue

                response.raise_for_status()
                data = response.json()

                if "hourly" not in data and "current" not in data:
                    raise ValueError("Invalid response: missing hourly/current data")

                if full_key:
                    self._cache[full_key] = data
                    self._cache_timestamps[full_key] = datetime.now()
                    self._cleanup_cache()
                    logger.info(f"Data cached: {full_key}")

                return data

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

    def get_forecast(self, days=2, lat=None, lon=None):
        params = {
            "hourly": (
                "temperature_2m,relative_humidity_2m,dew_point_2m,"
                "apparent_temperature,precipitation,weather_code,"
                "cloud_cover,wind_speed_10m,wind_direction_10m,"
                "surface_pressure,visibility,uv_index"
            ),
            "current": (
                "temperature_2m,relative_humidity_2m,dew_point_2m,"
                "apparent_temperature,precipitation,weather_code,"
                "cloud_cover,wind_speed_10m,wind_direction_10m,"
                "surface_pressure,visibility,uv_index"
            ),
            "temperature_unit": "celsius",
            "wind_speed_unit": "ms",
            "pressure_unit": "hPa",
            "timezone": "UTC",
            "forecast_days": days,
        }

        cache_key = f"forecast_{days}"
        return self._make_request(params, cache_key, lat, lon)

    def get_current(self, lat: float, lon: float) -> dict:
        """Возвращает {'current': {...}} с добавленными индексами CAPE и LI"""
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,dew_point_2m,apparent_temperature,"
                       "precipitation,weather_code,cloud_cover,surface_pressure,"
                       "wind_speed_10m,wind_direction_10m,cape,lifted_index", # <-- ДОБАВИЛИ CAPE И LI
            "timezone": "UTC"
        }

        cache_key = "current"
        return self._make_request(params, cache_key, lat, lon)

    def get_pressure_levels(self, lat=None, lon=None):
        params = {
            "hourly": [
                "temperature_1000hPa", "temperature_925hPa", "temperature_850hPa",
                "temperature_700hPa", "temperature_500hPa", "temperature_300hPa",
                "dew_point_1000hPa", "dew_point_925hPa", "dew_point_850hPa",
                "dew_point_700hPa", "dew_point_500hPa", "dew_point_300hPa",
                "wind_speed_1000hPa", "wind_speed_925hPa", "wind_speed_850hPa",
                "wind_speed_700hPa", "wind_speed_500hPa",
                "wind_direction_1000hPa", "wind_direction_925hPa",
                "wind_direction_850hPa", "wind_direction_700hPa", "wind_direction_500hPa",
                "surface_pressure",
            ],
            "temperature_unit": "celsius",
            "wind_speed_unit": "ms",
            "timezone": "UTC",
            "forecast_days": 1,
        }

        cache_key = "pressure_levels"
        return self._make_request(params, cache_key, lat, lon)

    def get_precipitation_nowcast(self, lat=None, lon=None):
        params = {
            "hourly": "precipitation",
            "current": "precipitation",
            "timezone": "UTC",
            "forecast_days": 1,
        }

        cache_key = "precipitation_nowcast"
        return self._make_request(params, cache_key, lat, lon)

    def clear_cache(self):
        self._cache.clear()
        self._cache_timestamps.clear()
        logger.info("Cache cleared")

    def get_cache_age_seconds(self, cache_key: str, lat=None, lon=None) -> float | None:
        """
        Сколько секунд назад данные были реально получены от API (а не из кэша).
        Возвращает None, если для этого ключа/координат ещё ничего не кэшировано
        (например, самый первый запрос в процессе).
        """
        full_key = f"{cache_key}_{lat if lat is not None else ''}_{lon if lon is not None else ''}"
        timestamp = self._cache_timestamps.get(full_key)
        if timestamp is None:
            return None
        return (datetime.now() - timestamp).total_seconds()