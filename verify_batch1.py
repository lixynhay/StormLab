import sqlite3
import os
import inspect

def sect(title):
    print("\n" + "=" * 8, title, "=" * 8)

sect("IMPORTS (package layout)")
try:
    from clients.openmeteo_api import OpenMeteoAPI
    from core.storm_indices import build_storm_report
    from alert_manager import check_dangerous_conditions as cdc_probe
    print("openmeteo/storm_indices/alert_manager: import OK")
except Exception as e:
    print("IMPORT FAIL:", type(e).__name__, e)
    raise SystemExit(1)

import clients.sounding_api as sa
print("sounding_api public:", [n for n in dir(sa) if not n.startswith("_")])

api = OpenMeteoAPI()

def probe(lat, lon, label):
    sect(f"LIVE {label} ({lat},{lon})")
    try:
        c = api.get_current(lat, lon)
        print("wind_speed_10m unit:", c.get("current_units", {}).get("wind_speed_10m"))
        p = api.get_pressure_levels(lat, lon)
        r = build_storm_report(c, p)
        print("report keys:", sorted(r.keys()))
        interesting = {k: v for k, v in r.items()
                       if any(t in str(k).lower() for t in ("srh", "shear", "cape", "cin", "stp", "scp"))}
        print("thermo/kin subset:", interesting)
        try:
            sig = inspect.signature(cdc_probe)
            print("check_dangerous_conditions signature:", sig)
            alert = cdc_probe(r)
            print("ALERT RESULT:", alert)
        except Exception as e:
            print("alert call FAIL (нужна другая сигнатура/аргументы):", type(e).__name__, e)
        return r
    except Exception as e:
        print("PROBE FAIL:", type(e).__name__, e)
        return None

probe(35.46756, -97.51643, "OKC")
probe(55.7558, 37.6173, "MOW")

sect("P9 STATIC: sounding_api row.name vs row[\"name\"]")
try:
    src_path = inspect.getsourcefile(sa)
    with open(src_path, encoding="utf-8") as f:
        lines = f.readlines()
    hits = [(i + 1, ln.rstrip()) for i, ln in enumerate(lines)
            if ("row" in ln and "name" in ln) or "_probe_one" in ln]
    for n, ln in hits:
        print(f"{src_path}:{n}: {ln}")
    bad = [ln for _, ln in hits if "row.name" in ln and 'row["name"]' not in ln and "row.get" not in ln]
    print("VERDICT P9:", "still uses row.name -> FIX NEEDED" if bad else "row[\"name\"] / row.get present -> looks patched")
except Exception as e:
    print("P9 static FAIL:", type(e).__name__, e)

sect("P5 SQLITE: sent_at vs UTC now")
try:
    db = os.path.join("data", "alerts.db")
    print("db exists:", os.path.exists(db), db)
    con = sqlite3.connect(db)
    cur = con.cursor()
    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        print("tables:", [t[0] for t in cur.fetchall()])
    except Exception as e:
        print("table list FAIL:", e)
    for tbl in ("alerts", "alert_history", "sent_alerts"):
        try:
            cur.execute(f"SELECT sent_at FROM {tbl} ORDER BY sent_at DESC LIMIT 3")
            rows = cur.fetchall()
            print(f"{tbl}.sent_at last3:", rows)
        except Exception:
            pass
    cur.execute("SELECT datetime('now')")
    print("SQLite UTC now:", cur.fetchone()[0])
    con.close()
except Exception as e:
    print("SQLITE FAIL:", type(e).__name__, e)

print("\nDONE")