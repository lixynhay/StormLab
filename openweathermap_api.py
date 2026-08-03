import logging
import time

import requests

from config import (
    OPENWEATHERMAP_API_KEY,
    OWM_API_TIMEOUT,
    OWM_RETRY_ATTEMPTS,
    OWM_RETRY_DELAY,
)

logger = logging.getLogger(__name__)


class OpenWeatherMapAPI:
    def __init__(self):
        self.base_url = "https://api.openweathermap.org/data/2.5/weather"

    def get_current(self, lat: float, lon: float) -> dict | None:
        """
        Возвращает словарь с полями в тех же именах/единицах, что и
        OpenMeteoAPI.get_current()['current'], чтобы слияние в data_fusion.py
        было прямым сопоставлением ключ-в-ключ. Возвращает None при любой
        проблеме (нет ключа, сеть недоступна, попытки исчерпаны и т.п.) —
        это НЕ исключение, вызывающий код просто продолжает работать без OWM.
        """
        if not OPENWEATHERMAP_API_KEY:
            logger.debug("OPENWEATHERMAP_API_KEY не настроен, пропускаю запрос к OWM")
            return None

        params = {
            "lat": lat,
            "lon": lon,
            "appid": OPENWEATHERMAP_API_KEY,
            "units": "metric",
        }

        last_error = None
        for attempt in range(1, OWM_RETRY_ATTEMPTS + 1):
            try:
                logger.info(f"OpenWeatherMap API request (attempt {attempt}/{OWM_RETRY_ATTEMPTS})")
                response = requests.get(self.base_url, params=params, timeout=OWM_API_TIMEOUT)

                if response.status_code == 429:
                    logger.warning("OpenWeatherMap: rate limited")
                    time.sleep(OWM_RETRY_DELAY)
                    continue

                if response.status_code == 401:
                    logger.error("OpenWeatherMap: неверный API-ключ (401)")
                    return None

                response.raise_for_status()
                data = response.json()

                main = data.get("main", {})
                wind = data.get("wind", {})
                clouds = data.get("clouds", {})

                return {
                    "temperature_2m": main.get("temp"),
                    "relative_humidity_2m": main.get("humidity"),
                    "surface_pressure": main.get("pressure"),
                    "wind_speed_10m": wind.get("speed"),
                    "wind_direction_10m": wind.get("deg"),
                    "cloud_cover": clouds.get("all"),
                }

            except requests.exceptions.Timeout as e:
                last_error = e
                logger.warning(f"OpenWeatherMap timeout (attempt {attempt}/{OWM_RETRY_ATTEMPTS})")
                if attempt < OWM_RETRY_ATTEMPTS:
                    time.sleep(OWM_RETRY_DELAY)

            except requests.exceptions.RequestException as e:
                last_error = e
                logger.error(f"OpenWeatherMap API error: {e}")
                if attempt < OWM_RETRY_ATTEMPTS:
                    time.sleep(OWM_RETRY_DELAY)

            except (ValueError, KeyError) as e:
                last_error = e
                logger.error(f"OpenWeatherMap: некорректный ответ: {e}")
                break

        logger.warning(
            f"OpenWeatherMap недоступен после {OWM_RETRY_ATTEMPTS} попыток: {last_error}. "
            f"Продолжаю работу только на Open-Meteo."
        )
        return None