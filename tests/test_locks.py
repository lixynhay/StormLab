"""3B: named/keyed locks and cache integrity under concurrent access."""
import threading

from stormlab.core.locks import KeyedLocks, get_lock
import stormlab.clients.geocoding as geo


def test_get_lock_returns_same_lock_per_name():
    assert get_lock("unit") is get_lock("unit")
    assert get_lock("unit") is not get_lock("unit2")


def test_keyed_locks_get_drop():
    locks = KeyedLocks()
    first = locks.get("k")
    assert locks.get("k") is first
    locks.drop("k")
    assert locks.get("k") is not first


def test_geo_cache_two_threads_stay_consistent(monkeypatch):
    geo._GEO_CACHE.clear()
    calls = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            calls.append(1)
            return {"results": [{
                "latitude": 55.75, "longitude": 37.62,
                "name": "Москва", "country": "Россия",
            }]}

    monkeypatch.setattr(geo.requests, "get", lambda *a, **kw: Resp())
    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(geo.resolve_city("Москва"))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 2
    assert results[0] == results[1] == (55.75, 37.62, "Москва, Россия")
    assert list(geo._GEO_CACHE) == ["москва"]
