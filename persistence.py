"""Atomic single-file persistence for python-telegram-bot v22.

In v22 the actual disk write happens in ``PicklePersistence._dump_singlefile``,
called from the async ``flush()``. Overriding that sync method keeps PTB's
flush semantics (including the non-empty checks) and makes the write atomic:
write to a temp file, fsync, then os.replace over the target.
"""
import os
import pickle
import tempfile
import threading
from pathlib import Path

from telegram.ext import PicklePersistence
from telegram.ext._picklepersistence import _BotPickler


class AtomicPicklePersistence(PicklePersistence):
    _io_lock = threading.RLock()

    def _dump_singlefile(self) -> None:
        with self._io_lock:
            data = {
                "conversations": self.conversations,
                "user_data": self.user_data,
                "chat_data": self.chat_data,
                "bot_data": self.bot_data,
                "callback_data": self.callback_data,
            }
            target = Path(self.filepath)
            directory = target.parent if str(target.parent) else Path(".")
            fd, tmp = tempfile.mkstemp(dir=directory, prefix=".persist_")
            try:
                with os.fdopen(fd, "wb") as file:
                    _BotPickler(self.bot, file, protocol=pickle.HIGHEST_PROTOCOL).dump(data)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(tmp, target)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
