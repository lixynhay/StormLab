import numpy as np
import pytest
from metpy.units import units
import metpy.calc as mpcalc

from stormlab.core.storm_indices import (
    PRESSURE_LEVELS,
    build_storm_report,
    calculate_brn,
    calculate_cape_real,
    calculate_ehi,
    calculate_hodograph_shear_srh,
    calculate_lifted_index_metpy,
    calculate_mlcape_real,
    calculate_mucape_real,
    calculate_showalter_index,
    calculate_sweat_index,
    calculate_thunderstorm_indices,
)


ABS_TOL = 1e-6


def test_total_totals_formula_pin():
    pressure = [850, 700, 500]
    temperature = [20, 5, -10]
    dewpoint = [10, 0, -20]

    indices = calculate_thunderstorm_indices(pressure, temperature, dewpoint)

    assert indices["total_totals"] == pytest.approx(50.0, abs=ABS_TOL)


def test_k_index_formula_pin():
    pressure = [850, 700, 500]
    temperature = [20, 5, -10]
    dewpoint = [10, 0, -20]

    indices = calculate_thunderstorm_indices(pressure, temperature, dewpoint)

    assert indices["k_index"] == pytest.approx(35.0, abs=ABS_TOL)


def test_lifted_index_formula_pin():
    pressure = [1000, 925, 850, 700, 500, 300]
    temperature = [25, 19, 13, -2, -23, -45]
    dewpoint = [20, 16, 10, -5, -30, -55]

    assert calculate_lifted_index_metpy(pressure, temperature, dewpoint) == pytest.approx(
        -17.0, abs=ABS_TOL
    )


def test_showalter_formula_pin_uses_850_hpa_parcel():
    pressure = [1000, 925, 850, 700, 500, 300]
    temperature = [25, 19, 13, -2, -23, -45]
    dewpoint = [20, 16, 10, -5, -30, -55]

    assert calculate_showalter_index(pressure, temperature, dewpoint) == pytest.approx(
        -10.1, abs=ABS_TOL
    )


def test_sweat_formula_matches_current_direction_and_speed_gates():
    td850 = 10
    total_totals = 55
    wind_speed_850 = 20
    wind_speed_500 = 20
    wind_dir_850 = 180
    wind_dir_500 = 270

    assert 12 * td850 == 120
    assert 20 * (total_totals - 49) == 120
    assert wind_speed_850 * 1.94384 == pytest.approx(38.8768, abs=ABS_TOL)
    assert 125 * (np.sin(np.radians(wind_dir_500 - wind_dir_850)) + 0.2) == pytest.approx(
        150.0, abs=ABS_TOL
    )
    assert 120 + 120 + 2 * 38.8768 + 38.8768 + 150 == pytest.approx(
        506.6304, abs=ABS_TOL
    )
    assert calculate_sweat_index(
        td850, total_totals, wind_speed_850, wind_speed_500,
        wind_dir_850, wind_dir_500,
    ) == pytest.approx(507.0, abs=ABS_TOL)
    assert 120 + 120 + 2 * 9.7192 + 9.7192 == pytest.approx(269.1576, abs=ABS_TOL)
    assert calculate_sweat_index(10, 55, 5, 5, 180, 270) == pytest.approx(
        269.0, abs=ABS_TOL
    )


def test_brn_formula_pin():
    assert calculate_brn(1500, 20) == pytest.approx(7.5, abs=ABS_TOL)


def test_ehi_formula_pin():
    assert calculate_ehi(300, 200) == pytest.approx(0.38, abs=ABS_TOL)


def _wind_speed_direction(u, v):
    speed = np.hypot(u, v)
    direction = np.degrees(np.arctan2(-u, -v)) % 360
    return speed, direction


def _wind_inputs(u_values, v_values):
    current_speed, current_direction = _wind_speed_direction(u_values[0], v_values[0])
    current = {
        "surface_pressure": 1000,
        "wind_speed_10m": float(current_speed),
        "wind_direction_10m": float(current_direction),
    }
    hourly = {}
    for level, u, v in zip(PRESSURE_LEVELS, u_values, v_values):
        speed, direction = _wind_speed_direction(u, v)
        hourly[f"wind_speed_{level}hPa"] = [float(speed)]
        hourly[f"wind_direction_{level}hPa"] = [float(direction)]
    return current, hourly


def test_bunkers_constant_wind_falls_back_to_mean_and_srh_is_zero():
    u_values = [4, 4, 4]
    v_values = [3, 3, 3]
    current, hourly = _wind_inputs(u_values, v_values)

    result = calculate_hodograph_shear_srh(current, hourly, PRESSURE_LEVELS[:3])

    assert result["storm_motion_u"] == pytest.approx(4.0, abs=ABS_TOL)
    assert result["storm_motion_v"] == pytest.approx(3.0, abs=ABS_TOL)
    assert result["srh"] == pytest.approx(0.0, abs=ABS_TOL)


def test_bunkers_veering_profile_right_mover_is_right_of_shear():
    u_values = [0, 2, 5, 9, 14, 20]
    v_values = [0, 5, 10, 15, 20, 25]
    current, hourly = _wind_inputs(u_values, v_values)

    result = calculate_hodograph_shear_srh(current, hourly, PRESSURE_LEVELS)
    mean_u, mean_v = float(np.mean(u_values)), float(np.mean(v_values))
    shear_u, shear_v = u_values[-1] - u_values[0], v_values[-1] - v_values[0]
    motion_u = result["storm_motion_u"] - mean_u
    motion_v = result["storm_motion_v"] - mean_v

    assert result["srh_method"] == "Bunkers (right-mover)"
    assert shear_u * motion_v - shear_v * motion_u < 0


def test_parcel_levels_and_cape_cin_invariants():
    pressure = [1000, 925, 850, 700, 500, 300, 200, 100]
    temperature = [25, 19, 13, -2, -23, -45, -50, -45]
    dewpoint = [20, 16, 10, -5, -30, -55, -60, -65]

    p = np.asarray(pressure) * units.hPa
    t = np.asarray(temperature) * units.degC
    td = np.asarray(dewpoint) * units.degC
    parcel = mpcalc.parcel_profile(p, t[0], td[0])
    lcl_p, _ = mpcalc.lcl(p[0], t[0], td[0])
    lfc_p, _ = mpcalc.lfc(p, t, td, parcel_temperature_profile=parcel)
    el_p, _ = mpcalc.el(p, t, td, parcel)
    cape, cin = mpcalc.surface_based_cape_cin(p, t, td)

    lcl_height = mpcalc.pressure_to_height_std(lcl_p).magnitude
    lfc_height = mpcalc.pressure_to_height_std(lfc_p).magnitude
    el_height = mpcalc.pressure_to_height_std(el_p).magnitude
    assert lcl_height <= lfc_height <= el_height
    assert float(cape.to("J/kg").magnitude) >= 0
    assert float(cin.to("J/kg").magnitude) <= 0


def test_mu_to_ml_to_sb_fallback_uses_first_valid_mu_parcel():
    pressure = [1000, 925, 850, 700, 500, 300]
    temperature = [27, 21, 15, 2, -18, -42]
    dewpoint = [21, 16, 10, -2, -28, -55]

    mucape = calculate_mucape_real(pressure, temperature, dewpoint)
    mlcape = calculate_mlcape_real(pressure, temperature, dewpoint)
    sbcape = calculate_cape_real(pressure, temperature, dewpoint)
    assert mucape is not None

    current, hourly = _wind_inputs([2, 3, 4, 6, 8, 10], [2, 4, 7, 10, 13, 16])
    current.update({"temperature_2m": temperature[0], "dew_point_2m": dewpoint[0]})
    for level, temp, dew in zip(pressure, temperature, dewpoint):
        hourly[f"temperature_{level}hPa"] = [temp]
        hourly[f"dew_point_{level}hPa"] = [dew]

    report = build_storm_report({"current": current}, {"hourly": hourly})

    assert report["cape_type"] == "MU"
    assert report["cape"] == mucape[0]
    assert mlcape is None or report["cape_type"] != "ML"
    assert sbcape is not None


def test_mu_and_ml_unavailable_falls_back_to_sb():
    pressure = [1000, 500]
    temperature = [25, -20]
    dewpoint = [20, -30]

    assert calculate_mucape_real(pressure, temperature, dewpoint) is None
    assert calculate_mlcape_real(pressure, temperature, dewpoint) is None
    sbcape = calculate_cape_real(pressure, temperature, dewpoint)
    assert sbcape is not None

    current, hourly = _wind_inputs([4, 4, 4], [3, 3, 3])
    current.update({"temperature_2m": temperature[0], "dew_point_2m": dewpoint[0]})
    hourly["temperature_500hPa"] = [temperature[1]]
    hourly["dew_point_500hPa"] = [dewpoint[1]]

    report = build_storm_report({"current": current}, {"hourly": hourly})

    assert report["cape_type"] == "SB"
    assert report["cape"] == sbcape[0]
