"""Batch 2.5 regression tests: REST season propagation + pop-safe cache cleanup."""
import warnings
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import api
from clients.openmeteo_api import OpenMeteoAPI


API_KEY = "0123456789abcdef0123456789abcdef"


def _synthetic_current(lat, lon):
    return {
        "current": {
            "temperature_2m": -5.0,
            "dew_point_2m": -8.0,
            "surface_pressure": 985.0,
            "wind_speed_10m": 10.0,
            "wind_direction_10m": 270.0,
        }
    }


def _synthetic_pressure(lat, lon):
    times = [f"2026-01-15T{h:02d}:00" for h in range(48)]
    hourly = {
        "time": times,
        "surface_pressure": [985.0] * 48,
        "temperature_2m": [-5.0] * 48,
        "dew_point_2m": [-8.0] * 48,
        "wind_speed_10m": [10.0] * 48,
        "wind_direction_10m": [270.0] * 48,
    }
    for i, lvl in enumerate((1000, 975, 950, 925, 900, 850, 800, 700, 600, 500, 400, 300)):
        hourly[f"temperature_{lvl}hPa"] = [-6.0 - i] * 48
        hourly[f"dew_point_{lvl}hPa"] = [-9.0 - i] * 48
        hourly[f"wind_speed_{lvl}hPa"] = [12.0 + i] * 48
        hourly[f"wind_direction_{lvl}hPa"] = [270.0 + i] * 48
    return {"hourly": hourly}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "API_ACCESS_KEY", API_KEY)
    monkeypatch.setattr(api.weather_api, "get_current", _synthetic_current)
    monkeypatch.setattr(api.weather_api, "get_pressure_levels", _synthetic_pressure)
    monkeypatch.setattr(api.owm_api, "get_current", lambda lat, lon: None)
    with TestClient(api.app) as c:
        yield c


def _freeze_month(monkeypatch, month):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, month, 15, 12, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(api, "datetime", FrozenDatetime)


def test_rest_winter_city_gets_cool_regime(client, monkeypatch):
    _freeze_month(monkeypatch, 1)
    response = client.get(
        "/api/storm",
        params={"lat": 55.75, "lon": 37.62, "city": "Moscow"},
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 200, response.text
    report = response.json()["report"]
    assert report["regime"] == "cool"
    assert "зимн" in report["cape_interpretation"]
    assert "зим" in report["cin_interpretation"] or "снеж" in report["cin_interpretation"]
    assert report["bulk_shear_06"] > 0


def test_rest_summer_city_gets_warm_regime(client, monkeypatch):
    _freeze_month(monkeypatch, 7)
    response = client.get(
        "/api/storm",
        params={"lat": 35.47, "lon": -97.51, "city": "OKC"},
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 200, response.text
    report = response.json()["report"]
    assert report["regime"] == "warm"
    assert "зимн" not in report["cape_interpretation"]


def test_rest_ai_analysis_no_arity_crash(client, monkeypatch):
    _freeze_month(monkeypatch, 1)
    monkeypatch.setattr(api, "generate_storm_analysis", lambda report, city, ctx: "stub-analysis")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        response = client.post(
            "/api/ai-analysis",
            json={"lat": 55.75, "lon": 37.62, "city": "Moscow", "time_index": 0},
            headers={"X-API-Key": API_KEY},
        )
    assert response.status_code == 200, response.text
    assert response.json()["analysis"] == "stub-analysis"
    assert not [w for w in caught if "Interpolation" in str(w.message)]


def test_rest_skewt_chart_uses_seasonal_regime(client, monkeypatch):
    _freeze_month(monkeypatch, 1)
    captured = {}

    def fake_chart(current, hourly, df, rt, city, time_label, report=None, **kwargs):
        captured["regime"] = (report or {}).get("regime")
        return iter([b"fake-png"])

    monkeypatch.setattr(api, "build_skewt_chart", fake_chart)
    response = client.get(
        "/api/chart/skewt",
        params={"lat": 55.75, "lon": 37.62, "city": "Moscow"},
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 200, response.text
    assert captured["regime"] == "cool"


def test_cleanup_cache_is_pop_safe_after_concurrent_eviction():
    client_api = OpenMeteoAPI()
    # Simulate a second to_thread call having already evicted the data entry
    # while _cache_timestamps still lists it as expired.
    client_api._cache.clear()
    client_api._cache_timestamps["current_1_2"] = datetime(2000, 1, 1)
    client_api._cache_timestamps["forecast_1_2"] = datetime(2000, 1, 1)
    client_api._cache["forecast_1_2"] = {"hourly": {}}

    client_api._cleanup_cache()  # must not raise KeyError

    assert "current_1_2" not in client_api._cache_timestamps
    assert "forecast_1_2" not in client_api._cache_timestamps
    assert client_api._cache.get("forecast_1_2") is None


def test_cleanup_cache_pop_safe_on_size_prune():
    client_api = OpenMeteoAPI()
    client_api._cache.clear()
    client_api._cache_timestamps.clear()
    base = datetime(2026, 1, 1)
    for i in range(60):
        key = f"current_{i}"
        client_api._cache_timestamps[key] = base.replace(minute=i % 60)
        # half of the keys were already evicted by a concurrent call
        if i % 2 == 0:
            client_api._cache[key] = {"current": {}}
    client_api._cleanup_cache()  # must not raise KeyError
    assert len(client_api._cache) <= client_api._max_cache_size
