import numpy as np

from metpy.units import units
import metpy.calc as mpcalc


EFFECTIVE_CONSTANTS = {
    "CAPE_MIN_LAYER": 100,
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
    "EBWD_MIN": 12.5,
    "EBWD_MAX": 30,
    "SCP_CAPE_NORM": 1000,
    "SCP_SRH_NORM": 50,
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


def find_effective_layer(profile):
    z, u, v, p, t, td = _profile_arrays(profile)
    if len(z) < 2:
        return None

    order = np.argsort(z)
    z, u, v, p, t, td = z[order], u[order], v[order], p[order], t[order], td[order]

    for i, z_bot in enumerate(z):
        if i + 1 >= len(z):
            break
        if len(p) == len(z) and len(t) == len(z) and len(td) == len(z):
            try:
                p_sub = p[i:] * units.hPa
                t_sub = t[i:] * units.degC
                td_sub = td[i:] * units.degC
                ml_t, ml_td = mpcalc.mix(p_sub, t_sub, td_sub, depth=100 * units.hPa)
                lcl_p, lcl_t = mpcalc.lcl(p_sub[0], ml_t, ml_td)
                parcel_profile = mpcalc.parcel_profile(p_sub, ml_t, ml_td)
                el_p, el_t = mpcalc.el(p_sub, t_sub, td_sub, parcel_profile)
                cape, _ = mpcalc.mixed_layer_cape_cin(p_sub, t_sub, td_sub, depth=100 * units.hPa)
                cape_value = float(cape.to("J/kg").magnitude) if cape is not None else 0.0
                if el_p is not None:
                    idx = np.argmin(np.abs(p - el_p.magnitude))
                    z_top = float(z[idx])
                else:
                    z_top = float(z[-1])
                if cape_value >= EFFECTIVE_CONSTANTS["CAPE_MIN_LAYER"] and z_top - z_bot >= EFFECTIVE_CONSTANTS["LAYER_DEPTH_MIN"]:
                    return z_bot, z_top
            except Exception:
                pass

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


def effective_bulk_shear(profile, z_bot, z_top):
    z, u, v, _, _, _ = _profile_arrays(profile)
    if len(z) == 0:
        return 0.0

    top = min(z_top, EFFECTIVE_CONSTANTS["ESRH_TOP_CLIP"])
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


def stp_effective(mucape, mllcl, esrh, ebwd, mlcin):
    if mucape is None or esrh is None or ebwd is None or mlcin is None:
        return None
    if ebwd < EFFECTIVE_CONSTANTS["EBWD_MIN"]:
        return 0.0
    if mucape <= 0:
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
        (mucape / EFFECTIVE_CONSTANTS["STP_CAPE_NORM"])
        * lcl_term
        * (esrh / EFFECTIVE_CONSTANTS["STP_SRH_NORM"])
        * (capped_ebwd / EFFECTIVE_CONSTANTS["STP_SHEAR_NORM"])
        * cin_term
    )


def scp_effective(mucape, esrh, ebwd):
    if mucape is None or esrh is None or ebwd is None:
        return None
    if ebwd < EFFECTIVE_CONSTANTS["EBWD_MIN"]:
        return 0.0
    if mucape <= 0:
        return 0.0

    capped_ebwd = min(ebwd, EFFECTIVE_CONSTANTS["EBWD_MAX"])
    return float(
        (mucape / EFFECTIVE_CONSTANTS["SCP_CAPE_NORM"])
        * (esrh / EFFECTIVE_CONSTANTS["SCP_SRH_NORM"])
        * (capped_ebwd / EFFECTIVE_CONSTANTS["STP_SHEAR_NORM"])
    )
