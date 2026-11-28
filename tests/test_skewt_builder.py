import matplotlib.pyplot as plt
import numpy as np
import pytest
from metpy.plots import SkewT
from metpy.units import units

from stormlab.render.skewt_builder import _draw_hodograph, _draw_skewt, _select_spaced_barbs


pytestmark = pytest.mark.filterwarnings(
    "ignore:.*interval_contains function was deprecated:matplotlib.MatplotlibDeprecationWarning"
)


def test_skewt_uses_skew_projection_for_isotherms():
    figure = plt.figure()
    try:
        skew = SkewT(figure, rotation=45)
        axis = skew.ax
        figure.canvas.draw()

        x_at_surface = axis.transData.transform((0, 1000))[0]
        x_aloft = axis.transData.transform((0, 300))[0]
        assert axis.name == "skewx"
        assert abs(x_at_surface - x_aloft) > 10
    finally:
        plt.close(figure)


def test_dewpoint_uses_all_available_levels_and_clips_supersaturation():
    current = {
        "surface_pressure": 1000,
        "temperature_2m": 10,
        "dew_point_2m": 14,
        "wind_speed_10m": 5,
        "wind_direction_10m": 180,
    }
    hourly = {
        "temperature_925hPa": [6],
        "dew_point_925hPa": [8],
        "temperature_850hPa": [None],
        "dew_point_850hPa": [4],
        "temperature_700hPa": [0],
        "dew_point_700hPa": [1],
        "wind_speed_925hPa": [7],
        "wind_direction_925hPa": [190],
        "wind_speed_850hPa": [9],
        "wind_direction_850hPa": [205],
        "wind_speed_700hPa": [12],
        "wind_direction_700hPa": [220],
    }
    figure = plt.figure()
    try:
        skew = SkewT(figure, rotation=45)
        _draw_skewt(skew, current, hourly, "Test", "Now")
        dewpoint_line = next(
            line for line in skew.ax.get_lines()
            if line.get_label() == "Td: Точка росы"
        )

        np.testing.assert_allclose(dewpoint_line.get_ydata(orig=False), [1000, 925, 850, 700])
        np.testing.assert_allclose(dewpoint_line.get_xdata(orig=False), [10, 6, 4, 0])
    finally:
        plt.close(figure)


def test_barb_selection_respects_minimum_vertical_pixel_spacing():
    figure = plt.figure()
    try:
        skew = SkewT(figure, rotation=45)
        skew.ax.set_ylim(1030, 200)
        figure.canvas.draw()
        pressure = np.array([1000, 975, 950, 925, 900, 850, 800, 700, 500, 300]) * units.hPa
        selected = _select_spaced_barbs(skew.ax, pressure, min_spacing_px=18)
        points = np.column_stack((np.zeros(len(pressure)), pressure.magnitude))
        y_pixels = skew.ax.transData.transform(points)[selected, 1]

        assert 0 < len(selected) < len(pressure)
        assert np.all(np.abs(np.diff(y_pixels)) >= 18)
    finally:
        plt.close(figure)


def test_hodograph_labels_have_non_overlapping_display_extents():
    u = np.array([0, 2, 5, 9, 14, 20], dtype=float)
    v = np.array([0, 5, 10, 15, 20, 25], dtype=float)
    speed = np.hypot(u, v)
    direction = np.degrees(np.arctan2(-u, -v)) % 360
    pressures = [1000, 925, 850, 700, 500, 300]
    figure, axis = plt.subplots(figsize=(4, 4), dpi=180)
    try:
        _draw_hodograph(axis, pressures, speed, direction)
        figure.canvas.draw()
        renderer = figure.canvas.get_renderer()
        labels = [text for text in axis.texts if text.get_text() in {
            "SFC", "1000", "925", "850", "700", "500", "300",
        }]
        padded_extents = [text.get_window_extent(renderer).padded(3) for text in labels]

        for index, extent in enumerate(padded_extents):
            assert not any(extent.overlaps(other) for other in padded_extents[index + 1:])
    finally:
        plt.close(figure)
