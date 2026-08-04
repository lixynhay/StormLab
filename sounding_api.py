import logging
import time
from datetime import datetime, timezone, timedelta
from math import radians, sin, cos, sqrt, atan2
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
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


def _haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def _load_stations():
    now = time.time()
    if _STATIONS_CACHE["df"] is not None and (now - _STATIONS_CACHE["ts"]) < _STATIONS_CACHE["ttl"]:
        return _STATIONS_CACHE["df"]
    clean, ttl = None, 7 * 86400
    try:
        from siphon.simplewebservice.igra2 import IGRAUpperAir
        df = IGRAUpperAir.get_stations()
        df.columns = [c.upper() for c in df.columns]
        if not {"ID", "LATITUDE", "LONGITUDE"}.issubset(set(df.columns)):
            raise ValueError(f"unexpected IGRA2 columns: {list(df.columns)}")
        rows, has_name = [], "NAME" in df.columns
        for _, r in df.iterrows():
            sid = str(r["ID"])
            if len(sid) < 5 or not sid[-5:].isdigit():
                continue
            try:
                la, lo = float(r["LATITUDE"]), float(r["LONGITUDE"])
            except Exception:
                continue
            if pd.isna(la) or pd.isna(lo):
                continue
            name = str(r["NAME"]).strip() if has_name and pd.notna(r.get("NAME")) else sid[-5:]
            rows.append({"wmo": sid[-5:], "name": name, "lat": la, "lon": lo})
        clean = pd.DataFrame(rows).drop_duplicates("wmo").reset_index(drop=True)
        logger.info(f"IGRA2 stations loaded: {len(clean)}")
    except Exception as e:
        logger.warning(f"IGRA2 unavailable, fallback: {e}")
        clean = pd.DataFrame([{"wmo": w, "name": n, "lat": la, "lon": lo} for (w, n, la, lo) in _FALLBACK_STATIONS])
        ttl = 3600
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
            return {"wmo": wmo, "name": str(row.name), "dist_km": round(float(row.dist)),
                    "has_data": True, "run_time": t}
    return {"wmo": wmo, "name": str(row.name), "dist_km": round(float(row.dist)),
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