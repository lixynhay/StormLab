"""Discriminating pin: fixed-layer STP must use surface-based LCL, not report LCL."""

from stormlab.core import storm_indices as si
from tests.test_storm_indices_core import _wind_inputs


def test_fixed_stp_uses_surface_based_lcl_pin(monkeypatch):
    pressure = [1000, 925, 850, 700, 500, 300]
    temperature = [27, 21, 15, 2, -18, -42]
    dewpoint = [21, 16, 10, -2, -28, -55]

    # Force report["lcl"] (the MU/ML parcel) to differ from the surface parcel.
    # With the old call site the STP term used this LCL and the test fails.
    monkeypatch.setattr(
        si, "calculate_mucape_real",
        lambda p, t, td: (1500.0, -50.0, 800.0, "MU"),
    )

    real_calculate_stp = si.calculate_stp
    captured = {}

    def spy(cape, srh, lcl_height_m, shear_06, cin=None):
        captured["lcl_height_m"] = lcl_height_m
        return real_calculate_stp(cape, srh, lcl_height_m, shear_06, cin)

    monkeypatch.setattr(si, "calculate_stp", spy)

    current, hourly = _wind_inputs([2, 3, 4, 6, 8, 10], [2, 4, 7, 10, 13, 16])
    current.update({"temperature_2m": temperature[0], "dew_point_2m": dewpoint[0]})
    for level, temp, dew in zip(pressure, temperature, dewpoint):
        hourly[f"temperature_{level}hPa"] = [temp]
        hourly[f"dew_point_{level}hPa"] = [dew]

    report = si.build_storm_report({"current": current}, {"hourly": hourly})

    sb_cape, sb_cin, sb_lcl_p, _ = si.calculate_cape_real(pressure, temperature, dewpoint)
    expected_sb_lcl_m = si.lcl_pressure_to_height(sb_lcl_p)

    assert report["lcl_height_m"] != expected_sb_lcl_m  # pin is discriminating
    assert captured["lcl_height_m"] == expected_sb_lcl_m
