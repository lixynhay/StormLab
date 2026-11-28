"""Property invariants that pin-tests cannot cover (Hypothesis)."""

from types import SimpleNamespace

import pytest
from hypothesis import given, strategies as st

from stormlab.alert_manager import CAPE_FLOOR
from stormlab.core.season_regime import get_regime, thresholds_for
from stormlab.core.storm_indices import _nd_render, calculate_stp, format_storm_text
from stormlab import rate_limiter as rl


@given(
    lat=st.floats(min_value=-90, max_value=90, allow_nan=False, allow_infinity=False),
    month=st.integers(min_value=1, max_value=12),
)
def test_season_floor_is_always_below_threshold(lat, month):
    """Floor < threshold must hold on both sides of the 45/55 degree borders."""
    regime = get_regime(lat, month)
    assert regime in ("warm", "cool")
    assert CAPE_FLOOR[regime] < thresholds_for(regime)["cape_min"]


@given(
    cape=st.floats(min_value=-100, max_value=10000, allow_nan=False, allow_infinity=False),
    srh=st.floats(min_value=-500, max_value=500, allow_nan=False, allow_infinity=False),
    lcl=st.floats(min_value=0, max_value=3000, allow_nan=False, allow_infinity=False),
    shear=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
    cin=st.floats(min_value=-1000, max_value=0, allow_nan=False, allow_infinity=False),
)
def test_fixed_stp_invariants(cape, srh, lcl, shear, cin):
    """STP is never negative, honours the zero/cap gates and cannot exceed the product bound."""
    value = calculate_stp(cape, srh, lcl, shear, cin)
    assert value is not None
    assert value >= 0
    if shear < 12.5 or cape <= 0 or srh <= 0:
        assert value == 0
    upper = max(0.0, cape / 1500.0) * 1.0 * max(0.0, srh / 150.0) * 1.5
    assert value <= upper + 0.01


@given(delta=st.integers(min_value=0, max_value=29))
def test_rate_limiter_never_allows_n_plus_one(delta):
    """A repeated call inside the cooldown window is always denied."""
    now = 1000.0
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(rl, "time", SimpleNamespace(time=lambda: now))
        rl._rate_limits.clear()
        uid, op = 987654321, "storm"
        cooldown = rl.COOLDOWNS[op]

        assert rl.check_rate_limit(uid, op)[0] is True
        now += float(delta)
        assert rl.check_rate_limit(uid, op)[0] is False
        now = 1000.0 + cooldown
        assert rl.check_rate_limit(uid, op)[0] is True


_FIELD = st.one_of(
    st.none(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.integers(min_value=-1000, max_value=1000),
    st.text(max_size=12),
)


@given(
    cape=_FIELD,
    stp=_FIELD,
    lcl=_FIELD,
    dcape=_FIELD,
    cin=_FIELD,
    interpretation=_FIELD,
)
def test_renderer_never_emits_none_nan_or_inf(cape, stp, lcl, dcape, cin, interpretation):
    """Sparse/missing fields must render as «н/д», never as literal None/nan/inf."""
    report = {
        "cape": cape,
        "stp": stp,
        "lcl": lcl,
        "dcape": dcape,
        "cin": cin,
        "dcape_interpretation": interpretation,
        "threat_level": 2,
    }
    text = format_storm_text(report, "Тест", "now")
    for token in ("None", "nan", "inf"):
        assert token not in text

    for value in (float("nan"), float("inf"), float("-inf")):
        assert _nd_render(value) == "н/д"
