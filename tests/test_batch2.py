import asyncio
import sys
import time
import types
from datetime import datetime, timezone

import pytest

import alert_manager
import rate_limiter
from ai.ai_providers import (
    GeminiProvider, LocalProvider, OpenAICompatProvider, _parse_prompt_data,
    _rule_based_analysis,
)
from clients.openmeteo_api import current_hour_index, resolve_hour_index
from core.season_regime import get_regime
from core.storm_indices import (
    build_skewt_context_for_ai,
    build_thermal_profile,
    interpret_cape,
    interpret_shear,
)


# ---------------------------------------------------------------- п.2 time slots

def test_hourly_index_uses_current_utc_hour_not_midnight():
    times = [f"2026-11-27T{h:02d}:00" for h in range(48)]
    now = datetime(2026, 11, 27, 14, 30, tzinfo=timezone.utc)
    assert current_hour_index(times, now) == 14
    assert resolve_hour_index(times, 0, now) == 14
    assert resolve_hour_index(times, 3, now) == 17
    assert resolve_hour_index(times, 6, now) == 20
    assert resolve_hour_index(times, 12, now) == 26
    assert resolve_hour_index(times, 24, now) == 38


def test_hourly_index_clamps_and_handles_empty():
    assert current_hour_index([]) == 0
    times = ["2026-11-27T00:00", "2026-11-27T01:00"]
    now = datetime(2026, 11, 27, 5, 0, tzinfo=timezone.utc)
    assert resolve_hour_index(times, 24, now) == 1


def test_pressure_levels_requests_surface_vars_and_two_days(monkeypatch):
    from clients.openmeteo_api import OpenMeteoAPI

    client = OpenMeteoAPI()
    captured = {}

    def fake_make_request(params, cache_key=None, lat=None, lon=None):
        captured.update(params)
        return {"hourly": {}}

    monkeypatch.setattr(client, "_make_request", fake_make_request)
    client.get_pressure_levels(35.0, -97.0)

    hourly = captured["hourly"].split(",")
    for var in ("surface_pressure", "temperature_2m", "dew_point_2m",
                "wind_speed_10m", "wind_direction_10m"):
        assert var in hourly
    assert captured["forecast_days"] >= 2


# ------------------------------------------------------- п.3 surface profile

def test_thermal_profile_drops_underground_1000_hpa():
    current = {"surface_pressure": 985.0, "temperature_2m": 20.0, "dew_point_2m": 15.0}
    hourly = {
        "temperature_1000hPa": [21.0], "dew_point_1000hPa": [16.0],
        "temperature_925hPa": [15.0], "dew_point_925hPa": [10.0],
    }
    p, t, td = build_thermal_profile(current, hourly)

    assert p[0] == 985.0
    assert 1000.0 not in p
    assert p == [985.0, 925.0]
    assert t == [20.0, 15.0]
    assert td == [15.0, 10.0]


def test_fused_forecast_uses_button_hours_and_sliced_surface(monkeypatch):
    import bot

    times = [f"2026-11-27T{h:02d}:00" for h in range(48)]
    hourly = {"time": times}
    for i in range(48):
        hourly.setdefault("temperature_2m", []).append(10 + i)
        hourly.setdefault("dew_point_2m", []).append(5 + i)
        hourly.setdefault("surface_pressure", []).append(1000 - i)
        hourly.setdefault("wind_speed_10m", []).append(3 + i)
        hourly.setdefault("wind_direction_10m", []).append(180)

    monkeypatch.setattr(bot.weather_api, "get_current",
                        lambda lat, lon: {"current": {"surface_pressure": 999}})
    monkeypatch.setattr(bot.weather_api, "get_pressure_levels",
                        lambda lat, lon: {"hourly": hourly})

    def fake_resolve(t, offset=0, now=None):
        assert offset == 3
        return 17

    monkeypatch.setattr(bot, "resolve_hour_index", fake_resolve)
    current_data, pressure_data, _ = bot._get_fused_current_data(35.0, -97.0, 3)

    assert current_data["current"]["temperature_2m"] == 27
    assert current_data["current"]["surface_pressure"] == 983
    assert pressure_data["hourly"]["temperature_2m"] == [27]


# ------------------------------------------------------------- 2.2 hemisphere

def test_southern_winter_is_cool_and_north_pins_hold():
    # Southern hemisphere mirrors the northern 45°/55° heuristic.
    assert get_regime(-55, 7) == "cool"
    assert get_regime(-55, 1) == "warm"
    assert get_regime(-60, 10) == "cool"
    assert get_regime(-33, 7) == "warm"   # below the 45° heuristic
    assert get_regime(-33, 1) == "warm"
    assert get_regime(56, 1) == "cool"
    assert get_regime(56, 7) == "warm"
    assert get_regime(60, 4) == "cool"
    assert get_regime(40, 1) == "warm"
    assert get_regime(35, 7) == "warm"


# --------------------------------------------------------- 2.1 seasonal alerts

def test_winter_alert_passes_cool_thresholds_but_not_warm_floor():
    winter = {"cape": 220, "bulk_shear_06": 22, "cin": -50, "lcl_height_m": 2000}
    assert alert_manager.check_dangerous_conditions(winter, regime="cool") is not None
    assert "thundersnow" in alert_manager.check_dangerous_conditions(winter, regime="cool")
    assert alert_manager.check_dangerous_conditions(winter, regime="warm") is None


def test_summer_profile_does_not_fire_warm_alert_with_low_shear():
    summer = {"cape": 300, "bulk_shear_06": 12, "cin": -50, "lcl_height_m": 2000}
    assert alert_manager.check_dangerous_conditions(summer, regime="warm") is None


def test_cool_supercell_branch_is_reworded_as_thundersnow():
    # 2 reasons only (CAPE + shear), so the supercell branch is reached.
    cool = {"cape": 2100, "bulk_shear_06": 22, "cin": -300, "lcl_height_m": 5000}
    warm = {"cape": 2100, "bulk_shear_06": 22, "cin": -300, "lcl_height_m": 5000}
    assert "thundersnow" in alert_manager.check_dangerous_conditions(cool, regime="cool")
    assert "суперячеек" in alert_manager.check_dangerous_conditions(warm, regime="warm")


# ------------------------------------------------- 2.3 seasonal interpretations

def test_cool_shear_interpretation_is_winter_not_supercell():
    assert "суперяче" not in interpret_shear(22, "cool")
    assert "snow-squall" in interpret_shear(22, "cool")
    assert "суперячейки" in interpret_shear(22, "warm")


def test_cool_cape_interpretation_is_thundersnow():
    assert "thundersnow" in interpret_cape(220, "cool")
    assert "слабая нестабильность" in interpret_cape(220, "warm")


# ------------------------------------------------------- 2.4 AI/local context

def test_skewt_context_includes_season_line():
    current = {"temperature_2m": 1.0, "dew_point_2m": -1.0, "surface_pressure": 985.0}
    hourly = {
        "temperature_850hPa": [-2.0], "dew_point_850hPa": [-4.0],
        "temperature_500hPa": [-20.0], "dew_point_500hPa": [-25.0],
    }
    cool_report = {"cape": 220, "cin": -30, "lcl": 900, "regime": "cool"}
    warm_report = {"cape": 220, "cin": -30, "lcl": 900, "regime": "warm"}

    cool_ctx = build_skewt_context_for_ai(cool_report, current, {"hourly": hourly})
    warm_ctx = build_skewt_context_for_ai(warm_report, current, {"hourly": hourly})

    assert "Сезонный режим: cool" in cool_ctx
    assert "thundersnow" in cool_ctx
    assert "Сезонный режим: warm" in warm_ctx


def test_local_provider_is_seasonal():
    prompt = (
        "Данные:\nСезонный режим: cool\n"
        "CAPE (SB): 220 Дж/кг | CIN: 30 Дж/кг | LCL: 900 гПа\n"
        "K-Index: 25 | Total Totals: 45 | Lifted Index: -2\n"
        "Сдвиг 0-6 км: 22 м/с | Сдвиг 0-3 км: 12 м/с\n"
        "SRH: 120 | EHI: 0.1 | BRN: 3\n"
        "STP: 0.3 | SCP: 1.0 | DCAPE: 600\n"
    )
    data = _parse_prompt_data(prompt)
    assert data["regime"] == "cool"
    text = _rule_based_analysis(data, "Тест")
    assert "thundersnow" in text
    assert "торнадо-опасные суперячейки" not in text


# ------------------------------------------------------------ п.7 rate limits

class _FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)


class _FakeUser:
    def __init__(self, uid=42):
        self.id = uid


class _FakeUpdate:
    def __init__(self, data=None):
        self.callback_query = _FakeQuery(data) if data else None
        self.effective_user = _FakeUser()
        self.effective_message = None


def test_rate_limit_decorator_blocks_sixth_callback_click(monkeypatch):
    rate_limiter._rate_limits.clear()
    calls = []

    @rate_limiter.rate_limited()
    async def handler(update, context):
        calls.append(1)

    async def run():
        for _ in range(6):
            await handler(_FakeUpdate("refresh"), types.SimpleNamespace(user_data={}))

    asyncio.run(run())
    assert len(calls) == 1

    # explicit check: subsequent clicks are answered with show_alert
    update = _FakeUpdate("refresh")
    asyncio.run(handler(update, types.SimpleNamespace(user_data={})))
    assert update.callback_query.answers and "Подожди" in update.callback_query.answers[-1]


def test_time_callback_uses_pending_action_operation():
    update = _FakeUpdate("time:1")
    context = types.SimpleNamespace(user_data={"pending_action": "skewt"})
    assert rate_limiter.operation_for_update(update, context) == "skewt"
    update = _FakeUpdate("stn:72357")
    assert rate_limiter.operation_for_update(update, types.SimpleNamespace(user_data={})) == "sounding"


# ------------------------------------------------------ 7b limits and dedupe

def test_alert_grouping_dedupes_same_location():
    alerts = [
        {"user_id": 1, "city": "Moscow", "lat": 55.751, "lon": 37.618},
        {"user_id": 2, "city": "Moskva", "lat": 55.754, "lon": 37.620},
        {"user_id": 3, "city": "Sochi", "lat": 43.60, "lon": 39.73},
    ]
    groups = alert_manager.group_alerts_by_location(alerts)
    assert len(groups) == 2
    assert max(len(g) for g in groups.values()) == 2


def test_alert_subscription_limit_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(alert_manager, "DB_PATH", tmp_path / "alerts.db")
    monkeypatch.setattr(alert_manager, "MAX_ALERTS_PER_USER", 5)
    alert_manager.init_db()
    try:
        for i in range(5):
            assert alert_manager.add_alert(1, "u", f"City{i}", 50.0 + i, 30.0 + i)
        assert not alert_manager.add_alert(1, "u", "City6", 60.0, 40.0)
        # same rounded location does not count as a new subscription
        assert alert_manager.add_alert(1, "u", "City0-alias", 50.0, 30.0)
        assert len(alert_manager.get_user_location_keys(1)) == 5
    finally:
        pass


# ---------------------------------------------------------------- 6a timeouts

def test_openai_provider_sets_explicit_timeout_and_no_retries(monkeypatch):
    from config import LLM_REQUEST_TIMEOUT

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))
    provider = OpenAICompatProvider("n", "key", "http://x", "m")
    client = provider._get_client()
    assert client.kwargs["timeout"] == LLM_REQUEST_TIMEOUT
    assert client.kwargs["max_retries"] == 0


def test_gemini_provider_uses_gemini_api_timeout(monkeypatch):
    import google.genai as genai

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(genai, "Client", FakeClient)
    provider = GeminiProvider("key", "m", timeout=7)
    client = provider._get_client()
    assert client.kwargs["http_options"].timeout == 7000


def test_wait_for_returns_control_from_hanging_call():
    async def hanging():
        await asyncio.sleep(5)
        return "late"

    async def run():
        start = time.monotonic()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(hanging(), timeout=0.2)
        return time.monotonic() - start

    elapsed = asyncio.run(run())
    assert elapsed < 1.0
