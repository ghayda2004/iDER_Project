import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.calibration import calibrer_dataset
from backend.config import (
    BASE_LOAD_MATIN,
    BASE_LOAD_JOURNEE,
    BASE_LOAD_NUIT,
    BASE_LOAD_SOIR,
    BATTERY_SOC_INIT_RANGE,
    BATTERY_SOC_MAX,
    BATTERY_SOC_MIN,
    EV_ARRIVEE_MOYENNE_H,
    EV_SOC_ARRIVEE_RANGE,
    EV_TARGET_SOC,
    FACTEUR_HVAC,
    FACTEUR_PV,
    MAISONS_AVEC_BATTERIE,
    MAISONS_AVEC_EV,
    MAISONS_AVEC_PV,
    NB_JOURS,
    NB_MAISONS,
    SCENARIOS,
)
from backend.database import get_measurement_count, purge_measurements, save_measurement

np.random.seed(42)


def house_profile(house_idx, hour):
    if hour < 6:
        base = BASE_LOAD_NUIT
    elif hour < 10:
        base = BASE_LOAD_MATIN
    elif hour < 17:
        base = BASE_LOAD_JOURNEE
    else:
        base = BASE_LOAD_SOIR

    profile = base + 0.35 * math.sin((hour - 7) / 24 * math.tau)
    profile += (house_idx % 5) * 0.18
    return max(0.3, profile)


def generate_dataset():
    before = get_measurement_count()
    print(f"[Purge] lignes avant purge : {before}")
    purge_measurements()
    after = get_measurement_count()
    print(f"[Purge] lignes après purge : {after}")

    rows = []
    for scenario in SCENARIOS:
        for jour in range(NB_JOURS):
            for maison_idx in range(NB_MAISONS):
                house_id = f"H{maison_idx + 1:02d}"
                has_pv = maison_idx < MAISONS_AVEC_PV
                has_battery = maison_idx < MAISONS_AVEC_BATTERIE
                has_ev = maison_idx < MAISONS_AVEC_EV

                pv_kw = 0.0
                if has_pv:
                    pv_kw = max(0.0, 1.6 + 0.4 * np.random.normal(0, 1.2) + ((maison_idx % 3) * 0.2))

                battery_soc = None
                if has_battery:
                    battery_soc = float(np.random.uniform(*BATTERY_SOC_INIT_RANGE))

                ev_soc = None
                ev_connected = 0
                if has_ev:
                    ev_soc = float(np.random.uniform(*EV_SOC_ARRIVEE_RANGE))
                    arrival = int(np.clip(np.random.normal(EV_ARRIVEE_MOYENNE_H, 1.5), 15, 21))
                    departure = int(np.clip(np.random.normal(EV_ARRIVEE_MOYENNE_H, 1.5), 6, 11))
                    ev_connected = 1 if (0 <= arrival <= 23 and 0 <= departure <= 23) else 0

                for heure in range(24):
                    base_load = house_profile(maison_idx, heure)
                    pv_output = pv_kw if has_pv and 7 <= heure <= 18 else 0.0
                    hvac_kw = 0.65 + 0.40 * (1 if 18 <= heure <= 22 else 0) + 0.15 * (maison_idx % 3)
                    if has_battery:
                        battery_soc = min(BATTERY_SOC_MAX, max(BATTERY_SOC_MIN, battery_soc + 0.15))
                    if has_ev:
                        ev_soc = min(EV_TARGET_SOC, max(0.0, ev_soc + (0.2 if heure >= 20 else 0.0)))

                    rows.append(
                        {
                            "scenario": scenario,
                            "jour": jour,
                            "heure": heure,
                            "house_id": house_id,
                            "base_load_kw": round(float(base_load), 4),
                            "pv_kw": round(float(pv_output), 4),
                            "battery_soc": round(float(battery_soc) if has_battery else 0.0, 2),
                            "ev_soc": round(float(ev_soc) if has_ev else 0.0, 2),
                            "ev_connected": int(ev_connected),
                            "hvac_kw": round(float(hvac_kw), 4),
                            "grid_import_kw": round(max(0.0, base_load + hvac_kw - pv_output), 4),
                        }
                    )

    df = pd.DataFrame(rows)
    calibrated = calibrer_dataset(df, scenario_ref="normal", target_peak_kw=180.0)

    for scenario in SCENARIOS:
        mask = calibrated["scenario"] == scenario
        if scenario == "nuageux":
            calibrated.loc[mask, "pv_kw"] *= FACTEUR_PV[scenario]
        if scenario == "canicule":
            calibrated.loc[mask, "hvac_kw"] *= FACTEUR_HVAC[scenario]
            calibrated.loc[mask, "pv_kw"] *= FACTEUR_PV[scenario]

    calibrated["grid_import_kw"] = np.maximum(
        0.0,
        calibrated["base_load_kw"] + calibrated["hvac_kw"] - calibrated["pv_kw"],
    ).round(4)

    for row in calibrated.to_dict(orient="records"):
        save_measurement(
            scenario=row["scenario"],
            jour=int(row["jour"]),
            heure=int(row["heure"]),
            house_id=row["house_id"],
            base_load_kw=row["base_load_kw"],
            pv_kw=row["pv_kw"],
            battery_soc=row["battery_soc"],
            ev_soc=row["ev_soc"],
            ev_connected=row["ev_connected"],
            hvac_kw=row["hvac_kw"],
            grid_import_kw=row["grid_import_kw"],
        )

    summary = calibrated.groupby("scenario")["grid_import_kw"].max().sort_index()
    print("Résumé génération dataset:")
    for scenario, peak in summary.items():
        print(f"  {scenario:8s}: pic max = {peak:.2f} kW")

    return calibrated


if __name__ == "__main__":
    generate_dataset()
