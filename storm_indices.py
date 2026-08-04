import logging
import numpy as np
import metpy.calc as mpcalc
from metpy.units import units

logger = logging.getLogger(__name__)

PRESSURE_LEVELS = [1000, 925, 850, 700, 500, 300]
SKEWT_LEVELS = [1000, 975, 950, 925, 900, 850, 800, 700, 600, 500, 400, 300]

def interpret_cin(cin_value):
    cin_abs = abs(cin_value) if cin_value is not None else 0
    if cin_abs < 25:
        return " Крышка отсутствует — свободная конвекция"
    elif cin_abs < 50:
        return "🟡 Слабая крышка"
    elif cin_abs < 200:
        return "🟠 Умеренная крышка — нужен триггер (фронт, орография)"
    else:
        return "🔴 Сильная крышка — грозы маловероятны"


def interpret_stp(stp):
    if stp is None:
        return "н/д"
    if stp < 0.5:
        return "🟢 Торнадо маловероятно"
    elif stp < 1.0:
        return "🟡 Возможны слабые торнадо (EF0-EF1)"
    elif stp < 2.0:
        return "🟠 Значительный риск (EF1-EF2)"
    elif stp < 4.0:
        return "🔴 Высокий риск сильных торнадо (EF2-EF3)"
    else:
        return "⚫ Экстремальный риск (EF3+)"


def interpret_scp(scp):
    if scp is None:
        return "н/д"
    if scp < 1:
        return "🟢 Суперячейки маловероятны"
    elif scp < 4:
        return "🟡 Возможны суперячейки"
    elif scp < 8:
        return " Высокий потенциал суперячеек"
    else:
        return "🔴 Экстремальный потенциал суперячеек"


def interpret_dcape(dcape):
    if dcape is None:
        return "н/д"
    if dcape < 500:
        return " Слабые нисходящие потоки"
    elif dcape < 1000:
        return "🟡 Умеренные нисходящие потоки"
    elif dcape < 1500:
        return "🟠 Риск сильных шквалов"
    else:
        return "🔴 Высокий риск микропорывов (downburst)"


def interpret_mcs_maintenance(mcsm):
    if mcsm is None:
        return "н/д"
    if not mcsm["maintained"]:
        return f"🟢 MCS не будет поддерживаться (score {mcsm['score']}/4)"
    return f"🔴 MCS устойчив (score {mcsm['score']}/4): {', '.join(mcsm['reasons'])}"


def interpret_shear(bulk_shear_06):
    if bulk_shear_06 is None or bulk_shear_06 == 0:
        return "Нет данных о ветре на уровнях"
    elif bulk_shear_06 < 10:
        return " Слабый (одиночные ячейки)"
    elif bulk_shear_06 < 20:
        return "🟡 Умеренный (мультиячейковые грозы)"
    elif bulk_shear_06 < 30:
        return "🟠 Сильный (суперячейки)"
    else:
        return "🔴 Очень сильный (суперячейки / шквалистые линии)"


def interpret_k_index(k):
    if k < 15:
        return "🟢 Грозы крайне маловероятны"
    elif k < 20:
        return "🟡 Грозы маловероятны"
    elif k < 25:
        return "🟠 Изолированные одиночные грозы"
    elif k < 30:
        return "🔴 Многоячейковые грозы (60-70%)"
    elif k < 35:
        return "🟣 Массовые грозы (80-90%)"
    else:
        return "⚫ Экстремальная конвекция!"


def interpret_tt(tt):
    if tt < 44:
        return " Нет конвекции"
    elif tt < 47:
        return "🟡 Слабая конвекция"
    elif tt < 50:
        return "🟠 Возможны грозы"
    elif tt < 53:
        return "🔴 Вероятны грозы"
    else:
        return " Сильные грозы вероятны"


def interpret_li(li):
    if li is None:
        return "Нет данных"
    if li > 2:
        return "🟢 Стабильно"
    elif li > 0:
        return "🟡 Слабая нестабильность"
    elif li > -3:
        return " Умеренная нестабильность"
    elif li > -6:
        return " Сильная нестабильность"
    else:
        return "⚫ Экстремальная нестабильность"


def interpret_si(si):
    if si is None:
        return "Нет данных"
    if si > 3:
        return "🟢 Грозы маловероятны"
    elif si > 1:
        return "🟡 Возможны ливни"
    elif si > -2:
        return " Возможны грозы"
    elif si > -6:
        return "🔴 Вероятны сильные грозы"
    else:
        return "⚫ Вероятны сильные грозы/торнадо"


def interpret_sweat(sweat):
    if sweat is None:
        return "Нет данных"
    if sweat < 300:
        return "🟢 Низкая вероятность опасных явлений"
    elif sweat < 400:
        return "🟡 Умеренная вероятность"
    elif sweat < 500:
        return "🟠 Высокая вероятность (сильные грозы)"
    else:
        return "🔴 Очень высокая (возможны торнадо)"


def interpret_ehi(ehi):
    if ehi is None:
        return "н/д (нет данных о сдвиге)"
    if ehi < 1:
        return " Низкий потенциал суперячеек"
    elif ehi < 2:
        return " Умеренный потенциал"
    elif ehi < 4:
        return "🟠 Значительный потенциал (сильные торнадо)"
    else:
        return "🔴 Экстремальный потенциал"


def interpret_brn(brn):
    if brn is None:
        return "н/д (нет данных о сдвиге)"
    if brn < 10:
        return "🟣 Очень сильный сдвиг относительно CAPE (риск срыва конвекции)"
    elif brn <= 45:
        return "🟢 Благоприятно для суперячеек"
    else:
        return " Слабый сдвиг относительно CAPE (мультиячейковые грозы)"

def calculate_stp(cape, srh, lcl_height_m, cin, shear_06):
    try:
        if cape is None or srh is None or shear_06 is None:
            return None
        if cape <= 0 or shear_06 <= 0:
            return 0.0
        cape_term = max(0, cape / 1500)
        if lcl_height_m is None or lcl_height_m < 1000:
            lcl_term = 1.0
        elif lcl_height_m > 2000:
            lcl_term = 0.0
        else:
            lcl_term = (2000 - lcl_height_m) / 1000
        srh_term = max(0, srh / 150)
        shear_term = min(shear_06 / 20, 1.5) if shear_06 < 30 else 1.5
        cin_abs = abs(cin) if cin else 0
        if cin_abs < 50:
            cin_term = 1.0
        elif cin_abs > 200:
            cin_term = 0.0
        else:
            cin_term = (200 - cin_abs) / 150
        return round(cape_term * lcl_term * srh_term * shear_term * cin_term, 2)
    except Exception:
        return None


def calculate_scp(cape, srh, shear_06, cin):
    try:
        if cape is None or srh is None or shear_06 is None:
            return None
        if cape <= 0 or shear_06 <= 0:
            return 0.0
        cape_term = max(0, cape / 1000)
        srh_term = max(0, srh / 100)
        shear_term = min(shear_06 / 20, 1.5) if shear_06 < 30 else 1.5
        cin_abs = abs(cin) if cin else 0
        if cin_abs < 50:
            cin_term = 1.0
        else:
            cin_term = max(0, (200 - cin_abs) / 150)
        return round(cape_term * srh_term * shear_term * cin_term, 2)
    except Exception:
        return None


def calculate_dcape(pressure_profile, temperature_profile, dewpoint_profile):
    try:
        if len(pressure_profile) < 3:
            return None
        p = np.array(pressure_profile) * units.hPa
        T = np.array(temperature_profile) * units.degC
        Td = np.array(dewpoint_profile) * units.degC

        try:
            dcape, _ = mpcalc.downdraft_cape_cin(p, T, Td)
            if dcape is not None:
                return round(float(dcape.to("J/kg").magnitude), 0)
        except AttributeError:
            pass
        except Exception:
            pass

        theta_e_list = []
        for i in range(len(p)):
            if 500 <= p[i].magnitude <= 900:
                try:
                    te = mpcalc.equivalent_potential_temperature(p[i], T[i], Td[i])
                    theta_e_list.append((i, te.magnitude))
                except Exception:
                    continue

        if not theta_e_list:
            return None

        min_idx, _ = min(theta_e_list, key=lambda x: x[1])
        theta_parcel = mpcalc.potential_temperature(p[min_idx], T[min_idx])

        Rd = 287.05
        g = 9.81
        dcape = 0
        for i in range(min_idx + 1, len(p)):
            p_i = p[i]
            T_env = T[i]
            T_parcel = theta_parcel * (p_i / (1000 * units.hPa)) ** (Rd / 1004.0)
            if T_parcel < T_env:
                buoyancy = g * (T_env - T_parcel).magnitude / (T_env.magnitude + 273.15)
                p_prev = p[i - 1]
                dz = (Rd * (T_env.magnitude + 273.15) / g) * np.log(p_prev.magnitude / p_i.magnitude)
                dcape += buoyancy * dz

        return round(dcape, 0) if dcape > 0 else None
    except Exception as e:
        logger.warning(f"DCAPE calculation failed: {e}")
        return None


def calculate_mcs_maintenance(cape, shear_06, mid_layer_spread):
    try:
        if cape is None or shear_06 is None:
            return None
        score = 0
        reasons = []
        if cape >= 400:
            score += 1
            reasons.append("CAPE≥400")
        if shear_06 >= 20:
            score += 1
            reasons.append("shear≥20м/с")
        if mid_layer_spread is not None and mid_layer_spread <= 6:
            score += 1
            reasons.append("влажный средний слой")
        if cape >= 1000 and shear_06 >= 15:
            score += 1
            reasons.append("CAPE+shear")
        return {"score": score, "maintained": score >= 3, "reasons": reasons}
    except Exception:
        return None


def lcl_pressure_to_height(lcl_pressure_hpa):
    try:
        if lcl_pressure_hpa is None or lcl_pressure_hpa <= 0:
            return None
        return round((1 - (lcl_pressure_hpa / 1013.25) ** 0.190284) * 44330, 0)
    except Exception:
        return None


def calculate_cape_real(pressure_profile, temperature_profile, dewpoint_profile):
    try:
        p = np.array(pressure_profile) * units.hPa
        T = np.array(temperature_profile) * units.degC
        Td = np.array(dewpoint_profile) * units.degC
        lcl_p, _ = mpcalc.lcl(p[0], T[0], Td[0])
        cape, cin = mpcalc.surface_based_cape_cin(p, T, Td)
        cape_val = cape.magnitude if cape is not None else 0
        cin_val = cin.magnitude if cin is not None else 0
        lcl_val = lcl_p.magnitude if lcl_p is not None else 0
        return round(cape_val, 0), round(cin_val, 0), round(lcl_val, 0), "SB"
    except Exception as e:
        logger.error(f"CAPE failed: {type(e).__name__}: {e}", exc_info=True)
        return None, None, None, "SB"


def calculate_mlcape_real(pressure_profile, temperature_profile, dewpoint_profile):
    try:
        p = np.array(pressure_profile) * units.hPa
        T = np.array(temperature_profile) * units.degC
        Td = np.array(dewpoint_profile) * units.degC
        if len(p) < 3:
            return None
        cape, cin = mpcalc.mixed_layer_cape_cin(p, T, Td, depth=100 * units.hPa)
        lcl_p, _ = mpcalc.lcl(p[0], T[0], Td[0])
        cape_val = cape.magnitude if cape is not None else 0
        cin_val = cin.magnitude if cin is not None else 0
        lcl_val = lcl_p.magnitude if lcl_p is not None else 0
        if cape_val > 0:
            return round(cape_val, 0), round(cin_val, 0), round(lcl_val, 0), "ML"
        return None
    except Exception as e:
        logger.warning(f"MLCAPE failed: {e}")
        return None


def calculate_mucape_real(pressure_profile, temperature_profile, dewpoint_profile):
    try:
        p = np.array(pressure_profile) * units.hPa
        T = np.array(temperature_profile) * units.degC
        Td = np.array(dewpoint_profile) * units.degC
        if len(p) < 3:
            return None
        cape, cin = mpcalc.most_unstable_cape_cin(p, T, Td, depth=300 * units.hPa)
        lcl_p, _ = mpcalc.lcl(p[0], T[0], Td[0])
        cape_val = cape.magnitude if cape is not None else 0
        cin_val = cin.magnitude if cin is not None else 0
        lcl_val = lcl_p.magnitude if lcl_p is not None else 0
        if cape_val > 0:
            return round(cape_val, 0), round(cin_val, 0), round(lcl_val, 0), "MU"
        return None
    except Exception as e:
        logger.warning(f"MUCAPE failed: {e}")
        return None


def calculate_lifted_index_metpy(pressure_profile, temperature_profile, dewpoint_profile):
    try:
        p = np.array(pressure_profile) * units.hPa
        T = np.array(temperature_profile) * units.degC
        Td = np.array(dewpoint_profile) * units.degC
        idx_500 = int(np.argmin(np.abs(p.magnitude - 500)))
        parcel_prof = mpcalc.parcel_profile(p[:idx_500 + 1], T[0], Td[0])
        li = (T[idx_500] - parcel_prof[-1]).magnitude
        return max(-15, min(20, li))
    except Exception as e:
        logger.warning(f"Lifted Index (MetPy) failed: {e}")
        return None


def validate_profile_physical(pressure_profile, temperature_profile):
    if len(pressure_profile) < 2:
        return False
    for i in range(len(pressure_profile) - 1):
        if pressure_profile[i + 1] >= pressure_profile[i]:
            logger.warning(f"Non-monotonic pressure at index {i}")
            return False
    return True


def calculate_thunderstorm_indices(pressure_levels, temperatures, dewpoints):
    result = {}
    try:
        p = np.array(pressure_levels)
        T = np.array(temperatures)
        Td = np.array(dewpoints)

        def find_level(target):
            return int(np.argmin(np.abs(p - target)))

        idx_850, idx_700, idx_500 = find_level(850), find_level(700), find_level(500)
        T850, Td850 = T[idx_850], Td[idx_850]
        T700, Td700 = T[idx_700], Td[idx_700]
        T500 = T[idx_500]

        k_index = (T850 - T500) + Td850 - (T700 - Td700)
        result["k_index"] = round(k_index, 1)
        result["k_interpretation"] = interpret_k_index(k_index)

        total_totals = (T850 + Td850) - 2 * T500
        result["total_totals"] = round(total_totals, 1)
        result["tt_interpretation"] = interpret_tt(total_totals)
        result["cross_totals"] = round(Td850 - T500, 1)
        result["vertical_totals"] = round(T850 - T500, 1)

        try:
            surface_temp, surface_td = T[0], Td[0]
            lcl_pressure = 1000 - ((surface_temp - surface_td) / 8) * 100
            if lcl_pressure > 500:
                temp_at_lcl = surface_temp - (1000 - lcl_pressure) / 100 * 9.8
                temp_parcel_500 = temp_at_lcl - (lcl_pressure - 500) / 100 * 6
            else:
                temp_parcel_500 = surface_temp - (1000 - 500) / 100 * 9.8
            lifted_index = max(-15, min(20, T500 - temp_parcel_500))
            result["lifted_index"] = round(lifted_index, 1)
            result["li_interpretation"] = interpret_li(lifted_index)
        except Exception:
            result["lifted_index"] = None
            result["li_interpretation"] = "Не удалось рассчитать"

        try:
            mid_layer_spread = np.mean([T[i] - Td[i] for i in range(len(T)) if 500 <= p[i] <= 700])
            result["mid_layer_spread"] = round(mid_layer_spread, 1)
        except Exception:
            result["mid_layer_spread"] = None

        li_for_calc = result.get("lifted_index", 0) or 0
        result["threat_level"] = calculate_threat_level(k_index, total_totals, li_for_calc)

    except Exception as e:
        logger.error(f"Thunderstorm indices error: {e}", exc_info=True)
        result["error"] = str(e)

    return result


def build_wind_profile(current, hourly, pressure_levels):
    surface_pressure = current.get("surface_pressure")
    if surface_pressure is None:
        return [], [], []

    pressures, speeds, dirs = [], [], []

    s_surf = current.get("wind_speed_10m")
    d_surf = current.get("wind_direction_10m")
    if s_surf is not None and d_surf is not None:
        pressures.append(surface_pressure)
        speeds.append(s_surf)
        dirs.append(d_surf)

    for lvl in pressure_levels:
        speed_key, dir_key = f"wind_speed_{lvl}hPa", f"wind_direction_{lvl}hPa"
        s_list = hourly.get(speed_key, [None])
        d_list = hourly.get(dir_key, [None])
        s = s_list[0] if s_list else None
        d = d_list[0] if d_list else None
        if lvl < surface_pressure and s is not None and d is not None:
            pressures.append(lvl)
            speeds.append(s)
            dirs.append(d)

    return pressures, speeds, dirs


def calculate_hodograph_shear_srh(current, hourly, pressure_levels):
    result = {
        "bulk_shear_06": 0, "bulk_shear_03": 0, "srh": 0,
        "shear_interpretation": "Нет данных", "srh_method": "н/д",
    }
    try:
        pressures, speeds, dirs = build_wind_profile(current, hourly, pressure_levels)
        if len(pressures) < 3:
            logger.warning(f"Недостаточно уровней ветра для годографа: {len(pressures)} (нужно ≥3).")
            result["shear_interpretation"] = "Недостаточно данных о ветре на уровнях"
            return result

        p = np.array(pressures) * units.hPa
        speed = np.array(speeds) * units("m/s")
        direction = np.array(dirs) * units.deg

        u, v = mpcalc.wind_components(speed, direction)
        heights = mpcalc.pressure_to_height_std(p)

        max_depth_available = (heights[-1] - heights[0]).to("m").magnitude
        depth_06 = min(6000, max_depth_available) * units.m
        depth_03 = min(3000, max_depth_available) * units.m

        shear06_u, shear06_v = mpcalc.bulk_shear(p, u, v, height=heights, depth=depth_06)
        shear03_u, shear03_v = mpcalc.bulk_shear(p, u, v, height=heights, depth=depth_03)

        result["bulk_shear_06"] = round(float(np.hypot(shear06_u.to("m/s").magnitude, shear06_v.to("m/s").magnitude)), 1)
        result["bulk_shear_03"] = round(float(np.hypot(shear03_u.to("m/s").magnitude, shear03_v.to("m/s").magnitude)), 1)
        result["shear_interpretation"] = interpret_shear(result["bulk_shear_06"])

        try:
            right_mover, _, _ = mpcalc.bunkers_storm_motion(p, u, v, heights)
            storm_u, storm_v = right_mover[0], right_mover[1]
            result["srh_method"] = "Bunkers (right-mover)"
        except Exception as e:
            logger.warning(f"Bunkers fallback: {e}")
            storm_u, storm_v = 15 * units("m/s"), 0 * units("m/s")
            result["srh_method"] = "оценка (15 м/с с запада)"

        _, _, srh_total = mpcalc.storm_relative_helicity(heights, u, v, depth=depth_03, storm_u=storm_u, storm_v=storm_v)
        result["srh"] = round(float(srh_total.to("m^2/s^2").magnitude), 1)

    except Exception as e:
        logger.error(f"Hodograph shear/SRH calculation error: {e}", exc_info=True)

    return result


def calculate_showalter_index(pressure_levels, temperatures, dewpoints):
    try:
        p = np.array(pressure_levels)
        idx_850, idx_500 = int(np.argmin(np.abs(p - 850))), int(np.argmin(np.abs(p - 500)))
        p850 = pressure_levels[idx_850] * units.hPa
        T850, Td850 = temperatures[idx_850] * units.degC, dewpoints[idx_850] * units.degC
        T500_actual = temperatures[idx_500] * units.degC
        lcl_p, lcl_t = mpcalc.lcl(p850, T850, Td850)
        parcel_temp_500 = mpcalc.moist_lapse(500 * units.hPa, lcl_t, reference_pressure=lcl_p)
        return round((T500_actual - parcel_temp_500).magnitude, 1)
    except Exception as e:
        logger.error(f"Showalter Index error: {e}", exc_info=True)
        return None


def calculate_sweat_index(td850, total_totals, wind_speed_850_ms, wind_speed_500_ms, wind_dir_850, wind_dir_500):
    try:
        if td850 is None or total_totals is None:
            return None
        term_td = 12 * max(td850, 0)
        term_tt = 20 * max(total_totals - 49, 0)
        f850_kt, f500_kt = wind_speed_850_ms * 1.94384, wind_speed_500_ms * 1.94384
        shear_term = 0
        dir_shear = wind_dir_500 - wind_dir_850
        if (wind_dir_850 is not None and wind_dir_500 is not None and
            130 <= wind_dir_850 <= 250 and 210 <= wind_dir_500 <= 310 and 
            dir_shear > 0 and f850_kt >= 15 and f500_kt >= 15):
            shear_term = 125 * (np.sin(np.radians(dir_shear)) + 0.2)
        return round(term_td + term_tt + 2 * f850_kt + f500_kt + shear_term, 0)
    except Exception as e:
        logger.error(f"SWEAT Index error: {e}")
        return None


def calculate_ehi(cape, srh):
    try:
        if srh is None or srh == 0 or cape is None:
            return None
        return (srh * cape) / 160000
    except Exception:
        return None


def calculate_brn(cape, bulk_shear_06):
    try:
        if bulk_shear_06 is None or bulk_shear_06 == 0 or cape is None:
            return None
        return round(cape / (0.5 * bulk_shear_06 ** 2), 1)
    except Exception:
        return None


def calculate_threat_level(k, tt, li, cape=0, cin=0, shear_06=0, ehi=0):
    score = 0
    cin_abs = abs(cin) if cin else 0
    if cape >= 250:
        score += 1
    if cape >= 1000:
        score += 1
    if cape >= 2500:
        score += 1
    if k >= 30:
        score += 1
    if tt >= 50:
        score += 1
    if li <= -3:
        score += 1
    if shear_06 >= 15 and cape >= 750:
        score += 1
    if shear_06 < 7:
        score -= 1
    if cin_abs > 250:
        score -= 1
    if cape < 250 and score > 2:
        score -= 1
    if ehi is not None and ehi < -1.0:
        score -= 1
    return max(0, min(score, 5))


def _threat_bar(level: int) -> str:
    return "" * level + "⬜" * (5 - level)

def build_storm_report(current_data: dict, pressure_data: dict) -> dict:
    current = current_data["current"]
    hourly = pressure_data.get("hourly", {})
    report = {}

    surface_temp = current.get("temperature_2m")
    surface_dewpoint = current.get("dew_point_2m")
    surface_pressure = current.get("surface_pressure")

    profile_pressure, profile_temp, profile_dewpoint = [], [], []
    if surface_temp is not None and surface_dewpoint is not None and surface_pressure is not None:
        profile_pressure.append(float(surface_pressure))
        profile_temp.append(float(surface_temp))
        profile_dewpoint.append(float(surface_dewpoint))

    for lvl in PRESSURE_LEVELS:
        t = hourly.get(f"temperature_{lvl}hPa", [None])[0]
        td = hourly.get(f"dew_point_{lvl}hPa", [None])[0]
        if t is not None and td is not None:
            if not profile_pressure or lvl < profile_pressure[-1]:
                profile_pressure.append(float(lvl))
                profile_temp.append(float(t))
                profile_dewpoint.append(float(td))

    if len(profile_pressure) >= 2:
        if not validate_profile_physical(profile_pressure, profile_temp):
            logger.warning("Profile validation failed, using data with caution")

        cape, cin, lcl, cape_type = 0, 0, 0, "SB"
        mucape_result = calculate_mucape_real(profile_pressure, profile_temp, profile_dewpoint)
        if mucape_result:
            cape, cin, lcl, cape_type = mucape_result
            logger.debug("Using MUCAPE")
        else:
            mlcape_result = calculate_mlcape_real(profile_pressure, profile_temp, profile_dewpoint)
            if mlcape_result:
                cape, cin, lcl, cape_type = mlcape_result
                logger.debug("Using MLCAPE")
            else:
                cape, cin, lcl, cape_type = calculate_cape_real(profile_pressure, profile_temp, profile_dewpoint)
                logger.debug("Using SBCAPE")

        report["cape"], report["cin"], report["lcl"], report["cape_type"] = cape, cin, lcl, cape_type
        report["cin_interpretation"] = interpret_cin(cin)
    else:
        report["cape"], report["cin"], report["lcl"], report["cape_type"] = 0, 0, 0, "SB"
        report["cin_interpretation"] = interpret_cin(0)

    valid_levels, temperatures, dewpoints = [], [], []
    for lvl in PRESSURE_LEVELS:
        t = hourly.get(f"temperature_{lvl}hPa", [None])[0]
        td = hourly.get(f"dew_point_{lvl}hPa", [None])[0]
        if t is not None and td is not None:
            valid_levels.append(lvl)
            temperatures.append(t)
            dewpoints.append(td)

    if len(valid_levels) >= 3:
        report.update(calculate_thunderstorm_indices(valid_levels, temperatures, dewpoints))
        report["showalter_index"] = calculate_showalter_index(valid_levels, temperatures, dewpoints)
        report["si_interpretation"] = interpret_si(report["showalter_index"])

        if 850 in valid_levels and 500 in valid_levels:
            idx_850 = valid_levels.index(850)
            report["sweat_index"] = calculate_sweat_index(
                dewpoints[idx_850], report.get("total_totals", 0),
                hourly.get("wind_speed_850hPa", [0])[0], hourly.get("wind_speed_500hPa", [0])[0],
                hourly.get("wind_direction_850hPa", [0])[0], hourly.get("wind_direction_500hPa", [0])[0]
            )
            report["sweat_interpretation"] = interpret_sweat(report["sweat_index"])
        else:
            report["sweat_index"] = None
            report["sweat_interpretation"] = "Нет данных (нет 850/500 hPa)"
    else:
        report["error"] = "Недостаточно данных профиля"

    report.update(calculate_hodograph_shear_srh(current, hourly, PRESSURE_LEVELS))

    report["ehi"] = calculate_ehi(report.get("cape"), report.get("srh"))
    report["ehi_interpretation"] = interpret_ehi(report["ehi"])
    report["brn"] = calculate_brn(report.get("cape"), report.get("bulk_shear_06"))
    report["brn_interpretation"] = interpret_brn(report["brn"])

    lcl_height_m = lcl_pressure_to_height(report.get("lcl"))
    report["lcl_height_m"] = lcl_height_m
    report["stp"] = calculate_stp(
        report.get("cape"), report.get("srh"),
        lcl_height_m, report.get("cin"), report.get("bulk_shear_06")
    )
    report["stp_interpretation"] = interpret_stp(report["stp"])
    report["scp"] = calculate_scp(
        report.get("cape"), report.get("srh"),
        report.get("bulk_shear_06"), report.get("cin")
    )
    report["scp_interpretation"] = interpret_scp(report["scp"])

    if len(profile_pressure) >= 2:
        report["dcape"] = calculate_dcape(profile_pressure, profile_temp, profile_dewpoint)
    else:
        report["dcape"] = None
    report["dcape_interpretation"] = interpret_dcape(report["dcape"])

    report["mcs_maintenance"] = calculate_mcs_maintenance(
        report.get("cape"), report.get("bulk_shear_06"),
        report.get("mid_layer_spread")
    )
    report["mcsm_interpretation"] = interpret_mcs_maintenance(report["mcs_maintenance"])

    cape = report.get("cape", 0) or 0
    k_index = report.get("k_index", 0) or 0
    total_totals = report.get("total_totals", 0) or 0
    li_for_calc = report.get("lifted_index", 0) or 0
    cin = report.get("cin", 0) or 0
    shear_06 = report.get("bulk_shear_06", 0) or 0
    ehi = report.get("ehi", 0) or 0
    report["threat_level"] = calculate_threat_level(
        k_index, total_totals, li_for_calc,
        cape=cape, cin=cin, shear_06=shear_06, ehi=ehi
    )

    return report


def format_storm_text(report: dict, city: str, timestamp_str: str) -> str:
    if "error" in report:
        return f"⚡ *ГРОЗОВЫЕ ИНДЕКСЫ: {city}*\n\n❌ Не удалось рассчитать индексы: данные неполные."

    threat = report.get("threat_level", 0)

    text = (
        f"⚡ *ГРОЗОВЫЕ ИНДЕКСЫ: {city}*\n"
        f"🕐 {timestamp_str}\n\n"
        f"🔥 *Термодинамика*\n"
        f"• CAPE ({report.get('cape_type', 'SB')}): *{report.get('cape')}* Дж/кг\n"
        f"• CIN: *{abs(report.get('cin', 0))}* Дж/кг\n"
        f"• LCL: *{report.get('lcl')}* гПа\n\n"
        f"📉 *Устойчивость*\n"
        f"• K-Index: *{report.get('k_index')}* — {report.get('k_interpretation')}\n"
        f"• Total Totals: *{report.get('total_totals')}* — {report.get('tt_interpretation')}\n"
        f"• Lifted Index: *{report.get('lifted_index')}* — {report.get('li_interpretation')}\n"
        f"• Mid-layer spread: *{report.get('mid_layer_spread')}*°C\n\n"
        f"🌪 *Динамика (Суперячейки)*\n"
        f"• Shear 0-6км: *{report.get('bulk_shear_06')}* м/с — {report.get('shear_interpretation')}\n"
        f"• Shear 0-3км: *{report.get('bulk_shear_03')}* м/с\n"
        f"• SRH 0-3км: *{report.get('srh')}* м²/с² ({report.get('srh_method')})\n\n"
        f"🎯 *Композитные (Шторм-чейзинг)*\n"
        f"• STP (торнадо): *{report.get('stp', 'н/д')}* — {report.get('stp_interpretation')}\n"
        f"• SCP (суперячейки): *{report.get('scp', 'н/д')}* — {report.get('scp_interpretation')}\n"
        f"• DCAPE (шквалы): *{report.get('dcape', 'н/д')}* Дж/кг — {report.get('dcape_interpretation')}\n"
        f"• MCS: {report.get('mcsm_interpretation')}\n\n"
        f"📊 *Дополнительно*\n"
        f"• Showalter: *{report.get('showalter_index')}* | SWEAT: *{report.get('sweat_index')}*\n"
        f"• EHI: *{report.get('ehi', 'н/д')}* | BRN: *{report.get('brn', 'н/д')}*\n\n"
        f"⚠️ *Уровень угрозы:* {_threat_bar(threat)} *{threat}/5*\n\n"
        f"_Расчёт по доступному профилю. Не заменяет официальный прогноз._"
    )
    return text

def build_skewt_context_for_ai(report: dict, current: dict, pressure_data: dict) -> str:
    hourly = pressure_data.get("hourly", {})
    lines = ["📊 ПОЛНЫЙ АНАЛИЗ АТМОСФЕРЫ (для AI):"]
    lines.append("=" * 50)

    cape = report.get("cape", 0) or 0
    cape_type = report.get("cape_type", "SB")
    cin = report.get("cin", 0) or 0
    lcl = report.get("lcl", 0) or 0
    lcl_height = report.get("lcl_height_m")
    threat = report.get("threat_level", 0)
    
    lines.append("")
    lines.append("📊 ТЕРМОДИНАМИКА:")
    lines.append(f"  CAPE ({cape_type}): {cape} Дж/кг — " + (
        "конвекция невозможна" if cape < 100 else
        "слабая нестабильность" if cape < 500 else
        "умеренная нестабильность" if cape < 1000 else
        "сильная нестабильность" if cape < 2500 else
        "экстремальная нестабильность"
    ))
    lines.append(f"  CIN: {abs(cin)} Дж/кг — " + (
        "нет крышки" if abs(cin) < 25 else
        "слабая крышка" if abs(cin) < 50 else
        "умеренная крышка" if abs(cin) < 200 else
        "сильная крышка"
    ))
    if lcl_height:
        lines.append(f"  LCL: {lcl} гПа (~{int(lcl_height)}м)")
    else:
        lines.append(f"  LCL: {lcl} гПа")
    
    lines.append("")
    lines.append("📊 ИНДЕКСЫ УСТОЙЧИВОСТИ:")
    if report.get("k_index"): lines.append(f"  K-Index: {report['k_index']} — {report.get('k_interpretation', '')}")
    if report.get("total_totals"): lines.append(f"  Total Totals: {report['total_totals']} — {report.get('tt_interpretation', '')}")
    if report.get("lifted_index"): lines.append(f"  Lifted Index: {report['lifted_index']} — {report.get('li_interpretation', '')}")
    if report.get("showalter_index"): lines.append(f"  Showalter: {report['showalter_index']} — {report.get('si_interpretation', '')}")
    if report.get("sweat_index"): lines.append(f"  SWEAT: {report['sweat_index']} — {report.get('sweat_interpretation', '')}")
    
    lines.append("")
    lines.append("📊 ДИНАМИКА (ветер/сдвиг):")
    lines.append(f"  Bulk Shear 0-6км: {report.get('bulk_shear_06', 'н/д')} м/с — {report.get('shear_interpretation', '')}")
    lines.append(f"  Bulk Shear 0-3км: {report.get('bulk_shear_03', 'н/д')} м/с")
    lines.append(f"  SRH 0-3км: {report.get('srh', 'н/д')} м²/с² ({report.get('srh_method', '')})")
    
    lines.append("")
    lines.append("📊 КОМПОЗИТНЫЕ ИНДЕКСЫ (шторм-чейзинг):")
    stp = report.get("stp")
    scp = report.get("scp")
    dcape = report.get("dcape")
    mcsm = report.get("mcs_maintenance")
    ehi = report.get("ehi")
    brn = report.get("brn")
    
    lines.append(f"  🌪 STP (торнадо): {stp} — {report.get('stp_interpretation', '')}")
    lines.append(f"  ⚡ SCP (суперячейки): {scp} — {report.get('scp_interpretation', '')}")
    lines.append(f"  💨 DCAPE (шквалы): {dcape} Дж/кг — {report.get('dcape_interpretation', '')}")
    lines.append(f"  📏 MCS Maintenance: {report.get('mcsm_interpretation', '')}")
    if ehi: lines.append(f"  EHI (энергия-спиральность): {ehi} — {report.get('ehi_interpretation', '')}")
    if brn: lines.append(f"  BRN (Bulk Richardson): {brn} — {report.get('brn_interpretation', '')}")
    
    lines.append("")
    lines.append(f"📊 ОБЩИЙ УРОВЕНЬ УГРОЗЫ: {threat}/5 {_threat_bar(threat)}")
    
    lines.append("")
    lines.append("📊 ВЕРТИКАЛЬНЫЙ ПРОФИЛЬ (T-Td spread):")
    spreads = {}
    for lvl in PRESSURE_LEVELS:
        t = hourly.get(f"temperature_{lvl}hPa", [None])[0]
        td = hourly.get(f"dew_point_{lvl}hPa", [None])[0]
        if t is not None and td is not None:
            spreads[lvl] = round(t - td, 1)
    
    if spreads:
        for lvl in sorted(spreads.keys(), reverse=True):
            spread = spreads[lvl]
            humidity = "СУХОЙ" if spread > 15 else "умеренно" if spread > 8 else "влажный" if spread > 3 else "насыщенный"
            lines.append(f"  {lvl} гПа: T-Td = {spread}°C ({humidity})")
    
    temps = [(lvl, hourly.get(f"temperature_{lvl}hPa", [None])[0]) for lvl in PRESSURE_LEVELS]
    temps = [(lvl, t) for lvl, t in temps if t is not None]
    inversions = []
    for i in range(len(temps) - 1):
        lvl_lo, t_lo = temps[i]
        lvl_hi, t_hi = temps[i + 1]
        if t_hi > t_lo:
            inversions.append(f"{lvl_hi}-{lvl_lo} гПа")
    
    if inversions:
        lines.append("")
        lines.append(f"⚠️ ИНВЕРСИИ (крышки): {', '.join(inversions)}")
    
    winds = [(lvl, hourly.get(f"wind_speed_{lvl}hPa", [None])[0]) for lvl in PRESSURE_LEVELS]
    winds = [(lvl, w) for lvl, w in winds if w is not None]
    if winds:
        jet_lvl, jet_w = max(winds, key=lambda x: x[1])
        lines.append(f"  Струйное течение: {jet_w:.0f} м/с на {jet_lvl} гПа")
    
    try:
        s_t, s_td, s_p = current.get("temperature_2m"), current.get("dew_point_2m"), current.get("surface_pressure")
        if s_t is not None and s_td is not None and s_p is not None:
            prof_p, prof_t, prof_td = [float(s_p)], [float(s_t)], [float(s_td)]
            for lvl in PRESSURE_LEVELS:
                t = hourly.get(f"temperature_{lvl}hPa", [None])[0]
                td = hourly.get(f"dew_point_{lvl}hPa", [None])[0]
                if t is not None and td is not None and lvl < prof_p[-1]:
                    prof_p.append(float(lvl))
                    prof_t.append(float(t))
                    prof_td.append(float(td))
            if len(prof_p) >= 2:
                p, T, Td = (
                    np.array(prof_p) * units.hPa,
                    np.array(prof_t) * units.degC,
                    np.array(prof_td) * units.degC,
                )
                lfc_p, _ = mpcalc.lfc(p, T, Td)
                el_p, _ = mpcalc.el(p, T, Td)
                # Исправленная проверка на None
                lfc_v = float(lfc_p.magnitude) if lfc_p is not None and hasattr(lfc_p, 'magnitude') and np.isfinite(lfc_p.magnitude) else None
                el_v = float(el_p.magnitude) if el_p is not None and hasattr(el_p, 'magnitude') and np.isfinite(el_p.magnitude) else None
                if lfc_v:
                    lines.append("")
                    lines.append(f"  LFC (свободная конвекция): {lfc_v:.0f} гПа" + (
                        " — высоко, нужен сильный подъём" if lfc_v < 700 else ""
                    ))
                if el_v:
                    lines.append(f"  EL (вершина грозы): {el_v:.0f} гПа")
    except Exception as e:
        logger.debug(f"LFC/EL не посчитались: {e}")
    
    lines.append("")
    lines.append("=" * 50)
    lines.append("🔍 ЗАДАЧА ДЛЯ AI:")
    lines.append("На основе всех данных выше, дай РАЗВЁРНУТЫЙ анализ:")
    lines.append("1. Тип ожидаемых гроз (одиночные/мульти/суперячейки/MCS)")
    lines.append("2. Вероятность опасных явлений (торнадо, град, шквалы)")
    lines.append("3. Пробьёт ли конвекция крышку (учитывая CIN и триггеры)")
    lines.append("4. Время максимальной активности (если есть данные о CAPE типе)")
    lines.append("5. Рекомендации для шторм-чейзеров (куда ехать, что искать)")
    lines.append("")
    lines.append("Отвечай на русском, используй эмодзи для наглядности.")
    
    return "\n".join(lines)