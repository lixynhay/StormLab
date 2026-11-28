import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from stormlab.render import radar_builder
from stormlab.render.radar_builder import _is_stub_tile, build_radar_image
from tests.cities import BERLIN, MOSCOW, OKC

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name):
    with Image.open(FIXTURE_DIR / name) as image:
        return image.convert("RGBA")


@pytest.mark.parametrize(
    "color",
    [
        (255, 255, 255, 255),
        (192, 192, 192, 255),
    ],
)
def test_single_visible_white_or_gray_tile_is_stub(color):
    tile = Image.new("RGBA", (256, 256), color)

    assert _is_stub_tile(tile) is True


def test_real_rainviewer_stub_fixture_is_detected():
    assert _is_stub_tile(_load_fixture("rainviewer_stub.png")) is True


def test_real_transparent_tile_fixture_is_not_stub():
    assert _is_stub_tile(_load_fixture("rainviewer_transparent.png")) is False


def test_real_echo_tile_fixture_is_not_stub():
    assert _is_stub_tile(_load_fixture("rainviewer_echo.png")) is False


def test_opaque_multicolor_tile_with_chromatic_dominant_is_not_stub():
    tile = Image.new("RGBA", (256, 256), (255, 0, 0, 255))
    tile.putpixel((0, 0), (0, 0, 255, 255))
    tile.putpixel((1, 0), (0, 255, 0, 255))

    assert _is_stub_tile(tile) is False


@pytest.mark.parametrize("lat_lon", [MOSCOW, BERLIN, OKC])
def test_full_tile_url_and_transparent_coverage(monkeypatch, caplog, lat_lon):
    lat, lon = lat_lon
    fixture_bytes = (FIXTURE_DIR / "rainviewer_transparent.png").read_bytes()
    requested_urls = []

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            requested_urls.append(url)
            return SimpleNamespace(status_code=200, content=fixture_bytes)

    monkeypatch.setattr(radar_builder.httpx, "Client", FakeClient)
    with caplog.at_level(logging.INFO, logger=radar_builder.__name__):
        image_buffer = build_radar_image(lat, lon, "/v2/radar/test-frame")

    assert image_buffer is not None
    assert image_buffer.no_echo is True
    assert len(requested_urls) == 9
    assert all("/v2/radar/test-frame/256/6/" in url for url in requested_urls)
    assert all(url.endswith("/2/1_1.png") for url in requested_urls)
    assert "Loaded 9/9 valid radar tiles" in caplog.text


@pytest.mark.parametrize("lat_lon", [MOSCOW, BERLIN, OKC])
def test_zero_valid_tile_coverage_returns_none(monkeypatch, caplog, lat_lon):
    lat, lon = lat_lon
    requested_urls = []

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            requested_urls.append(url)
            return SimpleNamespace(status_code=404)

    monkeypatch.setattr(radar_builder.httpx, "Client", FakeClient)
    with caplog.at_level(logging.WARNING, logger="radar_builder"):
        image_buffer = build_radar_image(lat, lon, "/v2/radar/test-frame")

    assert image_buffer is None
    assert len(requested_urls) == 9
    assert "No valid radar tile coverage" in caplog.text


@pytest.mark.parametrize("lat_lon", [MOSCOW, BERLIN, OKC])
def test_all_stub_tiles_return_none(monkeypatch, caplog, lat_lon):
    lat, lon = lat_lon
    fixture_bytes = (FIXTURE_DIR / "rainviewer_stub.png").read_bytes()

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return SimpleNamespace(status_code=200, content=fixture_bytes)

    monkeypatch.setattr(radar_builder.httpx, "Client", FakeClient)
    with caplog.at_level(logging.WARNING, logger="radar_builder"):
        image_buffer = build_radar_image(lat, lon, "/v2/radar/test-frame", zoom=8)

    assert image_buffer is None
    assert caplog.text.count("is a stub (Zoom Level Not Supported)") == 9
    assert "No valid radar tile coverage" in caplog.text
