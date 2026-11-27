"""Seasonal regime heuristic shared by reports, alerts and AI context.

Boundaries are intentionally coarse:
- calendar month is the UTC month, not a physical seasonal index;
- 45°/55° latitude thresholds are heuristics, not a physical model;
- April/October are transitional and treated as cool only at |lat| >= 55°;
- the southern hemisphere mirrors the cool season (May–September), so the
  threshold uses abs(lat) and the month set is inverted for lat < 0.

Floor vs threshold (alert_manager): CAPE_FLOOR is the cheap "is there any
convection at all?" early exit (warm 250, cool 100) and is always BELOW the
seasonal threshold (warm 1000, cool 200). The threshold is the real alert
condition. The cool threat-score first-ball floor is a separate constant in
core.storm_indices.calculate_threat_level (warm 250, cool 150) and never gates
an alert. Keeping all three distinct prevents cool-season CAPE 200-250 from
being silently killed by a warm floor.
"""

COOL_MONTHS_NORTH = {11, 12, 1, 2, 3}
COOL_MONTHS_SOUTH = {5, 6, 7, 8, 9}
SHOULDER_MONTHS = {4, 10}


def get_regime(lat: float, month: int) -> str:
    """Return "cool" or "warm" for a latitude (degrees, signed) and UTC month.

    Uses abs(lat) for the latitude threshold and mirrors the month set for the
    southern hemisphere; a signed latitude no longer silently means "warm".
    """
    abs_lat = abs(lat)
    if lat < 0:
        if month in COOL_MONTHS_SOUTH and abs_lat >= 45:
            return "cool"
        if month in SHOULDER_MONTHS and abs_lat >= 55:
            return "cool"
        return "warm"

    if month in COOL_MONTHS_NORTH and abs_lat >= 45:
        return "cool"
    if month in SHOULDER_MONTHS and abs_lat >= 55:
        return "cool"
    return "warm"


def thresholds_for(regime: str) -> dict:
    if regime == "cool":
        return {
            "cape_min": 200,
            "shear06_min": 20,
            "lcl_max": 2500,
            "cin_max": 100,
            "elevated": True,
            "winter": True,
        }
    if regime == "warm":
        return {
            "cape_min": 1000,
            "shear06_min": 15,
            "lcl_max": 1500,
            "cin_max": 150,
            "elevated": False,
            "winter": False,
        }
    raise ValueError(f"Unknown season regime: {regime}")


def interpret(regime: str, cape: float, shear06: float) -> list[str]:
    thresholds = thresholds_for(regime)
    if (
        regime == "cool"
        and cape >= thresholds["cape_min"]
        and shear06 >= thresholds["shear06_min"]
    ):
        return [
            "Cool-season/elevated convection: низкий CAPE значим при сильном сдвиге; "
            "проверь прокси thundersnow/snow-squall."
        ]
    return []
