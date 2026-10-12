"""Validation d'optimalité du dispatch par règles (hors boucle principale de simulation).

Le LP minimise un coût de mobilisation (batterie 1, VE 2, HVAC 3 par kW) sous
les mêmes bornes de flexibilité que le dispatch par règles. On compare, heure
de déficit par heure de déficit, le coût du LP à celui des règles appliquées
au même état des ressources. Les règles peuvent coûter plus cher que le LP à
cause du plafond d'équité à 50 % sur les batteries : c'est le prix de la
répartition de l'usure, que le LP ignore.
"""

from __future__ import annotations

import copy
import sys
import warnings
from pathlib import Path

import pandas as pd
import pulp

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import STEG_CAPACITY_KW
from backend.database import load_ev_sessions, load_measurements
from backend.orchestrator import dispatch

COUTS = {"battery": 1.0, "ev": 2.0, "hvac": 3.0}
COUT_NON_COUVERT = 1000.0

with warnings.catch_warnings():
    # CBC est le seul solveur livré avec PuLP 3.x ; son constructeur annonce une dépréciation pour PuLP 4.
    warnings.simplefilter("ignore", DeprecationWarning)
    SOLVEUR = pulp.PULP_CBC_CMD(msg=False)


def optimize_deficit(deficit_kw, batteries, evs, hvacs, couts=None):
    """Allocation LP du déficit (kW). Retourne (allocations, déficit non couvert) sans modifier les objets."""
    if deficit_kw <= 0:
        return [], 0.0
    couts = couts or COUTS
    problem = pulp.LpProblem("ider_dispatch", pulp.LpMinimize)
    variables = []
    for device_type, ressources in (("battery", batteries), ("ev", evs), ("hvac", hvacs)):
        for ressource in ressources:
            borne = float(ressource.flexibilite_disponible())
            if device_type == "battery":
                borne = min(borne, float(ressource.max_power_kw))
            if borne > 0:
                var = problem.add_variable(f"{device_type}_{ressource.id}".replace("-", "_"), lowBound=0, upBound=borne)
                variables.append((var, ressource.id, device_type))
    non_couvert = problem.add_variable("non_couvert", lowBound=0)
    problem += pulp.lpSum(couts[t] * v for v, _, t in variables) + COUT_NON_COUVERT * non_couvert
    problem += pulp.lpSum(v for v, _, _ in variables) + non_couvert == deficit_kw
    problem.solve(SOLVEUR)

    allocations = [
        {"device_id": device_id, "device_type": device_type, "power_kw": float(pulp.value(var))}
        for var, device_id, device_type in variables
        if pulp.value(var) and pulp.value(var) > 1e-9
    ]
    return allocations, float(pulp.value(non_couvert) or 0.0)


def cout_mobilisation(actions, couts=None):
    couts = couts or COUTS
    return sum(couts[a["device_type"]] * a["power_kw"] for a in actions)


def comparer_lp_regles(deficit_kw, batteries, evs, hvacs, couts=None):
    """Compare règles et LP sur le même état (les objets d'origine ne sont pas modifiés)."""
    regles, residuel_regles = dispatch(deficit_kw, *copy.deepcopy((batteries, evs, hvacs)))
    lp, residuel_lp = optimize_deficit(deficit_kw, *copy.deepcopy((batteries, evs, hvacs)), couts=couts)
    return {
        "deficit_kw": deficit_kw,
        "cout_regles": cout_mobilisation(regles, couts) + COUT_NON_COUVERT * residuel_regles,
        "cout_lp": cout_mobilisation(lp, couts) + COUT_NON_COUVERT * residuel_lp,
        "non_couvert_regles_kw": residuel_regles,
        "non_couvert_lp_kw": residuel_lp,
    }


def valider_scenario(scenario="normal", steg_capacity=STEG_CAPACITY_KW):
    """Rejoue le mode réactif et compare règles et LP à chaque heure de déficit."""
    from backend.simulation import preparer_entrees, simuler_scenario

    comparaisons = []

    def observer(t, deficit, batteries, evs, hvacs):
        comparaisons.append({"t": t, **comparer_lp_regles(deficit, batteries, evs, hvacs)})

    entrees = preparer_entrees(load_measurements(scenario))
    simuler_scenario(entrees, load_ev_sessions(), scenario, "reactif", steg_capacity, observateur=observer)
    return pd.DataFrame(comparaisons)


if __name__ == "__main__":
    resultats = valider_scenario()
    ecart = resultats["cout_regles"] - resultats["cout_lp"]
    print(f"Heures de déficit comparées : {len(resultats)}")
    print(f"Coût total règles : {resultats['cout_regles'].sum():.2f} | coût total LP : {resultats['cout_lp'].sum():.2f}")
    print(f"Heures où les règles coûtent plus que le LP : {(ecart > 1e-6).sum()} (écart max {ecart.max():.2f})")
