"""Named and keyed locks for 3B (no global shared dict is mutated unlocked)."""
import threading
from collections import OrderedDict

_named: dict[str, threading.RLock] = {}
_named_guard = threading.Lock()


def get_lock(name: str) -> threading.RLock:
    """One RLock per logical cache name (module-level caches)."""
    with _named_guard:
        lock = _named.get(name)
        if lock is None:
            lock = threading.RLock()
            _named[name] = lock
        return lock


class KeyedLocks:
    """LRU-touched keyed locks; one instance per owning module/state."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: "OrderedDict[object, threading.Lock]" = OrderedDict()

    def get(self, key) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            else:
                self._locks.move_to_end(key)
            return lock

    def drop(self, key) -> None:
        with self._guard:
            self._locks.pop(key, None)
