"""3A/3B: Forbidden removes subscription; failure of removal does not break the job."""
import asyncio
import sqlite3
import types

import stormlab.bot as bot
from telegram.error import Forbidden, NetworkError


def _setup(monkeypatch, alerts, remove_impl, processed, send_impl):
    monkeypatch.setattr(bot, "_get_fused_current_data",
                        lambda lat, lon, idx: ({"current": {}}, {"hourly": {}}, "mock"))
    monkeypatch.setattr(bot, "get_all_alerts", lambda: alerts)
    monkeypatch.setattr(bot, "can_send_alert", lambda u, c: True)
    monkeypatch.setattr(bot, "build_storm_report", lambda *a, **kw: {"cape": 2000})
    monkeypatch.setattr(bot, "check_dangerous_conditions", lambda *a, **kw: "danger")
    monkeypatch.setattr(bot, "remove_alert", remove_impl)
    monkeypatch.setattr(bot, "record_alert_sent", lambda u, c: processed.append((u, c)))
    monkeypatch.setattr(bot, "prune_history", lambda: None)

    class FakeBot:
        async def send_message(self, **kwargs):
            return send_impl(kwargs["chat_id"])

    return types.SimpleNamespace(bot=FakeBot())


def test_forbidden_removes_and_continues(monkeypatch):
    removed = []
    processed = []
    alerts = [
        {"user_id": 1, "city": "A", "lat": 55.0, "lon": 73.0},
        {"user_id": 2, "city": "B", "lat": 56.0, "lon": 74.0},
    ]

    def send(user):
        if user == 1:
            raise Forbidden("blocked")

    ctx = _setup(monkeypatch, alerts, lambda u, c: removed.append((u, c)), processed, send)
    asyncio.run(bot.alerts_background_task(ctx))
    assert removed == [(1, "A")]
    assert processed == [(2, "B")]


def test_forbidden_with_remove_failure_still_continues(monkeypatch):
    processed = []
    alerts = [
        {"user_id": 1, "city": "A", "lat": 55.0, "lon": 73.0},
        {"user_id": 2, "city": "B", "lat": 56.0, "lon": 74.0},
    ]

    def boom(u, c):
        raise sqlite3.OperationalError("locked")

    def send(user):
        if user == 1:
            raise Forbidden("blocked")

    ctx = _setup(monkeypatch, alerts, boom, processed, send)
    asyncio.run(bot.alerts_background_task(ctx))
    assert processed == [(2, "B")]


def test_network_error_never_removes(monkeypatch):
    removed = []
    alerts = [{"user_id": 1, "city": "A", "lat": 55.0, "lon": 73.0}]

    def send(user):
        raise NetworkError("temporary")

    ctx = _setup(monkeypatch, alerts, lambda u, c: removed.append((u, c)), [], send)
    asyncio.run(bot.alerts_background_task(ctx))
    assert removed == []
