import pytest

from effective_layer import (
    EFFECTIVE_CONSTANTS,
    effective_srh,
    effective_bulk_shear,
    find_effective_layer,
    stp_effective,
    scp_effective,
)
from storm_indices import calculate_stp, calculate_scp, calculate_threat_level


PIN_CONSTANTS = {
    "CAPE_MIN_LAYER": 100,
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
    "SCP_CAPE_NORM": 1000,
    "SCP_SRH_NORM": 50,
    "EBWD_LOWER": "base",
}


def test_effective_constants_pin():
    assert EFFECTIVE_CONSTANTS == PIN_CONSTANTS


def test_esrh_and_bulk_shear_pin():
    profile = {"z": [0, 3000], "u": [0, 10], "v": [10, 10]}
    assert effective_srh(profile, 0, 3000, (0, 0)) == pytest.approx(100.0, abs=1e-6)
    assert effective_bulk_shear(profile, 0, 3000) == pytest.approx(10.0, abs=1e-6)


def test_effective_srh_zero_and_constant_wind_zero_shear():
    constant_motion = {"z": [0, 3000], "u": [5, 5], "v": [5, 5]}
    assert effective_srh(constant_motion, 0, 3000, (5, 5)) == pytest.approx(0.0, abs=1e-6)
    assert effective_bulk_shear(constant_motion, 0, 3000) == pytest.approx(0.0, abs=1e-6)


def test_stp_scp_pin_values_and_limits():
    stp = stp_effective(1500, 1000, 150, 20, -50)
    scp = scp_effective(1500, 150, 20)
    assert stp == pytest.approx(1.0, abs=1e-6)
    assert scp == pytest.approx(4.5, abs=1e-6)

    assert stp_effective(1500, 1000, 150, 40, -50) == pytest.approx(1.5, abs=1e-6)
    assert scp_effective(1500, 150, 40) == pytest.approx(6.75, abs=1e-6)

    assert stp_effective(1500, 1000, 150, 10, -50) == 0.0
    assert scp_effective(1500, 150, 10) == 0.0
    assert stp_effective(1500, 2500, 150, 20, -50) == 0.0
    assert stp_effective(1500, 1000, 150, 20, -300) == 0.0


def test_wind_equal_to_bunkers_motion_zero_srh():
    profile = {"z": [0, 3000], "u": [2, 2], "v": [6, 6]}
    assert effective_srh(profile, 0, 3000, (2, 6)) == pytest.approx(0.0, abs=1e-6)


def test_missing_effective_layer_and_fixed_regression():
    assert find_effective_layer({"z": [0], "u": [0], "v": [0]}) is None

    fixed_stp = calculate_stp(1500, 150, 1000, -50, 20)
    fixed_scp = calculate_scp(1500, 150, 20, -50)
    threat = calculate_threat_level(30, 50, -5, cape=1500, cin=-50, shear_06=20, ehi=1)
    assert fixed_stp == 1.0
    assert fixed_scp == 2.25
    assert threat == 5
