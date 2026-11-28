"""Batch 3A tests: REST time-index, redaction, markdown, ctx isolation, subscriptions."""
import asyncio
import logging
import types
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import stormlab.api as api
import stormlab.bot as bot
import stormlab.clients.openmeteo_api as om
import stormlab.rate_limiter as rate_limiter
from stormlab.core.text_safety import escape_markdown, redact_secrets
from telegram.error import Forbidden, NetworkError

API_KEY = "0123456789abcdef0123456789abcdef"


def _freeze_utc(monkeypatch, year=2026, month=11, day=27, hour=14, minute=30):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    monkeypatch.setattr(om, "datetime", Frozen)
    monkeypatch.setattr(api, "datetime", Frozen)
    monkeypatch.setattr(api, "_utc_now", lambda: Frozen.now(timezone.utc))


def _hourly_48():
    base = datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc)
    times = [(base + timedelta(hours=h)).strftime("%Y-%m-%dT%H:00") for h in range(48)]
    return {
        "time": times,
        "surface_pressure": [1000 - i for i in range(48)],
        "temperature_2m": [10 + i for i in range(48)],
        "dew_point_2m": [5 + i for i in range(48)],
        "wind_speed_10m": [3 + i for i in range(48)],
        "wind_direction_10m": [180] * 48,
    }


@pytest.fixture
def client(monkeypatch):
    hourly = _hourly_48()
    monkeypatch.setattr(api, "API_ACCESS_KEY", API_KEY)
    monkeypatch.setattr(api.weather_api, "get_current",
                        lambda lat, lon: {"current": {"surface_pressure": 999}})
    monkeypatch.setattr(api.weather_api, "get_pressure_levels",
                        lambda lat, lon: {"hourly": hourly})
    monkeypatch.setattr(api.owm_api, "get_current", lambda lat, lon: None)
    with TestClient(api.app) as c:
        yield c


# ------------------------------------------------------------- Wave 2: time index

def _patch_weather(monkeypatch):
    hourly = _hourly_48()
    for module in (api, bot):
        monkeypatch.setattr(module.weather_api, "get_current",
                            lambda lat, lon: {"current": {"surface_pressure": 999}})
        monkeypatch.setattr(module.weather_api, "get_pressure_levels",
                            lambda lat, lon: {"hourly": hourly})
        monkeypatch.setattr(module.owm_api, "get_current", lambda lat, lon: None)


def test_rest_time_index_uses_current_hour_base(client, monkeypatch):
    _freeze_utc(monkeypatch)
    _patch_weather(monkeypatch)
    _, pressure, _, _ = api._get_fused_data(35.47, -97.51, 0)
    assert pressure["hourly"]["time"][0] == "2026-11-27T14:00"
    # the same request through TestClient stays 200
    r = client.get("/api/storm", params={"lat": 35.47, "lon": -97.51, "time_index": 0},
                   headers={"X-API-Key": API_KEY})
    assert r.status_code == 200


def test_rest_time_index_offsets_and_bot_parity(client, monkeypatch):
    _freeze_utc(monkeypatch)
    _patch_weather(monkeypatch)
    expected = {
        0: "2026-11-27T14:00", 1: "2026-11-27T17:00",
        4: "2026-11-28T14:00",
    }
    hour_offsets = (0, 3, 6, 12, 24)
    for idx, want in expected.items():
        _, pressure, _, _ = api._get_fused_data(35.47, -97.51, idx)
        assert pressure["hourly"]["time"][0] == want
        _, bot_pressure, _ = bot._get_fused_current_data(35.47, -97.51, hour_offsets[idx])
        assert bot_pressure["hourly"]["time"][0] == want

    r = client.get("/api/storm", params={"lat": 35.47, "lon": -97.51, "time_index": 4},
                   headers={"X-API-Key": API_KEY})
    assert r.status_code == 200


# ------------------------------------------------------------- Wave 3: redaction

def test_redact_secrets_removes_appid():
    text = "HTTPError: https://api.openweathermap.org/data/2.5/weather?lat=1&appid=SECRET123&units=metric"
    assert "SECRET123" not in redact_secrets(text)
    assert "***REDACTED***" in redact_secrets(text)


def test_owm_exception_key_never_reaches_logs(client, monkeypatch, caplog):
    def boom(lat, lon):
        raise RuntimeError(
            "https://api.openweathermap.org/data/2.5/weather?appid=SECRET123&lat=1"
        )
    monkeypatch.setattr(api.owm_api, "get_current", boom)
    with caplog.at_level(logging.WARNING):
        r = client.get("/api/storm", params={"lat": 35.47, "lon": -97.51},
                       headers={"X-API-Key": API_KEY})
    assert r.status_code == 200
    assert "SECRET123" not in caplog.text


# ------------------------------------------------------------- Wave 4: markdown

def test_escape_markdown_escapes_dynamic_city():
    out = escape_markdown("Москва_тест*[x]`")
    assert "\\_" in out and "\\*" in out and "\\[" in out and "\\`" in out


def test_ai_response_sent_without_parse_mode(monkeypatch):
    class FakeMessageTarget:
        def __init__(self):
            self.chat = types.SimpleNamespace(id=1)
            self.calls = []

        async def reply_text(self, text, **kwargs):
            self.calls.append((text, kwargs))

    monkeypatch.setattr(bot, "generate_storm_analysis",
                        lambda report, city, ctx: "AI текст с _ * [ ] и `кавычками`")
    target = FakeMessageTarget()
    context = types.SimpleNamespace(user_data={
        "last_report": {
            "report": {"cape": 400, "regime": "warm"}, "city": "Москва",
            "time_label": "Сейчас", "current": {}, "pressure": {},
        }
    })
    asyncio.run(bot._send_ai_analysis(target, context))
    assert len(target.calls) == 2
    assert "parse_mode" not in target.calls[1][1]


# ------------------------------------------------------------- Wave 5: ctx keys

class _FakeQuery:
    def __init__(self, chat_id, message_id, data):
        self.data = data
        self.answers = []
        self.message = types.SimpleNamespace(
            chat=types.SimpleNamespace(id=chat_id),
            message_id=message_id,
            edit_message_media=lambda *a, **kw: _done(),
        )

    async def edit_message_media(self, *args, **kwargs):
        return None

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)


def _done():
    async def f():
        return None
    return f()


def test_ctx_is_keyed_by_chat_and_message(monkeypatch):
    rate_limiter._rate_limits.clear()
    bot._skewt_ctx.clear()
    probe = [{"wmo": "72353", "name": "OKC", "dist_km": 12, "has_data": True}]
    bot._skewt_ctx[(1, 777)] = (35.0, -97.0, "Москва", {}, {}, probe, "Сейчас", {})
    bot._skewt_ctx[(2, 777)] = (55.0, 37.0, "Сочи", {}, {}, probe, "Сейчас", {})

    captured = []
    monkeypatch.setattr(bot, "build_skewt_chart",
                        lambda *a, **kw: captured.append(kw.get("report")) or "img")
    query = _FakeQuery(1, 777, "stn:__model__")
    update = types.SimpleNamespace(callback_query=query,
                                   effective_user=types.SimpleNamespace(id=999999))
    asyncio.run(bot.button_handler(update, types.SimpleNamespace(user_data={})))
    # chart was built with chat 1's context; city is taken from the tuple, not another chat
    assert len(captured) == 1
    assert bot._skewt_ctx[(1, 777)][2] == "Москва"
    assert bot._skewt_ctx[(2, 777)][2] == "Сочи"

    fake_wmo = _FakeQuery(1, 777, "stn:FAKE")
    rate_limiter._rate_limits.clear()
    asyncio.run(bot.button_handler(
        types.SimpleNamespace(callback_query=fake_wmo,
                              effective_user=types.SimpleNamespace(id=999999)),
        types.SimpleNamespace(user_data={}),
    ))
    assert fake_wmo.answers and "Станция не найдена" in fake_wmo.answers[-1]


# ------------------------------------------------------------- Wave 6: subscriptions

def _alert_context(send_exc):
    class FakeBot:
        async def send_message(self, **kwargs):
            raise send_exc

    alerts = [{"user_id": 42, "city": "Омск", "lat": 55.0, "lon": 73.0}]
    return types.SimpleNamespace(
        bot=FakeBot(),
        job=types.SimpleNamespace(),
    ), alerts


def test_forbidden_removes_subscription_but_network_error_does_not(monkeypatch):
    removed, pruned = [], []

    def fake_fused(lat, lon, idx):
        return ({"current": {}}, {"hourly": {}}, "mock")

    monkeypatch.setattr(bot, "_get_fused_current_data", fake_fused)
    monkeypatch.setattr(bot, "get_all_alerts", lambda: [
        {"user_id": 42, "city": "Омск", "lat": 55.0, "lon": 73.0}
    ])
    monkeypatch.setattr(bot, "can_send_alert", lambda u, c: True)
    monkeypatch.setattr(bot, "build_storm_report", lambda *a, **kw: {"cape": 2000})
    monkeypatch.setattr(bot, "check_dangerous_conditions", lambda *a, **kw: "danger")
    monkeypatch.setattr(bot, "remove_alert", lambda u, c: removed.append((u, c)))
    monkeypatch.setattr(bot, "prune_history", lambda: pruned.append(True))

    class FakeBot:
        def __init__(self, exc):
            self.exc = exc

        async def send_message(self, **kwargs):
            raise self.exc

    for exc, should_remove in ((Forbidden("blocked"), True), (NetworkError("network"), False)):
        removed.clear()
        context = types.SimpleNamespace(bot=FakeBot(exc))
        asyncio.run(bot.alerts_background_task(context))
        assert bool(removed) is should_remove
    assert pruned  # prune_history called after the job


def test_prune_history_keeps_cooldown_window(tmp_path, monkeypatch):
    import stormlab.alert_manager as am

    monkeypatch.setattr(am, "DB_PATH", tmp_path / "alerts.db")
    am.init_db()
    with am._connect() as conn:
        conn.execute(
            "INSERT INTO alert_history (user_id, city, sent_at) VALUES (?, ?, datetime('now'))",
            (1, "Омск"),
        )
        conn.execute(
            "INSERT INTO alert_history (user_id, city, sent_at) VALUES (?, ?, datetime('now','-40 days'))",
            (1, "Сочи"),
        )
        conn.commit()
    am.prune_history(30)
    with am._connect() as conn:
        cities = [r[0] for r in conn.execute("SELECT city FROM alert_history")]
    assert "Омск" in cities and "Сочи" not in cities


def test_sqlite_connection_closed_on_exception(tmp_path, monkeypatch):
    import stormlab.alert_manager as am

    class FakeConn:
        closed = False

        def cursor(self):
            return self

        def execute(self, *a, **kw):
            raise RuntimeError("boom")

        def fetchall(self):
            return []

        def close(self):
            FakeConn.closed = True

    monkeypatch.setattr(am.sqlite3, "connect", lambda *a, **kw: FakeConn())
    assert am.get_all_alerts() == []
    assert FakeConn.closed is True


# ------------------------------------------------------------- 3A blockers

def test_api_empty_hourly_returns_200(client, monkeypatch):
    monkeypatch.setattr(api.weather_api, "get_pressure_levels", lambda lat, lon: {"hourly": {}})
    r = client.get("/api/storm", params={"lat": 35.47, "lon": -97.51, "time_index": 0},
                   headers={"X-API-Key": API_KEY})
    assert r.status_code == 200


def test_api_time_index_out_of_range_is_422(client):
    r = client.get("/api/storm", params={"lat": 35.47, "lon": -97.51, "time_index": 5},
                   headers={"X-API-Key": API_KEY})
    assert r.status_code == 422


def test_api_time_index_consistency(monkeypatch):
    current = {"temperature_2m": 12.0, "dew_point_2m": 7.0, "surface_pressure": 999.0}
    monkeypatch.setattr(api.weather_api, "get_current", lambda lat, lon: {"current": current})
    monkeypatch.setattr(api.weather_api, "get_pressure_levels",
                        lambda lat, lon: {"hourly": _hourly_48()})
    monkeypatch.setattr(api.owm_api, "get_current", lambda lat, lon: None)
    fused, _, _, _ = api._get_fused_data(35.47, -97.51, 0)
    assert fused["current"] == current


def test_forbidden_with_remove_alert_failure_continues(monkeypatch):
    import sqlite3

    processed = []

    def fake_remove(user_id, city):
        raise sqlite3.OperationalError("locked")

    monkeypatch.setattr(bot, "_get_fused_current_data",
                        lambda lat, lon, idx: ({"current": {}}, {"hourly": {}}, "mock"))
    monkeypatch.setattr(bot, "get_all_alerts", lambda: [
        {"user_id": 1, "city": "A", "lat": 55.0, "lon": 73.0},
        {"user_id": 2, "city": "B", "lat": 56.0, "lon": 74.0},
    ])
    monkeypatch.setattr(bot, "can_send_alert", lambda u, c: True)
    monkeypatch.setattr(bot, "build_storm_report", lambda *a, **kw: {"cape": 2000})
    monkeypatch.setattr(bot, "check_dangerous_conditions", lambda *a, **kw: "danger")
    monkeypatch.setattr(bot, "remove_alert", fake_remove)
    monkeypatch.setattr(bot, "record_alert_sent", lambda u, c: processed.append((u, c)))
    monkeypatch.setattr(bot, "prune_history", lambda: None)

    calls = []

    class FakeBot:
        async def send_message(self, **kwargs):
            user = kwargs["chat_id"]
            calls.append(user)
            if user == 1:
                raise Forbidden("blocked")

    asyncio.run(bot.alerts_background_task(types.SimpleNamespace(bot=FakeBot())))
    assert calls == [1, 2]  # both deliveries attempted; failure did not break the loop
    assert processed == [(2, "B")]
