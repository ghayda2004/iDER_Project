import sqlite3
from pathlib import Path

import pandas as pd

from backend.config import SCENARIOS

DB_PATH = Path(__file__).resolve().parent.parent / "ider.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario TEXT, jour INTEGER, heure INTEGER, house_id TEXT,
            base_load_kw REAL, pv_kw REAL, battery_soc REAL, ev_soc REAL,
            ev_connected INTEGER, hvac_kw REAL, grid_import_kw REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orchestrator_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario TEXT, jour INTEGER, heure INTEGER,
            device_id TEXT, device_type TEXT, action_type TEXT,
            power_kw REAL, justification TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kpi_results (
            scenario TEXT, jour INTEGER,
            pic_avant_kw REAL, pic_apres_kw REAL,
            energie_deplacee_kwh REAL, economie_estimee_eur REAL,
            co2_evite_kg REAL
        )
        """
    )
    conn.commit()
    conn.close()


def save_measurement(scenario, jour, heure, house_id, base_load_kw, pv_kw, battery_soc, ev_soc,
                     ev_connected, hvac_kw, grid_import_kw):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO measurements (
            scenario, jour, heure, house_id, base_load_kw, pv_kw, battery_soc, ev_soc,
            ev_connected, hvac_kw, grid_import_kw
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scenario,
            jour,
            heure,
            house_id,
            float(base_load_kw),
            float(pv_kw),
            float(battery_soc),
            float(ev_soc),
            int(ev_connected),
            float(hvac_kw),
            float(grid_import_kw),
        ),
    )
    conn.commit()
    conn.close()


def save_action(scenario, jour, heure, device_id, device_type, action_type, power_kw, justification):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO orchestrator_actions (
            scenario, jour, heure, device_id, device_type, action_type, power_kw, justification
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scenario,
            jour,
            heure,
            device_id,
            device_type,
            action_type,
            float(power_kw),
            justification,
        ),
    )
    conn.commit()
    conn.close()


def save_kpi(scenario, jour, pic_avant_kw, pic_apres_kw, energie_deplacee_kwh, economie_estimee_eur, co2_evite_kg):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO kpi_results (
            scenario, jour, pic_avant_kw, pic_apres_kw, energie_deplacee_kwh, economie_estimee_eur, co2_evite_kg
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scenario,
            jour,
            float(pic_avant_kw),
            float(pic_apres_kw),
            float(energie_deplacee_kwh),
            float(economie_estimee_eur),
            float(co2_evite_kg),
        ),
    )
    conn.commit()
    conn.close()


def purge_measurements(scenario=None, jour=None):
    conn = get_connection()
    if scenario is None and jour is None:
        conn.execute("DELETE FROM measurements")
    elif scenario is not None and jour is None:
        conn.execute("DELETE FROM measurements WHERE scenario = ?", (scenario,))
    elif scenario is not None and jour is not None:
        conn.execute("DELETE FROM measurements WHERE scenario = ? AND jour = ?", (scenario, jour))
    else:
        conn.execute("DELETE FROM measurements WHERE jour = ?", (jour,))
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
    conn.close()
    return count


def get_measurement_count():
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
    conn.close()
    return count


def load_measurements(scenario, jour):
    conn = get_connection()
    df = pd.read_sql_query(
        """
        SELECT *
        FROM measurements
        WHERE scenario = ? AND jour = ?
        ORDER BY heure, house_id
        """,
        conn,
        params=(scenario, jour),
    )
    conn.close()
    return df


init_db()
