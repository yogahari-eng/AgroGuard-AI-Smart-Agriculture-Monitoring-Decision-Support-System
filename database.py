"""
database.py
Single place for all SQLite access. Uses the stdlib sqlite3 module only.
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "agroguard.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create all tables if they do not already exist. Safe to call every startup."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact TEXT UNIQUE NOT NULL,      -- email or phone
            password_hash TEXT NOT NULL,
            farm_name TEXT,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS otp_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact TEXT NOT NULL,
            code TEXT NOT NULL,
            purpose TEXT NOT NULL,             -- 'login' or 'signup'
            expires_at TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sensor_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,              -- real ESP32 hardware
            temperature REAL,
            humidity REAL,
            soil_moisture_raw REAL,
            soil_moisture_pct REAL,
            rain_raw REAL,
            rain_status TEXT,                  -- 'RAIN' / 'NO_RAIN'
            slope_deg REAL,
            terrain_status TEXT,               -- 'STABLE' / 'MOVEMENT_DETECTED'
            timestamp TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pump_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state TEXT NOT NULL,               -- 'ON' / 'OFF'
            mode TEXT NOT NULL,                -- 'AUTO' / 'MANUAL'
            reason TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS crop_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_path TEXT,
            analysis_type TEXT NOT NULL,       -- 'disease' / 'pest'
            prediction TEXT,
            confidence REAL,
            recommendation TEXT,
            timestamp TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            soil_dry_threshold REAL NOT NULL DEFAULT 30,
            soil_wet_threshold REAL NOT NULL DEFAULT 60,
            rain_raw_threshold REAL NOT NULL DEFAULT 2000,
            irrigation_mode TEXT NOT NULL DEFAULT 'AUTO',
            pump_state TEXT NOT NULL DEFAULT 'OFF',
            data_source TEXT NOT NULL DEFAULT 'esp32',        -- retained for backward-compatible DBs
            disease_conf_high REAL NOT NULL DEFAULT 80,
            disease_conf_mid REAL NOT NULL DEFAULT 50
        )
    """)
    cur.execute("SELECT COUNT(*) c FROM settings")
    if cur.fetchone()["c"] == 0:
        cur.execute("INSERT INTO settings (id, data_source) VALUES (1, 'esp32')")
    else:
        cur.execute("UPDATE settings SET data_source='esp32' WHERE id=1")

    conn.commit()
    conn.close()


def get_settings():
    conn = get_db()
    row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    conn.close()
    return dict(row)


def update_settings(**kwargs):
    if not kwargs:
        return
    conn = get_db()
    cols = ", ".join(f"{k} = ?" for k in kwargs)
    conn.execute(f"UPDATE settings SET {cols} WHERE id = 1", list(kwargs.values()))
    conn.commit()
    conn.close()


def now():
    return datetime.utcnow().isoformat()
