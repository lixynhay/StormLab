import warnings

import numpy as np

from metpy.units import units
import metpy.calc as mpcalc


EFFECTIVE_CONSTANTS = {
    "CAPE_MIN_LAYER": 100,
    # SPC: "Effective Inflow Layer = the first layer in a sounding where all contiguous
    # lifted parcels have CAPE >= 100 J kg-1 and CIN >= -250 J kg-1."
    # https://www.spc.noaa.gov/exper/mesoanalysis/help/begin.html
    "CIN_MIN_LAYER": -250,
    "LAYER_DEPTH_MIN": 50,
    "ESRH_TOP_CLIP": 10000,
    "STP_CAPE_NORM": 1500,
    "STP_LCL_NUM": 2000,
    "STP_LCL_DEN": 1000,
    "STP_LCL_CAP": (0, 1),
    "STP_SRH_NORM": 150,
    "STP_SHEAR_NORM": 20,
    "STP_CIN_NUM": 200,
    "STP_CIN_DEN": 150,
    "STP_CIN_CAP": (0, 1),
    "STP_CIN_ZERO": -200,
    # SPC effective STP: "...the EBWD term is capped at 1.5 for EBWD > 30 m s-1,
    # and set to 0.0 for EBWD < 12.5 m s-1..."
    # https://www.spc.noaa.gov/exper/mesoanalysis/help/begin.html
    "EBWD_MIN": 12.5,
    "EBWD_MAX": 30,
    # SPC: "...bulk vector shear from the 'effective inflow base' upward to 50% of
    # the equilibrium level height with the most unstable parcel in the lowest 300 mb."
    # https://www.spc.noaa.gov/exper/mesoanalysis/help/begin.html
    "EBWD_EL_FRACTION": 0.5,
    "SCP_CAPE_NORM": 1000,
    "SCP_SRH_NORM": 50,
    # SPC SCP: "EBWD is divided by 20 m s-1 in the range of 10-20 m s-1. EBWD less
    # than 10 m s-1 is set to zero, and EBWD greater than 20 m s-1 is set to one."
    # https://www.spc.noaa.gov/exper/mesoanalysis/help/help_scp.html
    "SCP_EBWD_MIN": 10,
    "SCP_EBWD_MAX": 20,
    # SPC SCP: "...the muCIN term ... is set to 1.0 when muCIN is greater than -40 kg-1."
    # https://www.spc.noaa.gov/exper/mesoanalysis/help/help_scp.html
    "SCP_CIN_THRESHOLD": -40,
    "EBWD_LOWER": "base",
}


def _profile_arrays(profile):
    if hasattr(profile, "pressure"):
        p = np.asarray(profile.pressure)
        z = np.asarray(profile.height)
        u = np.asarray(profile.u)
        v = np.asarray(profile.v)
        t = np.asarray(profile.temperature)
        td = np.asarray(profile.dewpoint)
    else:
        z = np.asarray(profile.get("z", profile.get("heights", [])), dtype=float)
        u = np.asarray(profile.get("u", profile.get("wind_u", [])), dtype=float)
        v = np.asarray(profile.get("v", profile.get("wind_v", [])), dtype=float)
        p = np.asarray(profile.get("p", profile.get("pressure", [])), dtype=float)
        t = np.asarray(profile.get("T", profile.get("temperature", [])), dtype=float)
        td = np.asarray(profile.get("Td", profile.get("dewpoint", [])), dtype=float)
    return z, u, v, p, t, td


def _sorted_thermo(profile):
    """Return z, p, t, td sorted by height, or None if unusable."""
    z, _, _, p, t, td = _profile_arrays(profile)
    if len(z) < 2 or not (len(p) == len(z) == len(t) == len(td)):
        return None
    order = np.argsort(z)
    z, p, t, td = z[order], p[order], t[order], td[order]
    if np.any(np.diff(z) <= 0) or np.any(np.diff(p) >= 0):
        return None
    return z, p, t, td


def _parcel_cape_cin(p, t, td, i):
    """CAPE/CIN of the parcel lifted from level i (SPC: 'lifted parcels')."""
    p_sub = p[i:] * units.hPa
    t_sub = t[i:] * units.degC
    td_sub = td[i:] * units.degC
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parcel = mpcalc.parcel_profile(p_sub, t_sub[0], td_sub[0])
        cape, cin = mpcalc.cape_cin(p_sub, t_sub, td_sub, parcel)
    cape_v = float(np.nan_to_num(cape.to("J/kg").magnitude, nan=0.0))
    cin_v = float(np.nan_to_num(cin.to("J/kg").magnitude, nan=-999.0))
    return cape_v, cin_v


def _parcel_el_height(p, t, td, i, z):
    try:
        p_sub = p[i:] * units.hPa
        t_sub = t[i:] * units.degC
        td_sub = td[i:] * units.degC
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parcel = mpcalc.parcel_profile(p_sub, t_sub[0], td_sub[0])
            el_p, _ = mpcalc.el(p_sub, t_sub, td_sub, parcel)
        if el_p is not None:
            el_value = float(el_p.magnitude)
            if np.isfinite(el_value):
                return float(np.interp(el_value, p[::-1], z[::-1]))
    except Exception:
        pass
    return float(z[-1])


def find_effective_layer(profile):
    """Effective inflow layer: first layer with parcel CAPE >= 100 and CIN >= -250.

    SPC: "the first layer in a sounding where all contiguous lifted parcels have
    CAPE >= 100 J kg-1 and CIN >= -250 J kg-1" and "...continue to look upward in
    the sounding until a lifted parcel has a CAPE less than 100 Jkg-1 OR a CIN less
    than -250 J kg-1."
    https://www.spc.noaa.gov/exper/mesoanalysis/help/begin.html
    https://www.spc.noaa.gov/exper/mesoanalysis/help/help_esrh.html

    Returns (base_height, top_height) in metres, or None when no parcel in the
    sounding meets the inflow-layer gates.
    """
    thermo = _sorted_thermo(profile)
    if thermo is None:
        return None
    z, p, t, td = thermo

    cape = np.full(len(z), 0.0)
    cin = np.full(len(z), -999.0)
    for i in range(len(z) - 1):
        try:
            cape[i], cin[i] = _parcel_cape_cin(p, t, td, i)
        except Exception:
            continue

    run_start = None
    run_last = None
    for i in range(len(z)):
        ok = (
            cape[i] >= EFFECTIVE_CONSTANTS["CAPE_MIN_LAYER"]
            and cin[i] >= EFFECTIVE_CONSTANTS["CIN_MIN_LAYER"]
        )
        if ok:
            if run_start is None:
                run_start = i
            run_last = i
        elif run_start is not None:
            if z[run_last] - z[run_start] >= EFFECTIVE_CONSTANTS["LAYER_DEPTH_MIN"]:
                # Top boundary: first level where CAPE < 100 or CIN < -250.
                return float(z[run_start]), float(z[i])
            run_start = None

    if run_start is not None and z[run_last] - z[run_start] >= EFFECTIVE_CONSTANTS["LAYER_DEPTH_MIN"]:
        # Layer never closes inside the profile: fall back to the parcel EL.
        return float(z[run_start]), float(_parcel_el_height(p, t, td, run_start, z))
    return None


def effective_srh(profile, z_bot, z_top, storm_motion):
    z, u, v, _, _, _ = _profile_arrays(profile)
    if len(z) == 0 or len(u) == 0 or len(v) == 0:
        return 0.0

    cx = float(np.asarray(storm_motion[0]).item())
    cy = float(np.asarray(storm_motion[1]).item())
    top = min(z_top, EFFECTIVE_CONSTANTS["ESRH_TOP_CLIP"])

    order = np.argsort(z)
    z, u, v = z[order], u[order], v[order]
    srh = 0.0
    for i in range(len(z) - 1):
        za, zb = float(z[i]), float(z[i + 1])
        lo = max(za, z_bot)
        hi = min(zb, top)
        if hi <= lo:
            continue

        if za == zb:
            continue
        frac_a = (lo - za) / (zb - za)
        frac_b = (hi - za) / (zb - za)
        ua = float(u[i]) + frac_a * (float(u[i + 1]) - float(u[i]))
        va = float(v[i]) + frac_a * (float(v[i + 1]) - float(v[i]))
        ub = float(u[i]) + frac_b * (float(u[i + 1]) - float(u[i]))
        vb = float(v[i]) + frac_b * (float(v[i + 1]) - float(v[i]))

        srh += 0.5 * (va + vb - 2 * cy) * (ub - ua)
        srh -= 0.5 * (ua + ub - 2 * cx) * (vb - va)

    return float(srh)


def most_unstable_el_height(profile):
    """EL height of the most unstable parcel in the lowest 300 hPa (SPC EBWD)."""
    thermo = _sorted_thermo(profile)
    if thermo is None:
        return None
    z, p, t, td = thermo
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            p_mu, t_mu, td_mu, idx = mpcalc.most_unstable_parcel(
                p * units.hPa, t * units.degC, td * units.degC, depth=300 * units.hPa
            )
            parcel = mpcalc.parcel_profile(p[idx:] * units.hPa, t_mu, td_mu)
            el_p, _ = mpcalc.el(
                p[idx:] * units.hPa, t[idx:] * units.degC, td[idx:] * units.degC, parcel
            )
        if el_p is not None:
            el_value = float(el_p.magnitude)
            if np.isfinite(el_value):
                return float(np.interp(el_value, p[::-1], z[::-1]))
    except Exception:
        pass
    # Truncated sounding: the profile top is the best available EL estimate.
    return float(z[-1])


def effective_bulk_shear(profile, z_bot, el_height):
    """EBWD = |V(0.5 * EL) - V(effective inflow base)|.

    SPC: "Effective Bulk Wind Difference = magnitude of the bulk vector shear from
    the 'effective inflow base' upward to 50% of the equilibrium level height with
    the most unstable parcel in the lowest 300 mb."
    https://www.spc.noaa.gov/exper/mesoanalysis/help/begin.html
    """
    z, u, v, _, _, _ = _profile_arrays(profile)
    if len(z) == 0 or el_height is None:
        return 0.0
    if not np.isfinite(float(el_height)) or float(el_height) <= 0:
        return 0.0

    top = EFFECTIVE_CONSTANTS["EBWD_EL_FRACTION"] * float(el_height)
    order = np.argsort(z)
    z, u, v = z[order], u[order], v[order]

    def wind_at(target):
        if target <= z[0]:
            return float(u[0]), float(v[0])
        if target >= z[-1]:
            return float(u[-1]), float(v[-1])
        i = int(np.searchsorted(z, target, side="right") - 1)
        i = min(max(i, 0), len(z) - 2)
        frac = (target - z[i]) / (z[i + 1] - z[i])
        return (float(u[i] + frac * (u[i + 1] - u[i])),
                float(v[i] + frac * (v[i + 1] - v[i])))

    base_u, base_v = wind_at(z_bot)
    top_u, top_v = wind_at(top)
    return float(np.hypot(top_u - base_u, top_v - base_v))


def stp_effective(mlcape, mllcl, esrh, ebwd, mlcin, base_height_m=0.0, surface_height_m=0.0):
    """Effective-layer STP, exactly as defined by SPC.

    SPC: "STP = (mlCAPE / 1500 J kg-1) * ((2000 - mlLCL) / 1000 m) *
    (ESRH / 150 m2 s-2) * (EBWD / 20 m s-1) * ((mlCIN + 200) / 150 J kg-1) ...
    the entire index is set to 0.0 when the effective inflow base is above the ground."
    https://www.spc.noaa.gov/exper/mesoanalysis/help/begin.html
    """
    if mlcape is None or esrh is None or ebwd is None or mlcin is None:
        return None
    if base_height_m > surface_height_m:
        # "the entire index is set to 0.0 when the effective inflow base is above the ground"
        return 0.0
    if ebwd < EFFECTIVE_CONSTANTS["EBWD_MIN"]:
        return 0.0
    if mlcape <= 0:
        return 0.0

    if mllcl is not None:
        if mllcl > EFFECTIVE_CONSTANTS["STP_LCL_NUM"]:
            lcl_term = 0.0
        else:
            lcl_term = float(np.clip(
                (EFFECTIVE_CONSTANTS["STP_LCL_NUM"] - mllcl) / EFFECTIVE_CONSTANTS["STP_LCL_DEN"],
                *EFFECTIVE_CONSTANTS["STP_LCL_CAP"],
            ))
    else:
        lcl_term = 1.0

    if mlcin < EFFECTIVE_CONSTANTS["STP_CIN_ZERO"]:
        cin_term = 0.0
    else:
        cin_term = float(np.clip(
            (EFFECTIVE_CONSTANTS["STP_CIN_NUM"] + mlcin) / EFFECTIVE_CONSTANTS["STP_CIN_DEN"],
            *EFFECTIVE_CONSTANTS["STP_CIN_CAP"],
        ))

    capped_ebwd = min(ebwd, EFFECTIVE_CONSTANTS["EBWD_MAX"])
    return float(
        (mlcape / EFFECTIVE_CONSTANTS["STP_CAPE_NORM"])
        * lcl_term
        * (esrh / EFFECTIVE_CONSTANTS["STP_SRH_NORM"])
        * (capped_ebwd / EFFECTIVE_CONSTANTS["STP_SHEAR_NORM"])
        * cin_term
    )


def scp_effective(mucape, esrh, ebwd, mucin=0.0):
    """Effective-layer SCP, exactly as defined by SPC.

    SPC: "SCP = (muCAPE / 1000 J kg-1) * (ESRH / 50 m2 s-2) * (EBWD / 20 m s-1) *
    (-40 J kg-1 / muCIN) ... EBWD less than 10 m s-1 is set to zero, and EBWD
    greater than 20 m s-1 is set to one ... the muCIN term ... is set to 1.0 when
    muCIN is greater than -40 kg-1."
    https://www.spc.noaa.gov/exper/mesoanalysis/help/help_scp.html
    """
    if mucape is None or esrh is None or ebwd is None:
        return None
    if ebwd < EFFECTIVE_CONSTANTS["SCP_EBWD_MIN"]:
        return 0.0
    if mucape <= 0:
        return 0.0

    capped_ebwd = min(ebwd, EFFECTIVE_CONSTANTS["SCP_EBWD_MAX"])
    if mucin == 0 or mucin >= EFFECTIVE_CONSTANTS["SCP_CIN_THRESHOLD"]:
        cin_term = 1.0
    else:
        cin_term = EFFECTIVE_CONSTANTS["SCP_CIN_THRESHOLD"] / mucin

    return float(
        (mucape / EFFECTIVE_CONSTANTS["SCP_CAPE_NORM"])
        * (esrh / EFFECTIVE_CONSTANTS["SCP_SRH_NORM"])
        * (capped_ebwd / EFFECTIVE_CONSTANTS["STP_SHEAR_NORM"])
        * cin_term
    )
