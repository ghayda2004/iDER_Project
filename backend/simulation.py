from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import (
    BATTERY_SOC_MIN,
    FACTEUR_EMISSION_CO2_KG_KWH,
    GRID_LIMIT_KW,
    PRIX_ELECTRICITE_EUR_KWH,
    SCENARIOS,
)
from backend.database import get_connection, init_db, load_measurements, save_action, save_kpi
from backend.forecasting import prevoir_demande
from backend.models import Battery, EV, HVAC
from backend.orchestrator import dispatch
from backend.optimizer_lp import optimize_deficit


def build_house_catalog():
    houses = []
    for idx in range(1, 21):
        house_id = f"H{idx:02d}"
        houses.append({
            "id": house_id,
            "has_pv": idx <= 13,
            "has_battery": idx <= 7,
            "has_ev": idx <= 8,
        })
    return houses


def build_resource_objects(scenario, jour):
    batteries = []
    evs = []
    hvacs = []

    measurements = load_measurements(scenario, jour)
    if measurements.empty:
        return batteries, evs, hvacs

    for _, row in measurements.iterrows():
        if row["battery_soc"] and row["battery_soc"] > 0:
            batteries.append(Battery(f"B{len(batteries) + 1:03d}", 10.0, float(row["battery_soc"]), 5.0))
        if row["ev_soc"] and row["ev_soc"] > 0:
            evs.append(EV(f"E{len(evs) + 1:03d}", 60.0, 7.0, bool(row["ev_connected"]), 18, 7, float(row["ev_soc"])))
        hvacs.append(HVAC(f"H{len(hvacs) + 1:03d}", float(row["hvac_kw"]), 0.5, float(row["hvac_kw"])))

    return batteries, evs, hvacs


def run_simulation(mode="rules"):
    init_db()
    conn = get_connection()
    for scenario in SCENARIOS:
        for jour in range(7):
            measurements = load_measurements(scenario, jour)
            if measurements.empty:
                continue
            daily_actions = []
            daily_peak_before = float(measurements["grid_import_kw"].max())
            daily_peak_after = daily_peak_before

            battery_objs = []
            ev_objs = []
            hvac_objs = []
            for _, row in measurements.iterrows():
                if row["battery_soc"] > 0:
                    battery_objs.append(Battery(f"B{len(battery_objs)+1:03d}", 10.0, float(row["battery_soc"]), 5.0))
                if row["ev_soc"] > 0:
                    ev_objs.append(EV(f"E{len(ev_objs)+1:03d}", 60.0, 7.0, bool(row["ev_connected"]), 18, 7, float(row["ev_soc"])))
                hvac_objs.append(HVAC(f"H{len(hvac_objs)+1:03d}", float(row["hvac_kw"]), 0.5, float(row["hvac_kw"])))

            for heure in range(24):
                hour_rows = measurements[measurements["heure"] == heure]
                grid_demand = float(hour_rows["grid_import_kw"].sum())
                forecast = prevoir_demande(measurements, jour, heure + 1)
                if grid_demand > GRID_LIMIT_KW or forecast > GRID_LIMIT_KW:
                    deficit = max(0.0, max(grid_demand, forecast) - GRID_LIMIT_KW)
                    if mode == "lp":
                        actions, remaining = optimize_deficit(deficit, battery_objs, ev_objs, hvac_objs)
                    else:
                        actions, remaining = dispatch(deficit, battery_objs, ev_objs, hvac_objs)
                    for action in actions:
                        save_action(
                            scenario=scenario,
                            jour=jour,
                            heure=heure,
                            device_id=action["device_id"],
                            device_type=action["device_type"],
                            action_type=action["action_type"],
                            power_kw=action["power_kw"],
                            justification=action["justification"],
                        )
                        daily_actions.append({
                            "scenario": scenario,
                            "jour": jour,
                            "heure": heure,
                            **action,
                        })
                    demand_after = max(0.0, grid_demand - sum(abs(item["power_kw"]) for item in actions))
                    daily_peak_after = min(daily_peak_after, demand_after)

            energie_deplacee = sum(abs(action["power_kw"]) for action in daily_actions)
            economie_estimee = (daily_peak_before - daily_peak_after) * PRIX_ELECTRICITE_EUR_KWH
            co2_evite_kg = energie_deplacee * FACTEUR_EMISSION_CO2_KG_KWH
            save_kpi(
                scenario=scenario,
                jour=jour,
                pic_avant_kw=daily_peak_before,
                pic_apres_kw=daily_peak_after,
                energie_deplacee_kwh=energie_deplacee,
                economie_estimee_eur=economie_estimee,
                co2_evite_kg=co2_evite_kg,
            )

    conn.close()
    return True


if __name__ == "__main__":
    run_simulation(mode="rules")
