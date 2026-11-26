from core.season_regime import get_regime, interpret, thresholds_for
from core.storm_indices import calculate_threat_level


def test_get_regime_by_latitude_and_month():
    assert get_regime(56, 1) == "cool"
    assert get_regime(56, 7) == "warm"
    assert get_regime(60, 4) == "cool"
    assert get_regime(40, 1) == "warm"


def test_regime_thresholds_differ():
    assert thresholds_for("cool") != thresholds_for("warm")


def test_cool_season_thresholds_raise_threat_for_low_cape_strong_shear():
    profile = {"cape": 300, "shear_06": 25}

    cool_threat = calculate_threat_level(
        0, 0, 0, **profile, cin=0, ehi=0, regime="cool"
    )
    warm_threat = calculate_threat_level(
        0, 0, 0, **profile, cin=0, ehi=0, regime="warm"
    )

    assert cool_threat > warm_threat
    assert warm_threat == 1


def test_interpret_identifies_cool_season_convection():
    assert interpret("cool", 300, 25) == [
        "Cool-season/elevated convection: низкий CAPE значим при сильном сдвиге; "
        "проверь прокси thundersnow/snow-squall."
    ]
    assert interpret("warm", 300, 25) == []
