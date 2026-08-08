import io
import logging
from typing import Optional, Dict, Any, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import metpy.calc as mpcalc
from metpy.plots import SkewT
from metpy.units import units

from storm_indices import SKEWT_LEVELS

logger = logging.getLogger(__name__)

FIG_BG = "#0B132B"
AX_BG = "#101424"
TEXT_COLOR = "#FFFFFF"
GRID_COLOR = "#3A4764"
TEMP_LINE = "#FF4D4D"
DEW_LINE = "#00E5FF"
PARCEL_LINE = "#FFEA00"
CAPE_COLOR = "red"
CIN_COLOR = "deepskyblue"


def _extract_profile_data(hourly: Dict[str, Any]) -> Tuple[List[float], List[float], List[float], List[float], List[float], List[float]]:
    surface_pressure = hourly.get("surface_pressure", [None])[0]
    
    temp_pressures, temps, dews = [], [], []
    pressures, speeds, dirs = [], [], []

    s_temp = hourly.get("temperature_2m", [None])[0]
    s_dew = hourly.get("dew_point_2m", [None])[0]
    s_speed = hourly.get("wind_speed_10m", [None])[0]
    s_dir = hourly.get("wind_direction_10m", [None])[0]

    if all(v is not None for v in [surface_pressure, s_temp, s_dew]):
        temp_pressures.append(float(surface_pressure))
        temps.append(float(s_temp))
        dews.append(float(s_dew))
        
    if all(v is not None for v in [surface_pressure, s_speed, s_dir]):
        pressures.append(float(surface_pressure))
        speeds.append(float(s_speed))
        dirs.append(float(s_dir))

    for lvl in SKEWT_LEVELS:
        if surface_pressure is not None and float(lvl) >= float(surface_pressure):
            continue
            
        t = hourly.get(f"temperature_{lvl}hPa", [None])[0]
        td = hourly.get(f"dew_point_{lvl}hPa", [None])[0]
        s = hourly.get(f"wind_speed_{lvl}hPa", [None])[0]
        d = hourly.get(f"wind_direction_{lvl}hPa", [None])[0]
        
        if t is not None and td is not None:
            temp_pressures.append(float(lvl))
            temps.append(float(t))
            dews.append(float(td))
            
        if s is not None and d is not None:
            pressures.append(float(lvl))
            speeds.append(float(s))
            dirs.append(float(d))
            
    return temp_pressures, temps, dews, pressures, speeds, dirs


def build_profile_chart(pressure_data: dict, city: str, time_label: str) -> Optional[io.BytesIO]:
    try:
        hourly = pressure_data.get("hourly", {})
        temp_pressures, temps, dews, pressures, speeds, dirs = _extract_profile_data(hourly)
        
        if len(temp_pressures) < 2:
            logger.warning("Недостаточно термодинамических данных для построения Skew-T")
            return None
            
        p = np.array(temp_pressures) * units.hPa
        T = np.array(temps) * units.degC
        Td = np.array(dews) * units.degC
        
        fig = plt.figure(figsize=(9, 11), facecolor=FIG_BG)
        skew = SkewT(fig, rotation=45)
        ax = skew.ax
        ax.set_facecolor(AX_BG)
        
        ax.grid(True, which='both', color=GRID_COLOR, linestyle='-', alpha=0.5, linewidth=0.7)
        ax.tick_params(axis='both', colors=TEXT_COLOR, labelsize=10)
        for side in ['bottom', 'top', 'left', 'right']:
            ax.spines[side].set_color(GRID_COLOR)
            
        skew.plot(p, T, TEMP_LINE, linewidth=2.5, label="Температура", zorder=5)
        skew.plot(p, Td, DEW_LINE, linewidth=2.5, label="Точка росы", zorder=4)
        
        try:
            parcel_prof = mpcalc.parcel_profile(p, T[0], Td[0]).to("degC")
            skew.plot(p, parcel_prof, PARCEL_LINE, linestyle="--", linewidth=2, label="Парцель", zorder=6)
            skew.shade_cape(p, T, parcel_prof, facecolor=CAPE_COLOR, alpha=0.2, label="CAPE")
            skew.shade_cin(p, T, parcel_prof, Td, facecolor=CIN_COLOR, alpha=0.2, label="CIN")
        except Exception as e:
            logger.debug(f"Не удалось построить линию парцеля: {e}")
            
        try:
            if len(pressures) >= 2:
                wind_p = np.array(pressures) * units.hPa
                wind_speed = np.array(speeds) * units("m/s")
                wind_dir = np.array(dirs) * units.deg
                u, v = mpcalc.wind_components(wind_speed, wind_dir)
                skew.plot_barbs(wind_p, u, v, color=TEXT_COLOR, length=6, linewidth=1.2, zorder=3)
        except Exception as e:
            logger.debug(f"Не удалось нарисовать ветровые barbs: {e}")
            
        ax.set_ylim(1030, 300)
        ax.set_xlim(-40, 45)
        ax.set_xlabel("Температура (°C)", color=TEXT_COLOR, fontsize=12, fontweight='bold', labelpad=10)
        ax.set_ylabel("Давление (гПа)", color=TEXT_COLOR, fontsize=12, fontweight='bold', labelpad=10)
        ax.set_title(f"{city.upper()}\nВертикальный профиль ({time_label})", 
                     fontsize=14, fontweight="bold", color=TEXT_COLOR, pad=20)
        
        leg = ax.legend(fontsize=10, loc="upper right", frameon=True, facecolor=AX_BG, edgecolor=GRID_COLOR)
        for text in leg.get_texts():
            text.set_color(TEXT_COLOR)
            
        skew.plot_dry_adiabats(linewidth=0.6, alpha=0.15, color='white')
        skew.plot_moist_adiabats(linewidth=0.6, alpha=0.15, color='white')
        skew.plot_mixing_lines(linewidth=0.6, alpha=0.15, color='white')
        
        fig.tight_layout()
        
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=200, facecolor=FIG_BG, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf
        
    except Exception as e:
        logger.error(f"Критическая ошибка построения графика профиля: {e}", exc_info=True)
        return None