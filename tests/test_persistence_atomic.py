"""3B: atomic persistence must never leave a partial file or temp debris."""
import asyncio
import pickle

import pytest
from telegram.ext import PersistenceInput
from telegram.ext._picklepersistence import _BotUnpickler

from persistence import AtomicPicklePersistence


def _persistence(tmp_path):
    p = AtomicPicklePersistence(
        filepath=str(tmp_path / "persistence.pkl"),
        store_data=PersistenceInput(),
    )
    p.user_data = {1: {"geo": (55.75, 37.62, "Москва")}}
    p.chat_data = {}
    p.conversations = {}
    p.callback_data = None
    p.bot_data = {"ready": True}
    return p


def test_flush_writes_valid_file_without_temp_debris(tmp_path):
    p = _persistence(tmp_path)
    asyncio.run(p.flush())
    with (tmp_path / "persistence.pkl").open("rb") as f:
        data = _BotUnpickler(None, f).load()
    assert data["user_data"][1]["geo"][0] == 55.75
    assert data["bot_data"] == {"ready": True}
    assert not list(tmp_path.glob(".persist_*"))


def test_interrupted_write_keeps_previous_file(tmp_path, monkeypatch):
    p = _persistence(tmp_path)
    asyncio.run(p.flush())
    original = (tmp_path / "persistence.pkl").read_bytes()

    real_replace = __import__("os").replace

    def failing_replace(src, dst):
        raise OSError("simulated interruption")

    monkeypatch.setattr("persistence.os.replace", failing_replace)
    p.bot_data = {"ready": False}
    with pytest.raises(OSError):
        p._dump_singlefile()

    assert (tmp_path / "persistence.pkl").read_bytes() == original
    assert not list(tmp_path.glob(".persist_*"))
    monkeypatch.setattr("persistence.os.replace", real_replace)
