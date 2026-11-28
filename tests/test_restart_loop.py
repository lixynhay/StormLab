"""Auto-restart proof: the wrapper must not change the in-process restart loop."""

import time
from types import SimpleNamespace

import pytest

import stormlab.bot as bot


def test_restart_loop_recovers_after_one_failure(monkeypatch):
    events = []

    class FakeApp:
        def run_polling(self, **kwargs):
            events.append("polled")

    def fake_build():
        events.append("build")
        if events.count("build") == 1:
            raise RuntimeError("boom")
        return FakeApp()

    monkeypatch.setattr(bot, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(bot, "build_application", fake_build)
    monkeypatch.setattr(
        bot, "time",
        SimpleNamespace(time=time.time, sleep=lambda seconds: events.append(("sleep", seconds))),
    )

    bot.main()

    assert events == ["build", ("sleep", 5), "build", "polled"]


def test_five_fast_failures_exit(monkeypatch):
    builds = []

    def fake_build():
        builds.append(1)
        raise RuntimeError("deterministic bug")

    monkeypatch.setattr(bot, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(bot, "build_application", fake_build)
    monkeypatch.setattr(
        bot, "time",
        SimpleNamespace(time=time.time, sleep=lambda seconds: None),
    )

    with pytest.raises(SystemExit) as exc:
        bot.main()

    assert exc.value.code == 1
    assert len(builds) == 5
