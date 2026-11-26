import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import alert_manager
import api
from clients import sounding_api
from clients.openmeteo_api import OpenMeteoAPI
from core.storm_indices import PRESSURE_LEVELS, SKEWT_LEVELS, calculate_hodograph_shear_srh

API_KEY = "audit-fix-key-0123456789"


class _FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"current": {"wind_speed_10m": 5.0}}


def test_get_current_requests_wind_in_ms():
    client = OpenMeteoAPI()
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(params)
        return _FakeResponse()

    client._session.get = fake_get
    client.get_current(56.8, 60.6)
    assert captured["wind_speed_unit"] == "ms"


def _profile(surface_wind):
    hourly = {}
    for level in SKEWT_LEVELS:
        hourly[f"wind_speed_{level}hPa"] = [3 + (1000 - level) * 0.05]
        hourly[f"wind_direction_{level}hPa"] = [180 + (1000 - level) * 0.1]
    current = {
        "surface_pressure": 985.0,
        "wind_speed_10m": surface_wind,
        "wind_direction_10m": 180.0,
    }
    return current, hourly


def test_srh_positive_with_wind_in_ms():
    current, hourly = _profile(5.0)
    result = calculate_hodograph_shear_srh(current, hourly, PRESSURE_LEVELS)
    assert result["srh"] > 0


def test_alert_requires_cape():
    report = {"cape": 0, "bulk_shear_06": 20, "cin": 0, "lcl_height_m": 500}
    assert not alert_manager.check_dangerous_conditions(report)
    report["cape"] = 50
    report["bulk_shear_06"] = 16
    assert not alert_manager.check_dangerous_conditions(report)


def test_alert_still_fires_for_real_threat():
    hot = {"cape": 2500, "bulk_shear_06": 25, "cin": -50, "lcl_height_m": 900}
    assert alert_manager.check_dangerous_conditions(hot)


@pytest.mark.parametrize("zone", ["Asia/Yekaterinburg", "UTC", "America/Chicago"])
@pytest.mark.skipif(not hasattr(time, "tzset"), reason="tzset() POSIX-only; cooldown UTC-ness structural via SQLite datetime('now')")
def test_alert_cooldown_independent_of_local_timezone(tmp_path, monkeypatch, zone):
    monkeypatch.setenv("TZ", zone)
    time.tzset()
    monkeypatch.setattr(alert_manager, "DB_PATH", tmp_path / "alerts.db")
    alert_manager.init_db()
    try:
        assert alert_manager.can_send_alert(1, "Test")
        alert_manager.record_alert_sent(1, "Test")
        assert not alert_manager.can_send_alert(1, "Test")

        import sqlite3
        conn = sqlite3.connect(alert_manager.DB_PATH)
        conn.execute("DELETE FROM alert_history")
        conn.execute(
            "INSERT INTO alert_history (user_id, city, sent_at) VALUES (1, 'Test', datetime('now', '-3 hours'))"
        )
        conn.commit()
        conn.close()
        assert alert_manager.can_send_alert(1, "Test")
    finally:
        monkeypatch.delenv("TZ", raising=False)
        time.tzset()


def test_probe_uses_station_name_not_index(monkeypatch):
    row = pd.Series(
        {"wmo": "72357", "name": "Norman, OK", "lat": 35.2, "lon": -97.4, "dist": 56.2},
        name=777,
    )
    monkeypatch.setattr(sounding_api, "_fetch_sounding", lambda wmo, t: pd.DataFrame({"x": [1]}))
    assert sounding_api._probe_one(row)["name"] == "Norman, OK"
    monkeypatch.setattr(sounding_api, "_fetch_sounding", lambda wmo, t: None)
    assert sounding_api._probe_one(row)["name"] == "Norman, OK"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "API_ACCESS_KEY", API_KEY)
    api._rest_rate_limits.clear()
    with TestClient(api.app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_unavailable_radar_is_503(client, monkeypatch):
    monkeypatch.setattr(api, "get_latest_radar_frame", lambda *a, **k: (None, None, False))
    response = client.get("/api/radar", params={"lat": 56, "lon": 60}, headers={"X-API-Key": API_KEY})
    assert response.status_code == 503


def test_calculation_error_hides_internals(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret internal path /srv/stormlab/x.py")

    monkeypatch.setattr(api, "_get_fused_data", boom)
    response = client.get("/api/storm", params={"lat": 56, "lon": 60}, headers={"X-API-Key": API_KEY})
    assert response.status_code == 500
    assert "Internal error" in response.json()["detail"]
    assert "request_id=" in response.json()["detail"]
    assert "/srv/stormlab" not in response.text


def test_short_api_key_refuses_startup(monkeypatch, caplog):
    monkeypatch.setattr(api, "API_ACCESS_KEY", "short")
    with pytest.raises(SystemExit):
        api._require_strong_api_key()
    with caplog.at_level("CRITICAL"):
        with pytest.raises(BaseException):
            with TestClient(api.app):
                pass
    assert "API_ACCESS_KEY слишком короткий" in caplog.text


def test_unset_api_key_still_starts(monkeypatch):
    monkeypatch.setattr(api, "API_ACCESS_KEY", None)
    with TestClient(api.app) as test_client:
        assert test_client.get("/api/health").status_code == 200
