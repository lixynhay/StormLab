import logging
import re
import time
from datetime import datetime, timezone, timedelta
from math import radians, sin, cos, sqrt, atan2
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
from siphon.simplewebservice.wyoming import WyomingUpperAir

logger = logging.getLogger(__name__)

MAX_COMPARE_KM = 1500

_STATIONS_CACHE = {"ts": 0.0, "df": None, "ttl": 0.0}
_SOUNDING_CACHE = {}
_SOUNDING_TS = {}
_PROBE_CACHE = {}
_PROBE_TTL = 1800
_SOUNDING_TTL = 3600
_FALLBACK_STATIONS = [
    ("28440", "Екатеринбург", 56.75, 61.05),
    ("27612", "Долгопрудный", 55.93, 37.52),
]

# Siphon's IGRAUpperAir only downloads soundings by station id; it has no station
# catalog. The catalog lives in the IGRA2 station list text file.
_STATION_LIST_URL = "https://www.ncei.noaa.gov/pub/data/igra/igra2-station-list.txt"
_STATION_LIST_TIMEOUT = 30
_STATION_LINE_RE = re.compile(
    r"^(\S{11})\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(.+?)\s+"
    r"(\d{4})\s+(\d{4})\s+(\d+)\s*$"
)
_NET_WARN_INTERVAL = 300
_NET_WARN_TS = {}


def _haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def _is_network_error(exc):
    return isinstance(exc, (requests.exceptions.RequestException, OSError))


def _log_network_unavailable(phase, exc):
    """Warn about real network failures, throttled so a probe cycle is not spammed."""
    now = time.time()
    if now - _NET_WARN_TS.get(phase, 0.0) >= _NET_WARN_INTERVAL:
        _NET_WARN_TS[phase] = now
        logger.warning(f"IGRA2/Wyoming unavailable, fallback to model: {exc}")
    else:
        logger.debug(f"IGRA2/Wyoming still unavailable ({phase}): {exc}")


def _log_integration_error(phase, exc):
    """Log bugs in our own integration loudly, never as 'unavailable'."""
    logger.error(f"IGRA2/Wyoming integration error: {exc}")
    logger.debug(f"IGRA2/Wyoming integration error detail ({phase})", exc_info=True)


def _fallback_station_frame():
    return pd.DataFrame(
        [{"wmo": w, "name": n, "lat": la, "lon": lo}
         for (w, n, la, lo) in _FALLBACK_STATIONS]
    )


def _parse_station_list(text):
    """Parse the IGRA2 station list text file into wmo/name/lat/lon rows."""
    rows = []
    for line in text.splitlines():
        m = _STATION_LINE_RE.match(line)
        if not m:
            continue
        sid, lat, lon, name = m.group(1), m.group(2), m.group(3), m.group(5)
        if len(sid) < 5 or not sid[-5:].isdigit():
            continue
        try:
            la, lo = float(lat), float(lon)
        except ValueError:
            continue
        if pd.isna(la) or pd.isna(lo) or not (-90 <= la <= 90 and -180 <= lo <= 180):
            continue
        rows.append({"wmo": sid[-5:], "name": name.strip(), "lat": la, "lon": lo})
    if not rows:
        return pd.DataFrame(columns=["wmo", "name", "lat", "lon"])
    return pd.DataFrame(rows).drop_duplicates("wmo").reset_index(drop=True)


def _load_stations():
    now = time.time()
    if _STATIONS_CACHE["df"] is not None and (now - _STATIONS_CACHE["ts"]) < _STATIONS_CACHE["ttl"]:
        return _STATIONS_CACHE["df"]
    clean, ttl = None, 7 * 86400
    try:
        resp = requests.get(_STATION_LIST_URL, timeout=_STATION_LIST_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.encoding or "utf-8"
        clean = _parse_station_list(resp.text)
        if clean.empty:
            raise ValueError("IGRA2 station list produced no usable rows")
        logger.info(f"IGRA2 stations loaded: {len(clean)}")
    except Exception as e:
        clean, ttl = _fallback_station_frame(), 3600
        if _is_network_error(e):
            _log_network_unavailable("station catalog", e)
        else:
            _log_integration_error("station catalog", e)
    _STATIONS_CACHE.update({"ts": now, "df": clean, "ttl": ttl})
    return clean


def _nearest(lat, lon, k=4):
    df = _load_stations().copy()
    if df.empty:
        return df
    df["dist"] = df.apply(lambda r: _haversine(lat, lon, r["lat"], r["lon"]), axis=1)
    return df.sort_values("dist").head(k)


def _candidate_times():
    now = datetime.now(timezone.utc)
    base = now.replace(minute=0, second=0, microsecond=0)
    seq = [base.replace(hour=12), base.replace(hour=0),
           base.replace(hour=12) - timedelta(hours=12), base.replace(hour=0) - timedelta(hours=12)]
    seen, out = set(), []
    for t in seq:
        if t <= now and t not in seen:
            seen.add(t); out.append(t)
        if len(out) >= 3:
            break
    return out


def _fetch_sounding(wmo, t):
    key = (wmo, t.isoformat())
    now = time.time()
    if key in _SOUNDING_CACHE and (now - _SOUNDING_TS.get(key, 0)) < _SOUNDING_TTL:
        return _SOUNDING_CACHE[key]
    try:
        df = WyomingUpperAir.request_data(t, wmo)
        if df is not None and not df.empty:
            _SOUNDING_CACHE[key] = df
            _SOUNDING_TS[key] = now
            logger.info(f"Sounding OK wmo={wmo} time={t:%d.%m %HZ}")
            return df
    except Exception as e:
        if _is_network_error(e):
            _log_network_unavailable("sounding fetch", e)
        elif isinstance(e, (AttributeError, NameError, TypeError, ImportError)):
            _log_integration_error("sounding fetch", e)
        else:
            logger.debug(f"Sounding miss wmo={wmo} time={t:%HZ}: {e}")
    return None


def get_sounding_by_wmo(wmo):
    for t in _candidate_times():
        df = _fetch_sounding(wmo, t)
        if df is not None:
            return df, t
    return None, None


def _probe_one(row):
    wmo = str(row.wmo)
    for t in _candidate_times():
        df = _fetch_sounding(wmo, t)
        if df is not None:
            return {"wmo": wmo, "name": str(row["name"]), "dist_km": round(float(row.dist)),
                    "has_data": True, "run_time": t}
    return {"wmo": wmo, "name": str(row["name"]), "dist_km": round(float(row.dist)),
            "has_data": False, "run_time": None}


def probe_stations(lat, lon, k=4):
    key = (round(lat, 1), round(lon, 1))
    now = time.time()
    if key in _PROBE_CACHE and (now - _PROBE_CACHE[key][0]) < _PROBE_TTL:
        return _PROBE_CACHE[key][1]
    near = _nearest(lat, lon, k)
    if near.empty:
        return []
    rows = [r for _, r in near.iterrows()]
    with ThreadPoolExecutor(max_workers=min(4, len(rows))) as ex:
        result = list(ex.map(_probe_one, rows))
    if result[0]["dist_km"] > MAX_COMPARE_KM:
        result = []
    else:
        result = [r for r in result if r["dist_km"] <= MAX_COMPARE_KM]
    _PROBE_CACHE[key] = (now, result)
    return result