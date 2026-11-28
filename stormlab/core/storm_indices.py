import logging
import numpy as np
import metpy.calc as mpcalc
from metpy.units import units

from stormlab.core.effective_layer import (
    find_effective_layer,
    effective_srh,
    effective_bulk_shear,
    most_unstable_el_height,
    stp_effective,
    scp_effective,
)

logger = logging.getLogger(__name__)

PRESSURE_LEVELS = [1000, 925, 850, 700, 500, 300]
SKEWT_LEVELS = [1000, 975, 950, 925, 900, 850, 800, 700, 600, 500, 400, 300]


def _nd_render(value, missing="н/д"):
    """Render a user-facing/AI-facing optional value: None -> «н/д».

    Never literal «None», never 0.0 as a stand-in for missing data. Real zeros
    are rendered as numbers (``0.0``), preserving fixed-field semantics.
    """
    if value is None:
        return missing
    # Sparse model grids can yield NaN/inf; they are missing data, not numbers.
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return missing
    return str(value)


def _as_float(value):
    """Numeric guard for values that must stay numeric (e.g. abs(CIN))."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def interpret_cin(cin_value, regime="warm"):
    cin_abs = abs(cin_value) if cin_value is not None else 0
    if regime == "cool":
        if cin_abs < 25:
            return "🟢 Крышка отсутствует — зимняя конвекция возможна (thundersnow)"
        elif cin_abs < 50:
            return "🟡 Слабая крышка — возможны снежные заряды"
        elif cin_abs < 200:
            return "🟠 Умеренная крышка — для зимней конвекции нужен фронт/орография"
        else:
            return "🔴 Сильная крышка — зимние грозы маловероятны"
    if cin_abs < 25:
        return "🟢 Крышка отсутствует — свободная конвекция"
    elif cin_abs < 50:
        return "🟡 Слабая крышка"
    elif cin_abs < 200:
        return "🟠 Умеренная крышка — нужен триггер (фронт, орография)"
    else:
        return "🔴 Сильная крышка — грозы маловероятны"


def interpret_cape(cape, regime="warm"):
    cape = cape or 0
    if regime == "cool":
        if cape < 100:
            return "❄️ Недостаточно энергии даже для зимней конвекции"
        elif cape < 200:
            return "❄️ Слабая зимняя нестабильность"
        elif cape < 500:
            return "🌨 Умеренная зимняя нестабильность — возможен thundersnow"
        elif cape < 1000:
            return "🌨 Значимая зимняя конвекция (thundersnow/snow-squall)"
        else:
            return "❄️ Аномально высокий CAPE для холодного сезона — мощная зимняя конвекция"
    if cape < 100:
        return "конвекция невозможна"
    elif cape < 500:
        return "слабая нестабильность"
    elif cape < 1000:
        return "умеренная нестабильность"
    elif cape < 2500:
        return "сильная нестабильность"
    return "экстремальная нестабильность"


def interpret_lcl(lcl_height_m, regime="warm"):
    if lcl_height_m is None:
        return "н/д"
    if regime == "cool":
        if lcl_height_m < 1000:
            return "🌨 Низкий LCL — влажный снег/ледяные ядра, риск snow-squall"
        elif lcl_height_m <= 2500:
            return "🌨 Умеренный LCL — зимняя конвекция возможна"
        return "❄️ Высокий LCL — зимняя конвекция маловероятна"
    if lcl_height_m < 1000:
        return "Низкий LCL — благоприятен для торнадо"
    elif lcl_height_m <= 2000:
        return "Умеренный LCL"
    return "Высокий LCL — конвекция выше и слабее"

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
        return "🟠 Высокий потенциал суперячеек"
    else:
        return "🔴 Экстремальный потенциал суперячеек"

def interpret_dcape(dcape):
    if dcape is None:
        return "н/д"
    if dcape < 500:
        return "🟢 Слабые нисходящие потоки"
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

def interpret_shear(bulk_shear_06, regime="warm"):
    if bulk_shear_06 is None or bulk_shear_06 == 0:
        return "Нет данных о ветре на уровнях"
    if regime == "cool":
        if bulk_shear_06 < 10:
            return "🟢 Слабый (разрозненная зимняя конвекция)"
        elif bulk_shear_06 < 20:
            return "🟡 Умеренный (снежные заряды/полосы)"
        elif bulk_shear_06 < 30:
            return "🟠 Сильный (snow-squall / зимний шквал)"
        else:
            return "🔴 Очень сильный (снежная буря / шквалистые линии)"
    if bulk_shear_06 < 10:
        return "🟢 Слабый (одиночные ячейки)"
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
        return "🟢 Нет конвекции"
    elif tt < 47:
        return "🟡 Слабая конвекция"
    elif tt < 50:
        return "🟠 Возможны грозы"
    elif tt < 53:
        return "🔴 Вероятны грозы"
    else:
        return "⚫ Сильные грозы вероятны"

def interpret_li(li):
    if li is None:
        return "Нет данных"
    if li > 2:
        return "🟢 Стабильно"
    elif li > 0:
        return "🟡 Слабая нестабильность"
    elif li > -3:
        return "🟠 Умеренная нестабильность"
    elif li > -6:
        return "🔴 Сильная нестабильность"
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
        return "🟠 Возможны грозы"
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
        return "🟢 Низкий потенциал суперячеек"
    elif ehi < 2:
        return "🟡 Умеренный потенциал"
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
        return "🟡 Слабый сдвиг относительно CAPE (мультиячейковые грозы)"

def calculate_stp(sb_cape, srh_0_1, sb_lcl_height_m, shear_06, cin=None):
    """Fixed-layer STP per SPC (no CIN term).

    SPC: "STP = (sbCAPE / 1500 J kg-1) * ((2000 - sbLCL) / 1000 m) *
    (0-1 km SRH / 150 m2 s-2) * (6BWD / 20 m s-1) where the sbLCL term is set
    to 1.0 for sbLCL heights < 1000 m AGL; the 6BWD term is capped at 1.5 for
    6BWD > 30 m s-1, and set to 0.0 for 6BWD < 12.5 m s-1."
    https://www.spc.noaa.gov/exper/mesoanalysis/help/begin.html

    ``cin`` is accepted for backwards compatibility only and is deliberately
    ignored: the SPC fixed-layer formula has no CIN term.
    """
    try:
        if sb_cape is None or srh_0_1 is None or shear_06 is None:
            return None
        if sb_cape <= 0 or shear_06 <= 0:
            return 0.0
        # SPC: "the 6BWD term ... set to 0.0 for 6BWD < 12.5 m s-1"
        if shear_06 < 12.5:
            return 0.0

        cape_term = max(0.0, sb_cape / 1500.0)

        # SPC: "sbLCL term is set to 1.0 for sbLCL heights < 1000 m AGL"
        if sb_lcl_height_m is None:
            lcl_term = 1.0
        elif sb_lcl_height_m < 1000:
            lcl_term = 1.0
        else:
            lcl_term = max(0.0, min(1.0, (2000.0 - sb_lcl_height_m) / 1000.0))

        srh_term = max(0.0, srh_0_1 / 150.0)
        # SPC: "the 6BWD term is capped at 1.5 for 6BWD > 30 m s-1"
        shear_term = min(shear_06, 30.0) / 20.0

        return round(cape_term * lcl_term * srh_term * shear_term, 2)
    except Exception:
        return None

def scp_fixed_local(cape, srh, shear_06, cin):
    """Local fixed-layer heuristic. NOT the SPC SCP.

    SPC defines SCP only with effective-layer ingredients (muCAPE, ESRH, EBWD);
    there is no fixed-layer SCP in
    https://www.spc.noaa.gov/exper/mesoanalysis/help/help_scp.html or
    https://www.spc.noaa.gov/exper/mesoanalysis/help/begin.html
    Formula kept unchanged as a local screening heuristic.
    """
    try:
        if cape is None or srh is None or shear_06 is None:
            return None
        if cape <= 0 or shear_06 <= 0:
            return 0.0
        
        cape_term = max(0.0, cape / 1000.0)
        srh_term = max(0.0, srh / 100.0)
        shear_term = max(0.0, min(1.5, shear_06 / 20.0))
        
        cin_abs = abs(cin) if cin is not None else 0.0
        cin_term = max(0.0, min(1.0, (200.0 - cin_abs) / 150.0))
        
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

        # Ручной fallback с использованием виртуальной температуры (Tv) для точности
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
            
            Td_env = Td[i]
            w_env = mpcalc.mixing_ratio_from_relative_humidity(
                p_i, T_env, 
                mpcalc.relative_humidity_from_dewpoint(T_env, Td_env)
            ).magnitude
            Tv_env = T_env.magnitude * (1 + 0.61 * w_env)
            Tv_parcel = T_parcel.magnitude
            
            if Tv_parcel < Tv_env:
                buoyancy = g * (Tv_env - Tv_parcel) / (Tv_env + 273.15)
                p_prev = p[i - 1]
                dz = (Rd * (Tv_env + 273.15) / g) * np.log(p_prev.magnitude / p_i.magnitude)
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
        return round(float(li), 1)
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
            idx = int(np.argmin(np.abs(p - target)))
            if abs(p[idx] - target) > 50:
                return None
            return idx

        idx_850, idx_700, idx_500 = find_level(850), find_level(700), find_level(500)
        
        if idx_850 is None or idx_700 is None or idx_500 is None:
            result["k_index"] = None
            result["total_totals"] = None
            result["k_interpretation"] = "Нет данных (нет уровней 850/700/500)"
            result["tt_interpretation"] = "Нет данных"
            return result
        
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
            mid_layer_spread = np.mean([T[i] - Td[i] for i in range(len(T)) if 500 <= p[i] <= 700])
            result["mid_layer_spread"] = round(mid_layer_spread, 1)
        except Exception:
            result["mid_layer_spread"] = None

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

def calculate_hodograph_shear_srh(current, hourly, pressure_levels, regime="warm"):
    result = {
        "bulk_shear_06": 0, "bulk_shear_03": 0, "srh": 0, "srh_0_1": 0,
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
        depth_01 = min(1000, max_depth_available) * units.m

        shear06_u, shear06_v = mpcalc.bulk_shear(p, u, v, height=heights, depth=depth_06)
        shear03_u, shear03_v = mpcalc.bulk_shear(p, u, v, height=heights, depth=depth_03)

        result["bulk_shear_06"] = round(float(np.hypot(shear06_u.to("m/s").magnitude, shear06_v.to("m/s").magnitude)), 1)
        result["bulk_shear_03"] = round(float(np.hypot(shear03_u.to("m/s").magnitude, shear03_v.to("m/s").magnitude)), 1)
        result["shear_interpretation"] = interpret_shear(result["bulk_shear_06"], regime)

        try:
            right_mover, _, _ = mpcalc.bunkers_storm_motion(p, u, v, heights)
            storm_u, storm_v = right_mover[0], right_mover[1]
            result["storm_motion_u"] = float(storm_u.to("m/s").magnitude)
            result["storm_motion_v"] = float(storm_v.to("m/s").magnitude)
            result["srh_method"] = "Bunkers (right-mover)"
        except Exception as e:
            logger.warning(f"Bunkers fallback: {e}")
            mean_u = np.mean(u)
            mean_v = np.mean(v)
            storm_u, storm_v = mean_u, mean_v
            result["storm_motion_u"] = float(storm_u.to("m/s").magnitude)
            result["storm_motion_v"] = float(storm_v.to("m/s").magnitude)
            result["srh_method"] = "оценка (средний ветер 0-6км)"

        _, _, srh_total = mpcalc.storm_relative_helicity(heights, u, v, depth=depth_03, storm_u=storm_u, storm_v=storm_v)
        result["srh"] = round(float(srh_total.to("m^2/s^2").magnitude), 1)

        # SPC fixed-layer STP uses 0-1 km SRH, not 0-3 km:
        # "STP = ... * (0-1 km SRH / 150 m2 s-2) * ..."
        # https://www.spc.noaa.gov/exper/mesoanalysis/help/begin.html
        _, _, srh_01 = mpcalc.storm_relative_helicity(heights, u, v, depth=depth_01, storm_u=storm_u, storm_v=storm_v)
        result["srh_0_1"] = round(float(srh_01.to("m^2/s^2").magnitude), 1)

    except Exception as e:
        logger.error(f"Hodograph shear/SRH calculation error: {e}", exc_info=True)

    return result

def calculate_showalter_index(pressure_levels, temperatures, dewpoints):
    try:
        p = np.array(pressure_levels) * units.hPa
        T = np.array(temperatures) * units.degC
        Td = np.array(dewpoints) * units.degC

        idx_850 = int(np.argmin(np.abs(p.magnitude - 850)))
        idx_500 = int(np.argmin(np.abs(p.magnitude - 500)))

        lcl_p, lcl_t = mpcalc.lcl(p[idx_850], T[idx_850], Td[idx_850])
        parcel_temp_500 = mpcalc.moist_lapse(
            500 * units.hPa, lcl_t, reference_pressure=lcl_p
        )
        return round((T[idx_500] - parcel_temp_500).magnitude, 1)

    except Exception as e:
        logger.error(f"Showalter Index error: {e}", exc_info=True)
        return None

def calculate_sweat_index(td850, total_totals, wind_speed_850_ms, wind_speed_500_ms, wind_dir_850, wind_dir_500):
    try:
        if td850 is None or total_totals is None:
            return None
        
        term_td = 12 * max(td850, 0)
        term_tt = 20 * max(total_totals - 49, 0)
        
        f850_kt = wind_speed_850_ms * 1.94384 if wind_speed_850_ms is not None else 0
        f500_kt = wind_speed_500_ms * 1.94384 if wind_speed_500_ms is not None else 0
        
        shear_term = 0
        
        if (wind_dir_850 is not None and wind_dir_500 is not None and
            130 <= wind_dir_850 <= 250 and 210 <= wind_dir_500 <= 310):
            dir_shear = wind_dir_500 - wind_dir_850
            if dir_shear > 0 and f850_kt >= 15 and f500_kt >= 15:
                shear_term = 125 * (np.sin(np.radians(dir_shear)) + 0.2)
        
        return round(term_td + term_tt + 2 * f850_kt + f500_kt + shear_term, 0)
    except Exception as e:
        logger.error(f"SWEAT Index error: {e}")
        return None

def calculate_ehi(cape, srh, pressure_profile=None, temperature_profile=None, dewpoint_profile=None):
    try:
        if srh is None or srh == 0 or cape is None:
            return None
        
        # Используем CAPE в слое 0-3 км для более точной оценки торнадо-потенциала
        if pressure_profile is not None and temperature_profile is not None and dewpoint_profile is not None:
            try:
                p = np.array(pressure_profile) * units.hPa
                T = np.array(temperature_profile) * units.degC
                Td = np.array(dewpoint_profile) * units.degC
                
                heights = mpcalc.pressure_to_height_std(p)
                idx_3km = np.where(heights <= 3000 * units.m)[0][-1] if np.any(heights <= 3000 * units.m) else len(p) - 1
                
                cape_3km, _ = mpcalc.surface_based_cape_cin(p[:idx_3km+1], T[:idx_3km+1], Td[:idx_3km+1])
                cape_val = cape_3km.magnitude if cape_3km is not None else cape
            except Exception:
                cape_val = cape
        else:
            cape_val = cape
        
        return round((srh * cape_val) / 160000, 2)
    except Exception:
        return None

def calculate_brn(cape, bulk_shear_06):
    try:
        if bulk_shear_06 is None or bulk_shear_06 == 0 or cape is None:
            return None
        return round(cape / (0.5 * bulk_shear_06 ** 2), 1)
    except Exception:
        return None

def calculate_threat_level(
    k, tt, li, cape=0, cin=0, shear_06=0, ehi=0, regime="warm", thresholds=None
):
    """Report-only threat score (0-5); never used as an alert gate.

    The cool first-ball CAPE floor is 150 here (alert_manager's CAPE_FLOOR is
    100, and the seasonal alert ``cape_min`` is 200): three distinct numbers
    for three distinct mechanisms. Do not unify them.
    """
    from stormlab.core.season_regime import thresholds_for

    thresholds = thresholds_for(regime) if thresholds is None else thresholds
    score = 0
    cin_abs = abs(cin) if cin else 0
    # Cool-season convection is significant at much lower CAPE, so the first
    # threat point starts lower; the alert threshold itself stays at cape_min.
    low_cape_floor = 150 if regime == "cool" else 250
    if cape >= low_cape_floor: score += 1
    if cape >= 1000: score += 1
    if cape >= 2500: score += 1
    if k >= 30: score += 1
    if tt >= 50: score += 1
    if li <= -3: score += 1
    if shear_06 >= 15 and cape >= 750: score += 1
    if (
        regime == "cool"
        and cape >= thresholds["cape_min"]
        and shear_06 >= thresholds["shear06_min"]
    ):
        score += 1
    if shear_06 < 7: score -= 1
    if cin_abs > (thresholds["cin_max"] if regime == "cool" else 250): score -= 1
    if cape < low_cape_floor and score > 2: score -= 1
    if ehi is not None and ehi < 0: score -= 1  # Отрицательный EHI (левый суперячейковый режим) снижает риск
    return max(0, min(score, 5))

def _threat_bar(level: int) -> str:
    return "🟥" * level + "⬜" * (5 - level)

def build_thermal_profile(current, hourly, levels=None):
    """Build the raw thermodynamic profile, dropping levels below real surface pressure.

    Surface pressure is the ground truth: at a 985 hPa surface, 1000 hPa is
    underground and must not enter CAPE/CIN/LCL maths (non-monotonic profile,
    MetPy "Interpolation point out of data bounds").
    """
    levels = PRESSURE_LEVELS if levels is None else levels
    surface_temp = current.get("temperature_2m")
    surface_dewpoint = current.get("dew_point_2m")
    surface_pressure = current.get("surface_pressure")

    profile_pressure, profile_temp, profile_dewpoint = [], [], []
    if surface_temp is not None and surface_dewpoint is not None and surface_pressure is not None:
        profile_pressure.append(float(surface_pressure))
        profile_temp.append(float(surface_temp))
        profile_dewpoint.append(float(surface_dewpoint))

    ground = float(surface_pressure) if surface_pressure is not None else (
        profile_pressure[-1] if profile_pressure else None
    )
    for lvl in levels:
        t = hourly.get(f"temperature_{lvl}hPa", [None])[0]
        td = hourly.get(f"dew_point_{lvl}hPa", [None])[0]
        if t is None or td is None:
            continue
        if ground is not None and lvl >= ground:
            continue
        profile_pressure.append(float(lvl))
        profile_temp.append(float(t))
        profile_dewpoint.append(float(td))

    return profile_pressure, profile_temp, profile_dewpoint


def build_storm_report(current_data: dict, pressure_data: dict, regime="warm", thresholds=None) -> dict:
    current = current_data["current"]
    hourly = pressure_data.get("hourly", {})
    report = {}

    profile_pressure, profile_temp, profile_dewpoint = build_thermal_profile(current, hourly)

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
        report["cin_interpretation"] = interpret_cin(cin, regime)
    else:
        report["cape"], report["cin"], report["lcl"], report["cape_type"] = 0, 0, 0, "SB"
        report["cin_interpretation"] = interpret_cin(0, regime)

    report["regime"] = regime
    report["cape_interpretation"] = interpret_cape(report.get("cape"), regime)

    # SPC fixed-layer STP is surface-based: "(sbCAPE / 1500 J kg-1) *
    # ((2000 - sbLCL) / 1000 m) * (0-1 km SRH / 150 m2 s-2) * (6BWD / 20 m s-1)"
    # https://www.spc.noaa.gov/exper/mesoanalysis/help/begin.html
    sb_cape = sb_cin = sb_lcl_height_m = None
    if len(profile_pressure) >= 2:
        sb_cape, sb_cin, sb_lcl_p, _ = calculate_cape_real(
            profile_pressure, profile_temp, profile_dewpoint
        )
        sb_lcl_height_m = lcl_pressure_to_height(sb_lcl_p)

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

        # Точный расчёт LI через MetPy на полном профиле
        li_metpy = calculate_lifted_index_metpy(profile_pressure, profile_temp, profile_dewpoint)
        report["lifted_index"] = li_metpy
        report["li_interpretation"] = interpret_li(li_metpy)

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

    report.update(calculate_hodograph_shear_srh(current, hourly, PRESSURE_LEVELS, regime))
    
    report["ehi"] = calculate_ehi(
        report.get("cape"), report.get("srh"),
        profile_pressure, profile_temp, profile_dewpoint
    )
    report["ehi_interpretation"] = interpret_ehi(report["ehi"])
    report["brn"] = calculate_brn(report.get("cape"), report.get("bulk_shear_06"))
    report["brn_interpretation"] = interpret_brn(report["brn"])

    lcl_height_m = lcl_pressure_to_height(report.get("lcl"))
    report["lcl_height_m"] = lcl_height_m
    report["lcl_interpretation"] = interpret_lcl(lcl_height_m, regime)
    
    report["stp"] = calculate_stp(
        sb_cape, report.get("srh_0_1"),
        sb_lcl_height_m, report.get("bulk_shear_06"), sb_cin
    )
    report["stp_interpretation"] = interpret_stp(report["stp"])
    
    report["scp"] = scp_fixed_local(
        report.get("cape"), report.get("srh"),
        report.get("bulk_shear_06"), report.get("cin")
    )
    report["scp_interpretation"] = interpret_scp(report["scp"])

    effective_profile = None
    if len(profile_pressure) >= 2:
        pressures = np.array(profile_pressure) * units.hPa
        temperatures = np.array(profile_temp) * units.degC
        dewpoints = np.array(profile_dewpoint) * units.degC
        heights = mpcalc.pressure_to_height_std(pressures)

        pressures_wind, speeds_wind, dirs_wind = build_wind_profile(current, hourly, PRESSURE_LEVELS)
        wind_u = wind_v = None
        if len(pressures_wind) >= 2:
            wp = np.array(pressures_wind) * units.hPa
            speed = np.array(speeds_wind) * units("m/s")
            direction = np.array(dirs_wind) * units.deg
            wind_u, wind_v = mpcalc.wind_components(speed, direction)
            wind_heights = mpcalc.pressure_to_height_std(wp).to("m").magnitude
            therm_heights = heights.to("m").magnitude
            effective_profile = {
                "z": therm_heights,
                "u": np.interp(therm_heights, wind_heights, wind_u.to("m/s").magnitude),
                "v": np.interp(therm_heights, wind_heights, wind_v.to("m/s").magnitude),
                "p": pressures.to("hPa").magnitude,
                "T": temperatures.to("degC").magnitude,
                "Td": dewpoints.to("degC").magnitude,
            }

        mucape = mucin = mllcl = mlcape = mlcin = None
        try:
            mucape_qty, mucin_qty = mpcalc.most_unstable_cape_cin(
                pressures, temperatures, dewpoints, depth=300 * units.hPa
            )
            mucape = float(mucape_qty.magnitude) if mucape_qty is not None else 0.0
            mucin = float(mucin_qty.magnitude) if mucin_qty is not None else 0.0
        except Exception:
            pass
        try:
            # MetPy has no mpcalc.mix(); mixed_parcel() is the 100-hPa mean parcel.
            ml_p, ml_t, ml_td = mpcalc.mixed_parcel(
                pressures, temperatures, dewpoints, depth=100 * units.hPa
            )
            ml_lcl_p, _ = mpcalc.lcl(ml_p, ml_t, ml_td)
            mllcl = float(lcl_pressure_to_height(ml_lcl_p.magnitude) or 0)
            mlcape_qty, mlcin_qty = mpcalc.mixed_layer_cape_cin(
                pressures, temperatures, dewpoints, depth=100 * units.hPa
            )
            # SPC effective STP uses mlCAPE / mlLCL / mlCIN:
            # "STP = (mlCAPE / 1500 J kg-1) * ((2000 - mlLCL) / 1000 m) * ..."
            # https://www.spc.noaa.gov/exper/mesoanalysis/help/begin.html
            mlcape = float(mlcape_qty.magnitude) if mlcape_qty is not None else 0.0
            mlcin = float(mlcin_qty.magnitude) if mlcin_qty is not None else 0.0
        except Exception:
            pass

        effective_layer = find_effective_layer(effective_profile) if effective_profile is not None else None
        if effective_layer is not None:
            z_bot, z_top = effective_layer
            storm_motion = (
                report.get("storm_motion_u", 0),
                report.get("storm_motion_v", 0),
            )
            esrh = effective_srh(effective_profile, z_bot, z_top, storm_motion)
            # SPC: EBWD goes "upward to 50% of the equilibrium level height with
            # the most unstable parcel in the lowest 300 mb."
            # https://www.spc.noaa.gov/exper/mesoanalysis/help/begin.html
            mu_el = most_unstable_el_height(effective_profile)
            ebwd = effective_bulk_shear(effective_profile, z_bot, mu_el)
            report["stp_eff"] = stp_effective(
                mlcape, mllcl, esrh, ebwd, mlcin,
                base_height_m=z_bot,
                surface_height_m=float(effective_profile["z"][0]),
            )
            report["scp_eff"] = scp_effective(mucape, esrh, ebwd, mucin)
            report["effective_layer"] = (z_bot, z_top)
            report["ebwd"] = round(float(ebwd), 1)
            report["esrh"] = round(float(esrh), 1)
        else:
            report["stp_eff"] = None
            report["scp_eff"] = None
            report["effective_layer"] = None
    else:
        report["stp_eff"] = None
        report["scp_eff"] = None
        report["effective_layer"] = None

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

    # Финальный расчёт уровня угрозы, когда ВСЕ индексы уже гарантированно рассчитаны
    cape = report.get("cape", 0) or 0
    k_index = report.get("k_index", 0) or 0
    total_totals = report.get("total_totals", 0) or 0
    li_for_calc = report.get("lifted_index", 0) or 0
    cin = report.get("cin", 0) or 0
    shear_06 = report.get("bulk_shear_06", 0) or 0
    ehi = report.get("ehi", 0) or 0
    
    report["threat_level"] = calculate_threat_level(
        k_index, total_totals, li_for_calc,
        cape=cape, cin=cin, shear_06=shear_06, ehi=ehi,
        regime=regime, thresholds=thresholds
    )

    return report

def format_storm_text(report: dict, city: str, timestamp_str: str) -> str:
    if "error" in report:
        return f"⚡ *ГРОЗОВЫЕ ИНДЕКСЫ: {city}*\n\n❌ Не удалось рассчитать индексы: данные неполные."

    threat = report.get("threat_level", 0) or 0

    dcape = report.get("dcape")
    dcape_text = (
        "н/д Дж/кг"
        if dcape is None
        else f"*{dcape}* Дж/кг — {_nd_render(report.get('dcape_interpretation'))}"
    )

    text = (
        f"⚡ *ГРОЗОВЫЕ ИНДЕКСЫ: {city}*\n"
        f"🕐 {timestamp_str}\n\n"
        f"🔥 *Термодинамика*\n"
        f"• CAPE ({_nd_render(report.get('cape_type', 'SB'))}): *{_nd_render(report.get('cape'))}* Дж/кг\n"
        f"• CIN: *{abs(_as_float(report.get('cin')))}* Дж/кг\n"
        f"• LCL: *{_nd_render(report.get('lcl'))}* гПа\n\n"
        f"📉 *Устойчивость*\n"
        f"• K-Index: *{_nd_render(report.get('k_index'))}* — {_nd_render(report.get('k_interpretation'))}\n"
        f"• Total Totals: *{_nd_render(report.get('total_totals'))}* — {_nd_render(report.get('tt_interpretation'))}\n"
        f"• Lifted Index: *{_nd_render(report.get('lifted_index'))}* — {_nd_render(report.get('li_interpretation'))}\n"
        f"• Mid-layer spread: *{_nd_render(report.get('mid_layer_spread'))}*°C\n\n"
        f"🌪 *Динамика (Суперячейки)*\n"
        f"• Shear 0-6км: *{_nd_render(report.get('bulk_shear_06'))}* м/с — {_nd_render(report.get('shear_interpretation'))}\n"
        f"• Shear 0-3км: *{_nd_render(report.get('bulk_shear_03'))}* м/с\n"
        f"• SRH 0-3км: *{_nd_render(report.get('srh'))}* м²/с² ({_nd_render(report.get('srh_method'))})\n\n"
        f"🎯 *Композитные (Шторм-чейзинг)*\n"
        f"• STP (торнадо): *{_nd_render(report.get('stp'))}* — {_nd_render(report.get('stp_interpretation'))}\n"
        f"• STP(eff): *{_nd_render(report.get('stp_eff'))}*\n"
        f"• SCP (local, не SPC): *{_nd_render(report.get('scp'))}* — {_nd_render(report.get('scp_interpretation'))}\n"
        f"• SCP(eff): *{_nd_render(report.get('scp_eff'))}*\n"
        f"• DCAPE (шквалы): {dcape_text}\n"
        f"• MCS: {_nd_render(report.get('mcsm_interpretation'))}\n\n"
        f"📊 *Дополнительно*\n"
        f"• Showalter: *{_nd_render(report.get('showalter_index'))}* | SWEAT: *{_nd_render(report.get('sweat_index'))}*\n"
        f"• EHI: *{_nd_render(report.get('ehi'))}* | BRN: *{_nd_render(report.get('brn'))}*\n\n"
        f"⚠️ *Уровень угрозы:* {_threat_bar(threat)} *{threat}/5*\n\n"
        f"_Расчёт по доступному профилю. Не заменяет официальный прогноз._"
    )
    return text

def build_skewt_context_for_ai(report: dict, current: dict, pressure_data: dict) -> str:
    hourly = pressure_data.get("hourly", {})
    regime = report.get("regime", "warm")
    lines = ["📊 ПОЛНЫЙ АНАЛИЗ АТМОСФЕРЫ (для AI):"]
    lines.append("=" * 50)
    lines.append(f"Сезонный режим: {regime}")
    if regime == "cool":
        lines.append(
            "❄️ СЕЗОН: холодный сезон (cool). Оценивай thundersnow / snow-squall / "
            "зимнюю конвекцию; не называй её суперячейковой."
        )
    else:
        lines.append("☀️ СЕЗОН: warm — классический конвективный режим.")

    cape = report.get("cape", 0) or 0
    cape_type = _nd_render(report.get("cape_type", "SB"))
    cin = report.get("cin", 0) or 0
    lcl = report.get("lcl", 0) or 0
    lcl_height = report.get("lcl_height_m")
    threat = report.get("threat_level", 0) or 0
    
    lines.append("")
    lines.append("📊 ТЕРМОДИНАМИКА:")
    lines.append(f"  CAPE ({cape_type}): {cape} Дж/кг — " + interpret_cape(cape, regime))
    lines.append(f"  CIN: {abs(cin)} Дж/кг — " + interpret_cin(cin, regime))
    if lcl_height:
        lines.append(f"  LCL: {lcl} гПа (~{int(lcl_height)}м) — {interpret_lcl(lcl_height, regime)}")
    else:
        lines.append(f"  LCL: {lcl} гПа")
    
    lines.append("")
    lines.append("📊 ИНДЕКСЫ УСТОЙЧИВОСТИ:")
    if report.get("k_index"): lines.append(f"  K-Index: {report['k_index']} — {_nd_render(report.get('k_interpretation'))}")
    if report.get("total_totals"): lines.append(f"  Total Totals: {report['total_totals']} — {_nd_render(report.get('tt_interpretation'))}")
    if report.get("lifted_index"): lines.append(f"  Lifted Index: {report['lifted_index']} — {_nd_render(report.get('li_interpretation'))}")
    if report.get("showalter_index"): lines.append(f"  Showalter: {report['showalter_index']} — {_nd_render(report.get('si_interpretation'))}")
    if report.get("sweat_index"): lines.append(f"  SWEAT: {report['sweat_index']} — {_nd_render(report.get('sweat_interpretation'))}")
    
    lines.append("")
    lines.append("📊 ДИНАМИКА (ветер/сдвиг):")
    lines.append(f"  Bulk Shear 0-6км: {_nd_render(report.get('bulk_shear_06'))} м/с — {_nd_render(report.get('shear_interpretation'))}")
    lines.append(f"  Bulk Shear 0-3км: {_nd_render(report.get('bulk_shear_03'))} м/с")
    lines.append(f"  SRH 0-3км: {_nd_render(report.get('srh'))} м²/с² ({_nd_render(report.get('srh_method'))})")
    
    lines.append("")
    lines.append("📊 КОМПОЗИТНЫЕ ИНДЕКСЫ (шторм-чейзинг):")
    ehi = report.get("ehi")
    brn = report.get("brn")
    
    lines.append(f"  🌪 STP (торнадо): {_nd_render(report.get('stp'))} — {_nd_render(report.get('stp_interpretation'))}")
    lines.append(f"  🌪 STP (effective): {_nd_render(report.get('stp_eff'))}")
    lines.append(f"  ⚡ SCP (суперячейки): {_nd_render(report.get('scp'))} — {_nd_render(report.get('scp_interpretation'))}")
    lines.append(f"  ⚡ SCP (effective): {_nd_render(report.get('scp_eff'))}")
    dcape = report.get("dcape")
    dcape_text = (
        "н/д Дж/кг"
        if dcape is None
        else f"{_nd_render(dcape)} Дж/кг — {_nd_render(report.get('dcape_interpretation'))}"
    )
    lines.append(f"  💨 DCAPE (шквалы): {dcape_text}")
    lines.append(f"  📏 MCS Maintenance: {_nd_render(report.get('mcsm_interpretation'))}")
    if ehi: lines.append(f"  EHI (энергия-спиральность): {ehi} — {_nd_render(report.get('ehi_interpretation'))}")
    if brn: lines.append(f"  BRN (Bulk Richardson): {brn} — {_nd_render(report.get('brn_interpretation'))}")
    
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
            prof_p, prof_t, prof_td = build_thermal_profile(current, hourly)
            if len(prof_p) >= 2:
                p, T, Td = (
                    np.array(prof_p) * units.hPa,
                    np.array(prof_t) * units.degC,
                    np.array(prof_td) * units.degC,
                )
                lfc_p, _ = mpcalc.lfc(p, T, Td)
                el_p, _ = mpcalc.el(p, T, Td)
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
    if regime == "cool":
        lines.append("1. Тип зимней конвекции (thundersnow/snow-squall/снежные полосы), а не суперячейки")
    else:
        lines.append("1. Тип ожидаемых гроз (одиночные/мульти/суперячейки/MCS)")
    lines.append("2. Вероятность опасных явлений (торнадо, град, шквалы)")
    lines.append("3. Пробьёт ли конвекция крышку (учитывая CIN и триггеры)")
    lines.append("4. Время максимальной активности (если есть данные о CAPE типе)")
    lines.append("5. Рекомендации для шторм-чейзеров (куда ехать, что искать)")
    lines.append("")
    lines.append("Отвечай на русском, используй эмодзи для наглядности.")
    
    return "\n".join(lines)