import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path("data/alerts.db")

THRESHOLDS = {
    "cape_min": 1000,
    "shear_06_min": 15,
    "lcl_max": 1500,
    "cin_max": 150,
}

ALERT_COOLDOWN_HOURS = 2


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
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
    conn.close()
    logger.info("Alert database initialized")


def add_alert(user_id: int, username: Optional[str], city: str, lat: float, lon: float) -> bool:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR IGNORE INTO alerts (user_id, username, city, lat, lon)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, username, city, lat, lon))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
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
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            DELETE FROM alerts WHERE user_id = ? AND city = ?
        """, (user_id, city))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        if success:
            logger.info(f"Alert removed: user={user_id}, city={city}")
        
        return success
    except Exception as e:
        logger.error(f"Failed to remove alert: {e}")
        return False


def get_user_alerts(user_id: int) -> List[Dict]:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT city, lat, lon, created_at FROM alerts WHERE user_id = ?
            ORDER BY created_at DESC
        """, (user_id,))
        
        results = cursor.fetchall()
        conn.close()
        
        return [
            {
                "city": row[0],
                "lat": row[1],
                "lon": row[2],
                "created_at": row[3]
            }
            for row in results
        ]
    except Exception as e:
        logger.error(f"Failed to get user alerts: {e}")
        return []


def get_all_alerts() -> List[Dict]:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT user_id, username, city, lat, lon FROM alerts
        """)
        
        results = cursor.fetchall()
        conn.close()
        
        return [
            {
                "user_id": row[0],
                "username": row[1],
                "city": row[2],
                "lat": row[3],
                "lon": row[4]
            }
            for row in results
        ]
    except Exception as e:
        logger.error(f"Failed to get all alerts: {e}")
        return []


def can_send_alert(user_id: int, city: str) -> bool:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cutoff = datetime.now() - timedelta(hours=ALERT_COOLDOWN_HOURS)
        
        cursor.execute("""
            SELECT COUNT(*) FROM alert_history
            WHERE user_id = ? AND city = ? AND sent_at > ?
        """, (user_id, city, cutoff))
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count == 0
    except Exception as e:
        logger.error(f"Failed to check alert cooldown: {e}")
        return False


def record_alert_sent(user_id: int, city: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO alert_history (user_id, city) VALUES (?, ?)
        """, (user_id, city))
        
        conn.commit()
        conn.close()
        logger.debug(f"Alert recorded: user={user_id}, city={city}")
    except Exception as e:
        logger.error(f"Failed to record alert: {e}")


def check_dangerous_conditions(report: Dict) -> Optional[str]:
    try:
        cape = report.get("cape") or 0
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
        
        if cape >= THRESHOLDS["cape_min"]:
            reasons.append(f"CAPE {cape} Дж/кг")
        
        if shear_06 >= THRESHOLDS["shear_06_min"]:
            reasons.append(f"сдвиг 0-6 км {shear_06} м/с")
        
        if lcl_meters is not None and 0 < lcl_meters <= THRESHOLDS["lcl_max"]:
            reasons.append(f"низкий LCL ({int(lcl_meters)} м)")
        
        if cin <= THRESHOLDS["cin_max"]:
            reasons.append(f"слабая крышка (CIN {cin} Дж/кг)")
        
        if len(reasons) >= 3:
            reason_text = ", ".join(reasons)
            return f"⚠️ Высокий риск организованных гроз: {reason_text}"
        
        if cape >= 2000 and shear_06 >= 20:
            return f"⚠️ Высокий риск суперячеек: CAPE {cape} Дж/кг + сдвиг {shear_06} м/с"
        
        return None
    except Exception as e:
        logger.error(f"Failed to check dangerous conditions: {e}")
        return None

def _self_check():
    """Минимальная проверка логики порогов (используется тестами)."""
    hot = {"cape": 2500, "bulk_shear_06": 25, "cin": -50, "lcl": 850.0}
    calm = {"cape": 100, "bulk_shear_06": 3, "cin": -300, "lcl": 900.0}
    assert check_dangerous_conditions(hot) is not None, "dangerous profile must trigger alert"
    assert check_dangerous_conditions(calm) is None, "calm profile must not trigger alert"
    return True


init_db()