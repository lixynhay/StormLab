import logging
import requests
from config import API_TIMEOUT

logger = logging.getLogger(__name__)

_GEO_CACHE = {}
_GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"


def resolve_city(query: str):
    if not query:
        return None

    key = query.strip().lower()
    if key in _GEO_CACHE:
        logger.debug(f"Geo cache HIT: {key}")
        return _GEO_CACHE[key]

    try:
        resp = requests.get(
            _GEO_URL,
            params={"name": query.strip(), "count": 1, "language": "ru", "format": "json"},
            timeout=API_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
        if not results:
            logger.warning(f"Город не найден: {query}")
            return None

        r = results[0]
        lat, lon = float(r["latitude"]), float(r["longitude"])
        name = r.get("name", query)
        admin1 = r.get("admin1")
        country = r.get("country")

        parts = [name]
        if admin1 and admin1.lower() != name.lower():
            parts.append(admin1)
        if country:
            parts.append(country)
        display_name = ", ".join(parts)

        result = (lat, lon, display_name)
        _GEO_CACHE[key] = result
        logger.info(f"Geo resolved: {query} -> {display_name} ({lat}, {lon})")
        return result

    except Exception as e:
        logger.error(f"Geocoding error for '{query}': {e}")
        return None
