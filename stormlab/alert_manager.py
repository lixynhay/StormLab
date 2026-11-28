"""Alert subscriptions and seasonal danger checks.

Three distinct CAPE numbers are deliberately NOT unified:
- ``CAPE_FLOOR`` (alert_manager): early exit "is there any convection at all?"
  -- warm 250, cool 100. Below the alert threshold in both regimes.
- ``thresholds_for(regime)['cape_min']`` (core.season_regime): the real alert
  condition, one of the >=3 conditions -- warm 1000, cool 200.
- ``low_cape_floor`` (core.storm_indices.calculate_threat_level): first threat
  score point -- warm 250, cool 150. A different mechanism (report score), not
  the alert gate; it does not decide whether an alert is sent.
"""

import sqlite3
import logging
from contextlib import contextmanager
from typing import List, Dict, Optional

from stormlab.config import MAX_ALERTS_PER_USER
from stormlab.paths import DATA_DIR
from stormlab.core.season_regime import thresholds_for

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "alerts.db"

ALERT_COOLDOWN_HOURS = 2

# CAPE floor is a cheap "is there any convection?" early exit, NOT the alert
# threshold. It must sit BELOW the seasonal threshold so real cool-season
# convection (CAPE 200-250) is not silently killed:
#   warm: floor 250 < threshold 1000
#   cool: floor 100 < threshold 200
# NOTE: the cool threat-score first-ball floor lives in
# core.storm_indices.calculate_threat_level and is 150, NOT 100. Different
# mechanism (score point), intentionally a different constant.
CAPE_FLOOR = {"warm": 250, "cool": 100}


@contextmanager
def _connect():
    """Every SQLite connection is closed even when a query raises."""
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with _connect() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                city TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, city)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                city TEXT NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    logger.info("Alert database initialized")


def location_key(lat, lon):
    """Coarse coordinate key: subscriptions to the same city share one API request."""
    return (round(float(lat), 2), round(float(lon), 2))


def get_user_location_keys(user_id: int) -> set:
    """Unique rounded coordinates already subscribed by the user."""
    try:
        with _connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT lat, lon FROM alerts WHERE user_id = ?", (user_id,))
            return {
                location_key(lat, lon)
                for lat, lon in cursor.fetchall()
                if lat is not None and lon is not None
            }
    except Exception as e:
        logger.error(f"Failed to get alert locations: {e}")
        return set()


def group_alerts_by_location(alerts: List[Dict]) -> Dict[tuple, List[Dict]]:
    """Group subscriptions by rounded coordinates so one city = one weather fetch."""
    groups: Dict[tuple, List[Dict]] = {}
    for alert in alerts:
        lat, lon = alert.get("lat"), alert.get("lon")
        if lat is not None and lon is not None:
            key = location_key(lat, lon)
        else:
            key = ("city", alert.get("city"))
        groups.setdefault(key, []).append(alert)
    return groups


def add_alert(user_id: int, username: Optional[str], city: str, lat: float, lon: float) -> bool:
    try:
        with _connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT lat, lon FROM alerts WHERE user_id = ?", (user_id,))
            keys = {
                location_key(row_lat, row_lon)
                for row_lat, row_lon in cursor.fetchall()
                if row_lat is not None and row_lon is not None
            }
            key = location_key(lat, lon)
            if key not in keys and len(keys) >= MAX_ALERTS_PER_USER:
                logger.info(
                    f"Alert limit reached: user={user_id}, unique_locations={len(keys)}, "
                    f"max={MAX_ALERTS_PER_USER}"
                )
                return False

            cursor.execute("""
                INSERT OR IGNORE INTO alerts (user_id, username, city, lat, lon)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, username, city, lat, lon))
            success = cursor.rowcount > 0
            conn.commit()

        if success:
            logger.info(f"Alert added: user={user_id}, city={city}")
        else:
            logger.info(f"Alert already exists: user={user_id}, city={city}")
        return success
    except Exception as e:
        logger.error(f"Failed to add alert: {e}")
        return False


def remove_alert(user_id: int, city: str) -> bool:
    try:
        with _connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM alerts WHERE user_id = ? AND city = ?", (user_id, city)
            )
            success = cursor.rowcount > 0
            conn.commit()
        if success:
            logger.info(f"Alert removed: user={user_id}, city={city}")
        return success
    except Exception as e:
        logger.error(f"Failed to remove alert: {e}")
        return False


def get_user_alerts(user_id: int) -> List[Dict]:
    try:
        with _connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT city, lat, lon, created_at FROM alerts WHERE user_id = ?
                ORDER BY created_at DESC
            """, (user_id,))
            results = cursor.fetchall()
        return [
            {
                "city": row[0], "lat": row[1], "lon": row[2], "created_at": row[3]
            }
            for row in results
        ]
    except Exception as e:
        logger.error(f"Failed to get user alerts: {e}")
        return []


def get_all_alerts() -> List[Dict]:
    try:
        with _connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, username, city, lat, lon FROM alerts")
            results = cursor.fetchall()
        return [
            {
                "user_id": row[0], "username": row[1], "city": row[2],
                "lat": row[3], "lon": row[4]
            }
            for row in results
        ]
    except Exception as e:
        logger.error(f"Failed to get all alerts: {e}")
        return []


def can_send_alert(user_id: int, city: str) -> bool:
    try:
        with _connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM alert_history
                WHERE user_id = ? AND city = ? AND sent_at > datetime('now', ?)
            """, (user_id, city, f"-{ALERT_COOLDOWN_HOURS} hours"))
            count = cursor.fetchone()[0]
        return count == 0
    except Exception as e:
        logger.error(f"Failed to check alert cooldown: {e}")
        return False


def record_alert_sent(user_id: int, city: str):
    try:
        with _connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO alert_history (user_id, city) VALUES (?, ?)", (user_id, city)
            )
            conn.commit()
        logger.debug(f"Alert recorded: user={user_id}, city={city}")
    except Exception as e:
        logger.error(f"Failed to record alert: {e}")


def check_dangerous_conditions(report: Dict, regime: str = "warm") -> Optional[str]:
    """Check a storm report against seasonal alert thresholds.

    ``CAPE_FLOOR`` is only an early exit ("any convection at all?"), while
    ``thresholds_for(regime)`` holds the real alert conditions. The floor is
    deliberately lower than the threshold in both regimes so cool-season
    CAPE 200-250 can still produce a thundersnow/snow-squall alert.

    Distinct numbers (not a typo):
    - alert floor (this function): warm 250, cool 100;
    - alert threshold ``cape_min`` (one of >=3 conditions): warm 1000, cool 200;
    - threat-score first ball (calculate_threat_level, separate mechanism):
      warm 250, cool 150. It never gates an alert.
    """
    try:
        thresholds = thresholds_for(regime)
        cape = report.get("cape") or 0
        if cape < CAPE_FLOOR.get(regime, CAPE_FLOOR["warm"]):
            return None
        shear_06 = report.get("bulk_shear_06") or 0
        cin = abs(report.get("cin") or 0)

        # LCL в отчёте хранится в гПа; берём уже рассчитанную высоту, иначе конвертируем
        lcl_meters = report.get("lcl_height_m")
        if lcl_meters is None:
            lcl = report.get("lcl")
            if lcl and 0 < lcl < 1013.25:
                lcl_meters = (1 - (lcl / 1013.25) ** 0.190284) * 44330
            else:
                lcl_meters = None

        reasons = []

        if cape >= thresholds["cape_min"]:
            reasons.append(f"CAPE {cape} Дж/кг")

        if shear_06 >= thresholds["shear06_min"]:
            reasons.append(f"сдвиг 0-6 км {shear_06} м/с")

        if lcl_meters is not None and 0 < lcl_meters <= thresholds["lcl_max"]:
            reasons.append(f"низкий LCL ({int(lcl_meters)} м)")

        if cin <= thresholds["cin_max"]:
            reasons.append(f"слабая крышка (CIN {cin} Дж/кг)")

        if len(reasons) >= 3:
            reason_text = ", ".join(reasons)
            if regime == "cool":
                return f"❄️ Высокий риск зимней конвекции (thundersnow/snow-squall): {reason_text}"
            return f"⚠️ Высокий риск организованных гроз: {reason_text}"

        if cape >= thresholds["cape_min"] and shear_06 >= thresholds["shear06_min"]:
            if regime == "cool":
                return (
                    f"❄️ Высокий риск thundersnow / snow-squall: "
                    f"CAPE {cape} Дж/кг + сдвиг {shear_06} м/с"
                )
            return f"⚠️ Высокий риск суперячеек: CAPE {cape} Дж/кг + сдвиг {shear_06} м/с"

        return None
    except Exception as e:
        logger.error(f"Failed to check dangerous conditions: {e}")
        return None


def prune_history(max_age_days: int = 30) -> int:
    """Delete alert_history rows older than max_age_days (coold-safe)."""
    try:
        with _connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM alert_history WHERE sent_at < datetime('now', ?)",
                (f"-{int(max_age_days)} days",),
            )
            deleted = cursor.rowcount
            conn.commit()
        if deleted:
            logger.info(f"Pruned {deleted} old alert_history rows")
        return deleted
    except Exception as e:
        logger.error(f"Failed to prune alert history: {e}")
        return 0


init_db()
