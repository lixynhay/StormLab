import pytest

import radar_api

VALID_PATH = "/v2/radar/237cea37e45b"
VALID_HOST = "https://tilecache.rainviewer.com"


@pytest.fixture(autouse=True)
def _reset_radar_cache():
    radar_api._cache.update({
        "last_check": 0,
        "is_valid": False,
        "last_valid_path": None,
        "last_valid_time": None,
    })


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    payload = {}

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url):
        return _FakeResponse(self.payload)


def _payload(path, host=VALID_HOST):
    return {"host": host, "radar": {"past": [{"time": 1795711200, "path": path}]}}


def test_accepts_real_rainviewer_path():
    assert radar_api._is_valid_radar_path(VALID_PATH, VALID_HOST)
    assert radar_api._is_valid_radar_path(VALID_PATH)
    assert radar_api._is_valid_radar_path(VALID_PATH, "https://tilecache.rainviewer.com/")


@pytest.mark.parametrize("path", [
    "/v2/radar/237cea37e45b/512/6/1/2",   # extra segments
    "/v2/radar/",                          # empty hash
    "/v2/radar/../secret",                 # traversal
    "/v2/radar/abc?x=1",                   # query
    "/v2/radar/abc def",                   # whitespace
    "/v2/satellite/abc",                   # wrong prefix
    "https://evil.example.com/v2/radar/abc",  # absolute URL
    "",
    None,
])
def test_rejects_bad_paths(path):
    assert not radar_api._is_valid_radar_path(path, VALID_HOST)


@pytest.mark.parametrize("host", [
    "https://evil.example.com",
    "http://tilecache.rainviewer.com",          # https only
    "https://tilecache.rainviewer.com.evil.com",
    "https://tilecache.rainviewer.com/path",
    "https://tilecache.rainviewer.com?x=1",
])
def test_rejects_foreign_hosts(host):
    assert not radar_api._is_valid_radar_path(VALID_PATH, host)


def test_frame_with_real_path_is_returned(monkeypatch):
    _FakeClient.payload = _payload(VALID_PATH)
    monkeypatch.setattr(radar_api.httpx, "Client", _FakeClient)

    path, dt_utc, is_cached = radar_api.get_latest_radar_frame(force_check=True)

    assert path == VALID_PATH
    assert dt_utc is not None
    assert is_cached is False


def test_frame_with_foreign_host_is_rejected(monkeypatch):
    _FakeClient.payload = _payload(VALID_PATH, host="https://evil.example.com")
    monkeypatch.setattr(radar_api.httpx, "Client", _FakeClient)

    assert radar_api.get_latest_radar_frame(force_check=True) == (None, None, False)


def test_frame_with_extra_segments_is_rejected(monkeypatch):
    _FakeClient.payload = _payload("/v2/radar/237cea37e45b/512/6/1/2")
    monkeypatch.setattr(radar_api.httpx, "Client", _FakeClient)

    assert radar_api.get_latest_radar_frame(force_check=True) == (None, None, False)
