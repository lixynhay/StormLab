import pytest

from effective_layer import (
    EFFECTIVE_CONSTANTS,
    effective_srh,
    effective_bulk_shear,
    find_effective_layer,
    most_unstable_el_height,
    stp_effective,
    scp_effective,
)
from storm_indices import (
    calculate_hodograph_shear_srh,
    calculate_stp,
    scp_fixed_local,
    calculate_threat_level,
)


PIN_CONSTANTS = {
    "CAPE_MIN_LAYER": 100,
    "CIN_MIN_LAYER": -250,
    "LAYER_DEPTH_MIN": 50,
    "ESRH_TOP_CLIP": 10000,
    "STP_CAPE_NORM": 1500,
    "STP_LCL_NUM": 2000,
    "STP_LCL_DEN": 1000,
    "STP_LCL_CAP": (0, 1),
    "STP_SRH_NORM": 150,
    "STP_SHEAR_NORM": 20,
    "STP_CIN_NUM": 200,
    "STP_CIN_DEN": 150,
    "STP_CIN_CAP": (0, 1),
    "STP_CIN_ZERO": -200,
    "EBWD_MIN": 12.5,
    "EBWD_MAX": 30,
    "EBWD_EL_FRACTION": 0.5,
    "SCP_CAPE_NORM": 1000,
    "SCP_SRH_NORM": 50,
    "SCP_EBWD_MIN": 10,
    "SCP_EBWD_MAX": 20,
    "SCP_CIN_THRESHOLD": -40,
    "EBWD_LOWER": "base",
}


def test_effective_constants_pin():
    assert EFFECTIVE_CONSTANTS == PIN_CONSTANTS


def test_esrh_and_bulk_shear_pin():
    profile = {"z": [0, 3000], "u": [0, 10], "v": [10, 10]}
    assert effective_srh(profile, 0, 3000, (0, 0)) == pytest.approx(100.0, abs=1e-6)
    # Unity pin: EL = 6000 m -> EBWD is measured at 0.5 * EL = 3000 m.
    assert effective_bulk_shear(profile, 0, 6000) == pytest.approx(10.0, abs=1e-6)


def test_effective_srh_zero_and_constant_wind_zero_shear():
    constant_motion = {"z": [0, 3000], "u": [5, 5], "v": [5, 5]}
    assert effective_srh(constant_motion, 0, 3000, (5, 5)) == pytest.approx(0.0, abs=1e-6)
    assert effective_bulk_shear(constant_motion, 0, 6000) == pytest.approx(0.0, abs=1e-6)


def test_stp_scp_pin_values_and_limits():
    # Unity pins: STP_eff = 1.0 for ml inputs, SCP_eff = 4.5 for muCIN = -40.
    stp = stp_effective(1500, 1000, 150, 20, -50)
    scp = scp_effective(1500, 150, 20, -40)
    assert stp == pytest.approx(1.0, abs=1e-6)
    assert scp == pytest.approx(4.5, abs=1e-6)

    # Effective STP: EBWD > 30 m/s -> cap 1.5.
    assert stp_effective(1500, 1000, 150, 40, -50) == pytest.approx(1.5, abs=1e-6)
    # SCP: EBWD > 20 m/s -> 1.0, so 40 m/s gives the same 4.5 as 20 m/s.
    assert scp_effective(1500, 150, 40, -40) == pytest.approx(4.5, abs=1e-6)

    assert stp_effective(1500, 1000, 150, 10, -50) == 0.0
    assert scp_effective(1500, 150, 9.9, -40) == 0.0
    assert scp_effective(1500, 150, 10, -40) == pytest.approx(2.25, abs=1e-6)
    assert stp_effective(1500, 2500, 150, 20, -50) == 0.0
    assert stp_effective(1500, 1000, 150, 20, -300) == 0.0


def test_scp_effective_cin_halves_relative_to_minus_40():
    at_40 = scp_effective(1500, 150, 20, -40)
    at_80 = scp_effective(1500, 150, 20, -80)
    assert at_80 == pytest.approx(at_40 / 2.0, abs=1e-9)
    assert scp_effective(1500, 150, 20, 0) == pytest.approx(at_40, abs=1e-9)


def test_stp_effective_zero_when_inflow_base_above_ground():
    # SPC: "the entire index is set to 0.0 when the effective inflow base is
    # above the ground." https://www.spc.noaa.gov/exper/mesoanalysis/help/begin.html
    assert stp_effective(
        1500, 1000, 150, 20, -50, base_height_m=500.0, surface_height_m=0.0
    ) == 0.0
    assert stp_effective(
        1500, 1000, 150, 20, -50, base_height_m=0.0, surface_height_m=0.0
    ) == pytest.approx(1.0, abs=1e-6)


def test_wind_equal_to_bunkers_motion_zero_srh():
    profile = {"z": [0, 3000], "u": [2, 2], "v": [6, 6]}
    assert effective_srh(profile, 0, 3000, (2, 6)) == pytest.approx(0.0, abs=1e-6)


def test_ebwd_uses_half_of_el_not_full_el():
    # EL = 8000 m -> EBWD must be |V(4000) - V(base)|, not |V(8000) - V(base)|.
    profile = {"z": [0, 4000, 8000], "u": [0, 10, 20], "v": [0, 0, 0]}
    assert effective_bulk_shear(profile, 0, 8000) == pytest.approx(10.0, abs=1e-6)
    assert effective_bulk_shear(profile, 0, 8000) != pytest.approx(20.0, abs=1e-6)


def test_effective_layer_none_when_all_parcels_inhibited():
    # Strongly stable profile: parcel CAPE < 100 everywhere, CIN < -250 at the
    # bottom -> no effective inflow layer, caller falls back to "н/д".
    stable = {
        "z": [0, 500, 1000, 1500, 3000, 5500],
        "p": [1000, 950, 900, 850, 700, 500],
        "T": [0, 5, 10, 15, 20, 25],
        "Td": [-1, 4, 9, 14, 19, 24],
        "u": [0, 0, 0, 0, 0, 0],
        "v": [0, 0, 0, 0, 0, 0],
    }
    assert find_effective_layer(stable) is None
    assert find_effective_layer({"z": [0], "u": [0], "v": [0]}) is None


def test_effective_layer_found_on_unstable_profile():
    unstable = {
        "z": [0, 500, 1000, 1500, 3000, 5500, 9000],
        "p": [1000, 950, 900, 850, 700, 500, 300],
        "T": [30, 25, 20, 15, 5, -15, -45],
        "Td": [23, 20, 15, 10, -5, -30, -60],
        "u": [0, 2, 4, 6, 12, 20, 30],
        "v": [0, 0, 0, 0, 0, 0, 0],
    }
    layer = find_effective_layer(unstable)
    assert layer is not None
    base, top = layer
    assert base == pytest.approx(0.0, abs=1e-6)
    assert top > base
    assert most_unstable_el_height(unstable) is not None


def test_missing_effective_layer_and_fixed_regression():
    assert find_effective_layer({"z": [0], "u": [0], "v": [0]}) is None

    # Deliberate SPC correction (fixed-layer STP): sbCAPE, sbLCL, SRH 0-1 km,
    # 6BWD; no CIN term and 6BWD < 12.5 m/s -> 0.
    # https://www.spc.noaa.gov/exper/mesoanalysis/help/begin.html
    fixed_stp = calculate_stp(1500, 150, 1000, 20, -50)
    fixed_scp = scp_fixed_local(1500, 150, 20, -50)
    threat = calculate_threat_level(30, 50, -5, cape=1500, cin=-50, shear_06=20, ehi=1)
    assert fixed_stp == 1.0
    assert fixed_scp == 2.25
    assert threat == 5


def test_fixed_stp_has_no_cin_term():
    # sbCIN = -300 vs -50 must produce the SAME fixed STP.
    assert calculate_stp(1500, 150, 1000, 20, -300) == calculate_stp(
        1500, 150, 1000, 20, -50
    )


def test_fixed_stp_zero_below_12_5_bwd6():
    assert calculate_stp(1500, 150, 1000, 10, -50) == 0.0


def test_fixed_stp_uses_0_1_km_srh_not_0_3_km():
    current = {
        "surface_pressure": 1000,
        "wind_speed_10m": 10,
        "wind_direction_10m": 180,
    }
    hourly = {
        "wind_speed_925hPa": [15],
        "wind_direction_925hPa": [200],
        "wind_speed_850hPa": [20],
        "wind_direction_850hPa": [220],
        "wind_speed_700hPa": [25],
        "wind_direction_700hPa": [240],
        "wind_speed_500hPa": [30],
        "wind_direction_500hPa": [260],
        "wind_speed_300hPa": [40],
        "wind_direction_300hPa": [270],
    }
    hodograph = calculate_hodograph_shear_srh(current, hourly, [1000, 925, 850, 700, 500, 300])

    assert "srh_0_1" in hodograph
    assert hodograph["srh_0_1"] != hodograph["srh"]

    srh_0_1 = hodograph["srh_0_1"]
    srh_0_3 = hodograph["srh"]
    expected_0_1 = round(1.0 * 1.0 * (srh_0_1 / 150.0) * (20.0 / 20.0), 2)

    assert calculate_stp(1500, srh_0_1, 1000, 20) == expected_0_1
    assert calculate_stp(1500, srh_0_1, 1000, 20) != calculate_stp(1500, srh_0_3, 1000, 20)
