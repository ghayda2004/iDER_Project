"""Schéma SQLite et accès aux données d'iDER.

La base `ider.db` est régénérée par le pipeline (pas de migration de données).
`DB_PATH` est lu à chaque connexion : les tests le remplacent par une base
temporaire avec `monkeypatch`.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "ider.db"

SCHEMA = {
    # Une ligne par scénario, heure et maison. Les grandeurs STEG sont au niveau
    # quartier (table bilan_horaire) : il n'y a plus de colonne grid_import_kw.
    "measurements": """
        CREATE TABLE measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario TEXT NOT NULL,
            date TEXT NOT NULL,
            jour INTEGER NOT NULL,
            heure INTEGER NOT NULL,
            house_id TEXT NOT NULL,
            day_of_week INTEGER NOT NULL,
            is_weekend INTEGER NOT NULL,
            temperature_c REAL NOT NULL,
            irradiance_wm2 REAL NOT NULL,
            steg_available INTEGER NOT NULL,
            base_load_kw REAL NOT NULL,
            hvac_kw REAL NOT NULL,
            ev_charge_kw REAL NOT NULL,
            ev_connected INTEGER NOT NULL,
            ev_soc REAL,
            pv_kw REAL NOT NULL,
            charge_totale_kw REAL NOT NULL,
            UNIQUE (scenario, jour, heure, house_id)
        )""",
    # Sessions de recharge VE (communes à tous les scénarios) : arrivée le jour
    # `jour`, départ le lendemain à `depart_h`.
    "ev_sessions": """
        CREATE TABLE ev_sessions (
            house_id TEXT NOT NULL,
            jour INTEGER NOT NULL,
            date TEXT NOT NULL,
            arrivee_h INTEGER NOT NULL,
            depart_h INTEGER NOT NULL,
            soc_arrivee REAL NOT NULL,
            energie_kwh REAL NOT NULL,
            PRIMARY KEY (house_id, jour)
        )""",
    # Bilan énergétique horaire du quartier pour chaque scénario et mode.
    "bilan_horaire": """
        CREATE TABLE bilan_horaire (
            scenario TEXT NOT NULL,
            mode TEXT NOT NULL,
            date TEXT NOT NULL,
            jour INTEGER NOT NULL,
            heure INTEGER NOT NULL,
            charge_totale_kw REAL NOT NULL,
            pv_kw REAL NOT NULL,
            pv_utilise_kw REAL NOT NULL,
            demande_nette_kw REAL NOT NULL,
            steg_disponible_kw REAL NOT NULL,
            deficit_kw REAL NOT NULL,
            steg_import_kw REAL NOT NULL,
            decharge_batteries_kw REAL NOT NULL,
            recharge_batteries_kw REAL NOT NULL,
            ve_reporte_kw REAL NOT NULL,
            hvac_reduit_kw REAL NOT NULL,
            contribution_der_kw REAL NOT NULL,
            energie_non_desservie_kw REAL NOT NULL,
            depassement_steg_kw REAL NOT NULL,
            ve_non_livre_kwh REAL NOT NULL,
            prevision_demande_nette_kw REAL,
            tarif_tnd_kwh REAL NOT NULL,
            PRIMARY KEY (scenario, mode, jour, heure)
        )""",
    # État horaire de chaque batterie (fin d'heure), pour prouver la continuité.
    "etat_batteries": """
        CREATE TABLE etat_batteries (
            scenario TEXT NOT NULL,
            mode TEXT NOT NULL,
            jour INTEGER NOT NULL,
            heure INTEGER NOT NULL,
            device_id TEXT NOT NULL,
            house_id TEXT NOT NULL,
            soc_debut REAL NOT NULL,
            soc REAL NOT NULL,
            puissance_kw REAL NOT NULL,
            stress_score REAL NOT NULL,
            PRIMARY KEY (scenario, mode, jour, heure, device_id)
        )""",
    "orchestrator_actions": """
        CREATE TABLE orchestrator_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario TEXT NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('reactif', 'predictif')),
            date TEXT NOT NULL,
            jour INTEGER NOT NULL,
            heure INTEGER NOT NULL,
            device_id TEXT NOT NULL,
            device_type TEXT NOT NULL,
            action_type TEXT NOT NULL,
            declencheur TEXT NOT NULL,
            power_kw REAL NOT NULL,
            justification TEXT NOT NULL
        )""",
    "kpi_results": """
        CREATE TABLE kpi_results (
            scenario TEXT NOT NULL,
            mode TEXT NOT NULL,
            date TEXT NOT NULL,
            jour INTEGER NOT NULL,
            pic_steg_avant_kw REAL NOT NULL,
            pic_steg_apres_kw REAL NOT NULL,
            reduction_pic_pct REAL NOT NULL,
            energie_deplacee_kwh REAL NOT NULL,
            energie_steg_avant_kwh REAL NOT NULL,
            energie_steg_apres_kwh REAL NOT NULL,
            consommation_kwh REAL NOT NULL,
            taux_autonomie_pct REAL NOT NULL,
            facture_steg_avant_tnd REAL NOT NULL,
            facture_steg_apres_tnd REAL NOT NULL,
            economie_tnd REAL NOT NULL,
            co2_evite_kg REAL NOT NULL,
            energie_non_desservie_kwh REAL NOT NULL,
            depassement_steg_kwh REAL NOT NULL,
            ve_non_livre_kwh REAL NOT NULL,
            PRIMARY KEY (scenario, mode, jour)
        )""",
    "forecasts": """
        CREATE TABLE forecasts (
            scenario TEXT NOT NULL,
            date TEXT NOT NULL,
            jour INTEGER NOT NULL,
            heure INTEGER NOT NULL,
            cible TEXT NOT NULL CHECK (cible IN ('charge', 'pv', 'demande_nette')),
            y_pred REAL NOT NULL,
            y_true REAL NOT NULL,
            modele TEXT NOT NULL CHECK (modele IN ('ml', 'baseline', 'persistance')),
            split TEXT NOT NULL CHECK (split IN ('train', 'val', 'test'))
        )""",
    "model_metrics": """
        CREATE TABLE model_metrics (
            modele TEXT NOT NULL,
            cible TEXT NOT NULL,
            split TEXT NOT NULL,
            mae_kw REAL,
            rmse_kw REAL,
            mape_pct REAL,
            mae_pointe_kw REAL,
            n_echantillons INTEGER NOT NULL,
            horizon_h INTEGER NOT NULL,
            precision_deficit REAL,
            rappel_deficit REAL,
            vrais_positifs INTEGER,
            faux_positifs INTEGER,
            faux_negatifs INTEGER,
            PRIMARY KEY (modele, cible, split)
        )""",
    "feature_importances": """
        CREATE TABLE feature_importances (
            cible TEXT NOT NULL,
            feature TEXT NOT NULL,
            importance REAL NOT NULL,
            PRIMARY KEY (cible, feature)
        )""",
}

INDEX = [
    "CREATE INDEX idx_measurements_sjh ON measurements (scenario, jour, heure)",
    "CREATE INDEX idx_actions_smj ON orchestrator_actions (scenario, mode, jour)",
    "CREATE INDEX idx_forecasts_mc ON forecasts (modele, cible, scenario, jour)",
]

TABLES_DONNEES = ["measurements", "ev_sessions"]
TABLES_SIMULATION = ["bilan_horaire", "etat_batteries", "orchestrator_actions", "kpi_results"]
TABLES_ML = ["forecasts", "model_metrics", "feature_importances"]


def get_connection():
    return sqlite3.connect(DB_PATH)


def reinitialiser_schema():
    """Supprime toutes les tables (y compris celles d'anciennes versions) et recrée le schéma."""
    with closing(get_connection()) as conn:
        anciennes = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )]
        for table in anciennes:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        for ddl in SCHEMA.values():
            conn.execute(ddl)
        for ddl in INDEX:
            conn.execute(ddl)
        conn.commit()
        conn.execute("VACUUM")


def schema_a_jour():
    """Vrai si toutes les tables attendues existent dans la base."""
    if not Path(DB_PATH).exists():
        return False
    with closing(get_connection()) as conn:
        existantes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    return set(SCHEMA) <= existantes


def vider_tables(tables):
    with closing(get_connection()) as conn:
        for table in tables:
            conn.execute(f"DELETE FROM {table}")
        conn.commit()


def ecrire_table(table, df):
    """Ajoute les lignes d'un DataFrame dans une table existante du schéma."""
    if df.empty:
        return 0
    with closing(get_connection()) as conn:
        df.to_sql(table, conn, if_exists="append", index=False, chunksize=5000)
        conn.commit()
    return len(df)


def lire(query, params=()):
    with closing(get_connection()) as conn:
        return pd.read_sql_query(query, conn, params=params)


def compter_lignes():
    with closing(get_connection()) as conn:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in SCHEMA}


def load_measurements(scenario, jour=None):
    """Mesures d'un scénario (toute la période, ou un seul jour)."""
    if jour is None:
        return lire(
            "SELECT * FROM measurements WHERE scenario = ? ORDER BY jour, heure, house_id",
            (scenario,),
        )
    return lire(
        "SELECT * FROM measurements WHERE scenario = ? AND jour = ? ORDER BY heure, house_id",
        (scenario, jour),
    )


def load_ev_sessions():
    return lire("SELECT * FROM ev_sessions ORDER BY house_id, jour")
