def get_regime(lat: float, month: int) -> str:
    if month in {11, 12, 1, 2, 3} and lat >= 45:
        return "cool"
    if month in {4, 10} and lat >= 55:
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
