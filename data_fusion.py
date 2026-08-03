"""
Слияние приземных данных Open-Meteo и OpenWeatherMap.

Метод: взвешенное среднее по обратной дисперсии (inverse-variance weighting) —
стандартный статистический способ объединения двух независимых измерений одной
и той же физической величины (BLUE — best linear unbiased estimator). Чем
меньше приписанная источнику неопределённость (σ), тем больше его вес в
итоговом значении. Это не наивное среднее арифметическое: если бы, скажем,
Open-Meteo был втрое точнее OWM по температуре, его вклад в результат был бы
пропорционально больше.

Честная оговорка: значения σ ниже — РАЗУМНЫЕ ДЕФОЛТНЫЕ ДОПУЩЕНИЯ о типичной
точности прогноза каждого источника, а не эмпирически откалиброванные на
исторических данных именно этого бота цифры. Настоящая калибровка потребовала
бы системы верификации прогнозов (сравнение прогноза с фактом за историю) —
такая система в проекте не реализована (см. список "не реализовано" в истории
проекта). Пока это лучшее доступное приближение, а не измеренная статистика.
"""

import logging

import numpy as np

logger = logging.getLogger(__name__)

# Приблизительные "типичные" стандартные отклонения ошибки для приземных
# параметров. Единицы соответствуют полям Open-Meteo/OWM после нормализации.
FIELD_SIGMA = {
    "temperature_2m": 1.5,       # °C
    "surface_pressure": 1.0,     # гПа
    "relative_humidity_2m": 8.0, # %
    "wind_speed_10m": 1.5,       # м/с
}


def _inverse_variance_fuse(x1: float, sigma1: float, x2: float, sigma2: float) -> float:
    """Взвешенное среднее по обратной дисперсии (BLUE-оценка)."""
    w1 = 1 / (sigma1 ** 2)
    w2 = 1 / (sigma2 ** 2)
    return (x1 * w1 + x2 * w2) / (w1 + w2)


def _circular_mean_direction(dir1_deg: float, weight1: float, dir2_deg: float, weight2: float) -> float:
    """
    Направление ветра — циклическая величина (0° и 360° — одно и то же),
    поэтому его нельзя усреднять напрямую (среднее 350° и 10° наивно даёт 180° —
    прямо противоположное направление). Усредняем через векторные составляющие,
    взвешивая по скорости каждого источника (чем сильнее ветер, тем увереннее
    источник в направлении).
    """
    rad1, rad2 = np.radians(dir1_deg), np.radians(dir2_deg)
    u = -weight1 * np.sin(rad1) - weight2 * np.sin(rad2)
    v = -weight1 * np.cos(rad1) - weight2 * np.cos(rad2)
    if u == 0 and v == 0:
        return dir1_deg  # оба вектора взаимно погасили друг друга — редкий случай, берём любой
    return float(np.degrees(np.arctan2(-u, -v)) % 360)


def fuse_current_weather(om_current: dict, owm_current: dict | None) -> dict:
    """
    om_current — data['current'] из OpenMeteoAPI.get_current() (обязателен).
    owm_current — нормализованный словарь из OpenWeatherMapAPI.get_current(),
    либо None, если запрос к OWM не удался или ключ не настроен.

    Точка росы (dew_point_2m), погодный код (weather_code) и облачность НЕ
    участвуют в слиянии и всегда берутся из Open-Meteo: OpenWeatherMap на
    бесплатном тарифе не отдаёт точку росы напрямую, а коды погодных условий
    у источников — разные несовместимые шкалы.
    """
    if not owm_current:
        return dict(om_current)  # OWM недоступен — работаем только на Open-Meteo, как раньше

    fused = dict(om_current)

    for field, sigma in FIELD_SIGMA.items():
        om_value = om_current.get(field)
        owm_value = owm_current.get(field)

        if om_value is None:
            if owm_value is not None:
                fused[field] = owm_value
            continue
        if owm_value is None:
            continue  # om_value уже в fused по умолчанию

        fused[field] = round(_inverse_variance_fuse(om_value, sigma, owm_value, sigma), 1)

    # Направление ветра — отдельно от остальных полей (циклическая величина)
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