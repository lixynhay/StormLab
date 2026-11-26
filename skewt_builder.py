import io
import logging
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import metpy.calc as mpcalc
from metpy.plots import SkewT
from metpy.units import units
from storm_indices import PRESSURE_LEVELS, build_wind_profile
from chart_builder import _serialized_matplotlib_render

logger = logging.getLogger(__name__)

DARK_BG = "#0a0e1a"
PANEL_BG = "#111827"
GRID_COLOR = "#1f2937"
AXIS_COLOR = "#9ca3af"
TEXT_COLOR = "#f9fafb"
ACCENT = "#fbbf24"

TEMP_COLOR = "#ef4444"
DEW_COLOR = "#3b82f6"
PARCEL_COLOR = "#fbbf24"
CAPE_COLOR = "#dc262644"
CIN_COLOR = "#1d4ed844"

BARB_COLORS = [
    (0, "#22c55e"),
    (10, "#84cc16"),
    (15, "#eab308"),
    (20, "#f97316"),
    (25, "#ef4444"),
    (35, "#dc2626"),
]

def _barb_color(speed_ms):
    s = speed_ms if isinstance(speed_ms, (int, float)) else 0
    for threshold, color in BARB_COLORS:
        if s < threshold:
            return color
    return "#7f1d1d"

def _select_spaced_barbs(ax, pressures, min_spacing_px=18):
    pressure_values = np.asarray(pressures.to("hPa").magnitude, dtype=float)
    points = np.column_stack((np.zeros(len(pressure_values)), pressure_values))
    y_pixels = ax.transData.transform(points)[:, 1]
    selected = []
    for index in np.argsort(y_pixels):
        if all(abs(y_pixels[index] - y_pixels[previous]) >= min_spacing_px
               for previous in selected):
            selected.append(index)
    return np.asarray(sorted(selected), dtype=int)


def _add_clear_label(ax, label, x, y, occupied_boxes, color=TEXT_COLOR, fontsize=6):
    candidates = [
        (6, 5, "left", "bottom"), (6, -8, "left", "top"),
        (-6, 5, "right", "bottom"), (-6, -8, "right", "top"),
        (8, 0, "left", "center"), (-8, 0, "right", "center"),
    ]
    renderer = ax.figure.canvas.get_renderer()
    for offset_x, offset_y, horizontal, vertical in candidates:
        artist = ax.annotate(
            label, (x, y), xytext=(offset_x, offset_y), textcoords="offset points",
            ha=horizontal, va=vertical, color=color, fontsize=fontsize,
            fontweight="bold", annotation_clip=True,
        )
        ax.figure.canvas.draw()
        extent = artist.get_window_extent(renderer)
        padded_extent = extent.padded(3)
        if not any(padded_extent.overlaps(box) for box in occupied_boxes):
            occupied_boxes.append(padded_extent)
            return artist
        artist.remove()
        renderer = ax.figure.canvas.get_renderer()
    return None


def _draw_skewt(skew, current, hourly, city, time_label, indices_text=None):
    pressures, speeds, dirs = build_wind_profile(current, hourly, PRESSURE_LEVELS)
    surface_pressure = current.get("surface_pressure") or 1013.25
    surface_temp = current.get("temperature_2m")
    surface_dewpoint = current.get("dew_point_2m")

    temp_levels, temperatures = [], []
    dewpoint_levels, dewpoints = [], []
    paired_levels, paired_temperatures, paired_dewpoints = [], [], []

    def add_level(level, temperature, dewpoint):
        if temperature is not None:
            temp_levels.append(float(level))
            temperatures.append(float(temperature))
        if dewpoint is not None:
            dewpoint_levels.append(float(level))
            dewpoint_value = float(dewpoint)
            dewpoints.append(min(dewpoint_value, float(temperature))
                             if temperature is not None else dewpoint_value)
        if temperature is not None and dewpoint is not None:
            paired_levels.append(float(level))
            paired_temperatures.append(float(temperature))
            paired_dewpoints.append(min(float(dewpoint), float(temperature)))

    add_level(surface_pressure, surface_temp, surface_dewpoint)

    for lvl in PRESSURE_LEVELS:
        if lvl < surface_pressure:
            t = hourly.get(f"temperature_{lvl}hPa", [None])[0]
            td = hourly.get(f"dew_point_{lvl}hPa", [None])[0]
            add_level(lvl, t, td)

    if len(temp_levels) < 2:
        return None, None

    temp_order = np.argsort(temp_levels)[::-1]
    dewpoint_order = np.argsort(dewpoint_levels)[::-1]
    temp_levels = np.asarray(temp_levels)[temp_order]
    temperatures = np.asarray(temperatures)[temp_order]
    dewpoint_levels = np.asarray(dewpoint_levels)[dewpoint_order]
    dewpoints = np.asarray(dewpoints)[dewpoint_order]
    paired_order = np.argsort(paired_levels)[::-1]
    paired_levels = np.asarray(paired_levels)[paired_order]
    paired_temperatures = np.asarray(paired_temperatures)[paired_order]
    paired_dewpoints = np.asarray(paired_dewpoints)[paired_order]

    p_temp = temp_levels * units.hPa
    T = temperatures * units.degC
    p_dewpoint = dewpoint_levels * units.hPa
    Td = dewpoints * units.degC
    p = paired_levels * units.hPa
    paired_T = paired_temperatures * units.degC
    paired_Td = paired_dewpoints * units.degC
    ax = skew.ax
    ax.set_facecolor(PANEL_BG)
    ax.grid(True, which="both", color=GRID_COLOR, linestyle="-", alpha=0.55, linewidth=0.7)

    skew.plot(p_temp, T, TEMP_COLOR, linewidth=2.7, label="T: Температура")
    if len(p_dewpoint):
        skew.plot(p_dewpoint, Td, DEW_COLOR, linewidth=2.7, label="Td: Точка росы")

    parcel_prof = None
    if len(p) >= 2:
        try:
            parcel_prof = mpcalc.parcel_profile(p, paired_T[0], paired_Td[0]).to("degC")
            skew.plot(p, parcel_prof, PARCEL_COLOR, linestyle="--", linewidth=2.2,
                      label="Парцель")
            skew.shade_cape(p, paired_T, parcel_prof, color=CAPE_COLOR)
            skew.shade_cin(p, paired_T, parcel_prof, paired_Td, color=CIN_COLOR)
        except Exception as e:
            logger.warning(f"Парцель не построен: {e}")

        try:
            lcl_p, _ = mpcalc.lcl(p[0], paired_T[0], paired_Td[0])
            if lcl_p is not None and np.isfinite(lcl_p.magnitude):
                ax.axhline(lcl_p.magnitude, color=ACCENT, linestyle=":",
                           alpha=0.75, linewidth=1.3, zorder=2)
                ax.annotate(
                    f"LCL {lcl_p.magnitude:.0f} гПа",
                    (0.02, lcl_p.magnitude), xycoords=ax.get_yaxis_transform(),
                    xytext=(10, -9), textcoords="offset points",
                    color=ACCENT, fontsize=8, va="top", fontweight="bold",
                    bbox={"facecolor": PANEL_BG, "edgecolor": GRID_COLOR,
                          "alpha": 0.95, "pad": 2.5},
                )
        except Exception:
            pass

    if parcel_prof is not None and len(p) >= 2:
        try:
            lfc_p, _ = mpcalc.lfc(p, paired_T, paired_Td, parcel_prof)
            if lfc_p is not None and np.isfinite(lfc_p.magnitude):
                ax.axhline(lfc_p.magnitude, color="#22c55e", linestyle=":",
                           alpha=0.7, linewidth=1.2)
                ax.text(0.02, lfc_p.magnitude, "LFC", transform=ax.get_yaxis_transform(),
                        color="#22c55e", fontsize=8, va="bottom", fontweight="bold",
                        bbox={"facecolor": PANEL_BG, "edgecolor": "none", "alpha": 0.9, "pad": 1})
        except Exception:
            pass
        try:
            el_p, _ = mpcalc.el(p, paired_T, paired_Td, parcel_prof)
            if el_p is not None and np.isfinite(el_p.magnitude):
                ax.axhline(el_p.magnitude, color="#a855f7", linestyle=":",
                           alpha=0.7, linewidth=1.2)
                ax.text(0.02, el_p.magnitude, "EL", transform=ax.get_yaxis_transform(),
                        color="#a855f7", fontsize=8, va="bottom", fontweight="bold",
                        bbox={"facecolor": PANEL_BG, "edgecolor": "none", "alpha": 0.9, "pad": 1})
        except Exception:
            pass

    ax.set_ylim(1030, 200)
    ax.set_xlim(-40, 45)
    ax.grid(True, which="both", color=GRID_COLOR, linestyle="-", alpha=0.55, linewidth=0.7)

    skew.plot_dry_adiabats(linewidth=0.6, alpha=0.35, color=GRID_COLOR)
    skew.plot_moist_adiabats(linewidth=0.6, alpha=0.35, color=GRID_COLOR)
    skew.plot_mixing_lines(linewidth=0.6, alpha=0.35, color=GRID_COLOR)

    if len(pressures) >= 2:
        try:
            wind_p = np.array(pressures) * units.hPa
            wind_speed = np.array(speeds) * units("m/s")
            wind_dir = np.array(dirs) * units.deg
            u, v = mpcalc.wind_components(wind_speed, wind_dir)
            ax.figure.canvas.draw()
            barb_indices = _select_spaced_barbs(ax, wind_p)
            if len(barb_indices):
                skew.plot_barbs(
                    wind_p[barb_indices], u[barb_indices], v[barb_indices],
                    color=_barb_color(np.mean(np.asarray(speeds)[barb_indices])),
                    length=5.5, linewidth=1.1,
                )
        except Exception as e:
            logger.warning(f"Wind barbs: {e}")

    for spine in ax.spines.values():
        spine.set_color(AXIS_COLOR)
    ax.tick_params(colors=AXIS_COLOR, labelsize=8)
    ax.set_xlabel("Температура (°C)", fontsize=10, color=TEXT_COLOR)
    ax.set_ylabel("Давление (гПа)", fontsize=10, color=TEXT_COLOR)

    ax.legend(fontsize=8, loc="upper right", facecolor=PANEL_BG,
                   edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR)
    ax.set_title(f"Штормовой профиль: {city} • {time_label}",
                      fontsize=13, color=TEXT_COLOR, pad=12, fontweight="bold")
    return skew, (pressures, speeds, dirs, p, u if len(pressures) >= 2 else None,
                  v if len(pressures) >= 2 else None)

def _draw_hodograph(ax, pressures, speeds, dirs):
    if pressures is None or len(pressures) < 3:
        ax.set_visible(False)
        return
    try:
        p = np.array(pressures) * units.hPa
        speed = np.array(speeds) * units("m/s")
        direction = np.array(dirs) * units.deg
        u, v = mpcalc.wind_components(speed, direction)

        ax.set_facecolor(PANEL_BG)
        for spine in ax.spines.values():
            spine.set_color(AXIS_COLOR)
        ax.tick_params(colors=AXIS_COLOR, labelsize=7)
        ax.set_aspect("equal")
        ax.axhline(0, color=GRID_COLOR, linewidth=0.8)
        ax.axvline(0, color=GRID_COLOR, linewidth=0.8)

        for r in [10, 20, 30, 40]:
            ax.add_patch(plt.Circle((0, 0), r, fill=False,
                                    edgecolor=GRID_COLOR, linewidth=0.6, alpha=0.6))

        u_ms = u.to("m/s").magnitude
        v_ms = v.to("m/s").magnitude

        for i in range(1, len(u_ms)):
            speed_avg = (speeds[i-1] + speeds[i]) / 2 if speeds[i-1] and speeds[i] else 0
            ax.plot(u_ms[i-1:i+1], v_ms[i-1:i+1],
                    color=_barb_color(speed_avg), linewidth=2.5)

        label_data = []
        for i, pres in enumerate(pressures):
            if int(round(pres)) in [1000, 925, 850, 700, 500, 300]:
                ax.scatter([u_ms[i]], [v_ms[i]], s=40, color=ACCENT,
                           edgecolor=TEXT_COLOR, linewidth=1, zorder=5)
                label_data.append((str(int(round(pres))), u_ms[i], v_ms[i], TEXT_COLOR))

        ax.scatter([u_ms[0]], [v_ms[0]], s=80, color="#22c55e",
                   edgecolor=TEXT_COLOR, linewidth=1.5, zorder=6)
        label_data.append(("SFC", u_ms[0], v_ms[0], "#22c55e"))

        ax.set_xlim(-50, 50)
        ax.set_ylim(-50, 50)
        ax.set_title("Hodograph (u/v м/с)",
                     fontsize=9, color=TEXT_COLOR, pad=6, fontweight="bold")
        ax.figure.canvas.draw()
        occupied_boxes = []
        for label, x, y, color in label_data:
            _add_clear_label(ax, label, x, y, occupied_boxes, color=color, fontsize=6)
    except Exception as e:
        logger.warning(f"Hodograph failed: {e}")
        ax.set_visible(False)

def _draw_indices_box(ax, current, hourly, indices_text=None):
    ax.set_facecolor(PANEL_BG)
    for spine in ax.spines.values():
        spine.set_color(AXIS_COLOR)
    ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)

    surface_temp = current.get("temperature_2m")
    surface_td = current.get("dew_point_2m")
    surface_p = current.get("surface_pressure")

    info_lines = []
    if surface_temp is not None:
        info_lines.append(f"T: {surface_temp:.1f}°C")
    if surface_td is not None:
        info_lines.append(f"Td: {surface_td:.1f}°C")
    if surface_p is not None:
        info_lines.append(f"P: {surface_p:.0f} гПа")
    if surface_temp is not None and surface_td is not None:
        spread = surface_temp - surface_td
        info_lines.append(f"Spread: {spread:.1f}°C")

    y_pos = 0.92
    ax.text(0.05, y_pos, "УСЛОВИЯ У ПОВЕРХНОСТИ",
            transform=ax.transAxes, fontsize=10, color=ACCENT,
            fontweight="bold")
    y_pos -= 0.08

    for line in info_lines:
        ax.text(0.05, y_pos, line, transform=ax.transAxes,
                fontsize=9, color=TEXT_COLOR, family="monospace")
        y_pos -= 0.06

    if indices_text:
        y_pos -= 0.03
        ax.text(0.05, y_pos, "КЛЮЧЕВЫЕ ИНДЕКСЫ",
                transform=ax.transAxes, fontsize=10, color=ACCENT,
                fontweight="bold")
        y_pos -= 0.08
        for line in indices_text.split("\n"):
            if line.strip():
                ax.text(0.05, y_pos, line, transform=ax.transAxes,
                        fontsize=8.5, color=TEXT_COLOR, family="monospace")
                y_pos -= 0.05

def _format_indices_for_box(report):
    if not report:
        return None
    lines = []
    cape_type = report.get("cape_type", "")
    cape = report.get("cape", 0) or 0
    cin = abs(report.get("cin", 0) or 0)
    lcl = report.get("lcl", 0)
    lines.append(f"CAPE[{cape_type}]: {cape:.0f} Дж/кг")
    lines.append(f"CIN: {cin:.0f} Дж/кг")
    lines.append(f"LCL: {lcl:.0f} гПа")
    stp = report.get("stp")
    scp = report.get("scp")
    dcape = report.get("dcape")
    if stp is not None:
        lines.append(f"STP: {stp:.2f}")
    if scp is not None:
        lines.append(f"SCP: {scp:.2f}")
    if dcape is not None:
        lines.append(f"DCAPE: {dcape:.0f}")
    threat = report.get("threat_level")
    if threat is not None:
        lines.append(f"УГРОЗА: {threat}/5")
    return "\n".join(lines)

def _draw_sounding_skewt(skew, df, run_time, station_name):
    p = df["pressure"].values * units.hPa
    T = df["temperature"].values * units.degC
    Td = df["dewpoint"].values * units.degC
    ax = skew.ax
    Td_display = np.minimum(Td, T)
    ax.set_facecolor(PANEL_BG)
    ax.grid(True, which="both", color=GRID_COLOR, linestyle="-", alpha=0.55, linewidth=0.7)
    skew.plot(p, T, TEMP_COLOR, linewidth=2.5)
    skew.plot(p, Td_display, DEW_COLOR, linewidth=2.5)

    try:
        parcel_prof = mpcalc.parcel_profile(p, T[0], Td_display[0]).to("degC")
        skew.plot(p, parcel_prof, PARCEL_COLOR, linestyle="--", linewidth=2)
        skew.shade_cape(p, T, parcel_prof, color=CAPE_COLOR)
        skew.shade_cin(p, T, parcel_prof, Td_display, color=CIN_COLOR)
    except Exception:
        pass

    try:
        u = df["u_wind"].values * units.knot
        v = df["v_wind"].values * units.knot
        interval = np.logspace(2, 3, 20) * units.hPa
        idx = mpcalc.resample_nn_1d(p, interval)
        barb_p = p[idx]
        ax.figure.canvas.draw()
        barb_indices = _select_spaced_barbs(ax, barb_p)
        if len(barb_indices):
            skew.plot_barbs(barb_p[barb_indices], u[idx][barb_indices], v[idx][barb_indices],
                            color=ACCENT, length=5.5, linewidth=1.1)
    except Exception:
        pass

    ax.set_ylim(1030, 200)
    ax.set_xlim(-40, 45)
    ax.grid(True, which="both", color=GRID_COLOR, linestyle="-", alpha=0.55, linewidth=0.7)
    skew.plot_dry_adiabats(linewidth=0.6, alpha=0.35, color=GRID_COLOR)
    skew.plot_moist_adiabats(linewidth=0.6, alpha=0.35, color=GRID_COLOR)
    skew.plot_mixing_lines(linewidth=0.6, alpha=0.35, color=GRID_COLOR)
    ax.set_title(f"Зонд: {station_name} • {run_time:%d.%m %H:%MZ}",
                      fontsize=12, color=TEXT_COLOR, pad=10, fontweight="bold")

    for spine in ax.spines.values():
        spine.set_color(AXIS_COLOR)
    ax.tick_params(colors=AXIS_COLOR, labelsize=8)
    ax.set_xlabel("Температура (°C)", fontsize=10, color=TEXT_COLOR)
    ax.set_ylabel("Давление (гПа)", fontsize=10, color=TEXT_COLOR)
    return skew

@_serialized_matplotlib_render
def build_skewt_chart(current, hourly, sounding_df=None, sounding_run_time=None,
                      city="Город", time_label="Сейчас", station_name="Зонд",
                      report=None):
    """Render observations at raw pressure levels; display interpolation is disabled.

    Parcel, CAPE/CIN shading, LCL/LFC/EL and all other calculations use the raw
    available co-located T/Td levels. Display interpolation is intentionally off.
    """
    fig = None
    try:
        has_sounding = sounding_df is not None and len(sounding_df) > 0

        plt.rcParams.update({
            "figure.facecolor": DARK_BG,
            "text.color": TEXT_COLOR,
            "font.family": "DejaVu Sans",
        })

        indices_text = _format_indices_for_box(report)

        if has_sounding:
            fig = plt.figure(figsize=(16, 9))
            gs = fig.add_gridspec(1, 2, width_ratios=[1.3, 1])

            skew_model = SkewT(fig=fig, rotation=45, subplot=gs[0, 0])
            result = _draw_skewt(skew_model, current, hourly, city, time_label, indices_text)
            if result is None or result[0] is None:
                return None

            skew_sounding = SkewT(fig=fig, rotation=45, subplot=gs[0, 1])
            _draw_sounding_skewt(skew_sounding, sounding_df, sounding_run_time, station_name)
        else:
            fig = plt.figure(figsize=(14, 9))
            gs = gridspec.GridSpec(2, 2, figure=fig,
                                   width_ratios=[2, 1],
                                   height_ratios=[2, 1],
                                   hspace=0.25, wspace=0.25)

            skew = SkewT(fig=fig, rotation=45, subplot=gs[0, :])
            result = _draw_skewt(skew, current, hourly, city, time_label, indices_text)
            if result is None or result[0] is None:
                return None

            skew, wind_data = result
            pressures, speeds, dirs = wind_data[0], wind_data[1], wind_data[2]

            ax_hodo = fig.add_subplot(gs[1, 0])
            _draw_hodograph(ax_hodo, pressures, speeds, dirs)

            ax_info = fig.add_subplot(gs[1, 1])
            _draw_indices_box(ax_info, current, hourly, indices_text)

        fig.text(0.5, 0.01,
                 "StormLab • MetPy + Open-Meteo • " +
                 ("Реальный зонд + модель" if has_sounding else "Только модель (fallback)"),
                 ha="center", fontsize=9, color=AXIS_COLOR, style="italic")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=180, bbox_inches="tight", facecolor=DARK_BG)
        buf.seek(0)
        return buf
    except Exception as e:
        logger.error(f"Skew-T: {e}", exc_info=True)
        return None
    finally:
        if fig is not None:
            plt.close(fig)