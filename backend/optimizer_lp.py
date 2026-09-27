from __future__ import annotations

import math

import pulp


def optimize_deficit(deficit_kw, batteries, evs, hvacs, penalty_weights=None):
    """Optimisation linéaire alternative en mode PuLP.

    Elle minimise une pénalité pondérée où la batterie vaut 1, le VE vaut 2 et
    le chauffage vaut 3, sous la contrainte que la somme des puissances
    allouées couvre exactement le déficit.
    """
    if deficit_kw <= 0:
        return [], 0.0

    if penalty_weights is None:
        penalty_weights = {"battery": 1.0, "ev": 2.0, "hvac": 3.0}

    problem = pulp.LpProblem("ider_dispatch", pulp.LpMinimize)
    variables = []
    objective = []

    for index, battery in enumerate(batteries):
        available = float(battery.flexibilite_disponible())
        if available > 0:
            var = pulp.LpVariable(f"b_{battery.id}", lowBound=0, upBound=min(float(available), float(battery.max_power_kw)))
            variables.append(var)
            objective.append(penalty_weights["battery"] * var)

    for ev in evs:
        available = float(ev.flexibilite_disponible())
        if available > 0:
            var = pulp.LpVariable(f"ev_{ev.id}", lowBound=0, upBound=min(float(available), float(ev.max_charge_kw)))
            variables.append(var)
            objective.append(penalty_weights["ev"] * var)

    for hvac in hvacs:
        available = float(hvac.flexibilite_disponible())
        if available > 0:
            var = pulp.LpVariable(f"h_{hvac.id}", lowBound=0, upBound=float(available))
            variables.append(var)
            objective.append(penalty_weights["hvac"] * var)

    if not variables:
        return [], deficit_kw

    problem += pulp.lpSum(objective)
    problem += pulp.lpSum(variables) >= deficit_kw
    problem.solve(pulp.PULP_CBC_CMD(msg=False))

    actions = []
    allocated = 0.0
    for var in variables:
        value = pulp.value(var)
        if value is None or value <= 0:
            continue
        allocated += float(value)
        actions.append({
            "power_kw": float(value),
            "variable": var.name,
        })

    return actions, max(0.0, deficit_kw - allocated)
