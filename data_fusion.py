import logging

import numpy as np

logger = logging.getLogger(__name__)

FIELD_SIGMA = {
    "temperature_2m": 1.5,       # °C
    "surface_pressure": 1.0,     # гПа
    "relative_humidity_2m": 8.0, # %
    "wind_speed_10m": 1.5,       # м/с
}


def _inverse_variance_fuse(x1: float, sigma1: float, x2: float, sigma2: float) -> float:
    w1 = 1 / (sigma1 ** 2)
    w2 = 1 / (sigma2 ** 2)
    return (x1 * w1 + x2 * w2) / (w1 + w2)


def _circular_mean_direction(dir1_deg: float, weight1: float, dir2_deg: float, weight2: float) -> float:
    rad1, rad2 = np.radians(dir1_deg), np.radians(dir2_deg)
    u = -weight1 * np.sin(rad1) - weight2 * np.sin(rad2)
    v = -weight1 * np.cos(rad1) - weight2 * np.cos(rad2)
    if u == 0 and v == 0:
        return dir1_deg
    return float(np.degrees(np.arctan2(-u, -v)) % 360)


def fuse_current_weather(om_current: dict, owm_current: dict | None) -> dict:
    if not owm_current:
        return dict(om_current)

    fused = dict(om_current)

    for field, sigma in FIELD_SIGMA.items():
        om_value = om_current.get(field)
        owm_value = owm_current.get(field)

        if om_value is None:
            if owm_value is not None:
                fused[field] = owm_value
            continue
        if owm_value is None:
            continue

        fused[field] = round(_inverse_variance_fuse(om_value, sigma, owm_value, sigma), 1)

    om_dir = om_current.get("wind_direction_10m")
    owm_dir = owm_current.get("wind_direction_10m")
    om_speed = om_current.get("wind_speed_10m") or 0
    owm_speed = owm_current.get("wind_speed_10m") or 0

    if om_dir is not None and owm_dir is not None:
        fused["wind_direction_10m"] = round(
            _circular_mean_direction(om_dir, om_speed, owm_dir, owm_speed), 0
        )

    logger.info("Приземные данные слиты: Open-Meteo + OpenWeatherMap")
    return fused