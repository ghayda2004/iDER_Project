"""Simulation horaire du quartier : STEG source de base, DER pour couvrir le déficit.

Chaque scénario est simulé comme une chronologie continue (jour 0 00h ->
dernier jour 23h) dans trois modes :

- `sans_orchestration` : référence « avant ». STEG fournit toute la demande
  nette, même au-delà de sa capacité (dépassement). Batteries non pilotées,
  VE rechargés dès l'arrivée, PV autoconsommé.
- `reactif` : à chaque heure, le déficit observé est couvert par batteries ->
  VE -> HVAC ; les batteries se rechargent (surplus PV, heures creuses).
- `predictif` : idem, plus des actions anticipées à partir de la prévision ML
  de l'heure suivante ; la couverture réactive reste le filet de sécurité.

Bilan horaire (vérifié par les tests) :
    steg_import + contribution_DER + pv_utilise + energie_non_desservie = charge_totale
où charge_totale inclut la recharge des batteries et la demande VE avant report.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import (
    FORECAST_SAFETY_MARGIN,
    HEURES_CREUSES,
    MAISONS_AVEC_BATTERIE,
    MODES,
    SCENARIOS,
    SOC_CIBLE,
    SOC_MAX,
    STEG_CAPACITY_KW,
    tarif_tnd_kwh,
)
from backend.database import (
    TABLES_SIMULATION,
    ecrire_table,
    load_ev_sessions,
    load_measurements,
    vider_tables,
)
from backend.kpi import agreger_quartier, calculer_kpi
from backend.models import EV, HVAC, Battery
from backend.orchestrator import ORDRE_DELESTAGE, ORDRE_MERITE, dispatch, fmt

EPS = 1e-9


def preparer_entrees(measurements):
    """Agrégats horaires du quartier et demande HVAC par maison pour un scénario."""
    quartier = agreger_quartier(measurements)
    hvac = (
        measurements.pivot_table(index=["jour", "heure"], columns="house_id", values="hvac_kw", aggfunc="sum")
        .sort_index()
    )
    return {"quartier": quartier, "hvac": hvac}


def recharger(batteries, puissance_kw, soc_cible):
    """Répartit une puissance de recharge entre les batteries, les plus vides d'abord."""
    details = []
    for battery in sorted(batteries, key=lambda b: b.soc):
        if puissance_kw <= EPS:
            break
        absorbee = battery.charger(puissance_kw, soc_cible)
        if absorbee > EPS:
            details.append((battery, absorbee))
            puissance_kw -= absorbee
    return details


def simuler_scenario(entrees, sessions, scenario, mode, steg_capacity=STEG_CAPACITY_KW, previsions=None,
                     observateur=None):
    """Simule un scénario sur toute la période dans un mode ; aucune écriture en base.

    `previsions` : tableau aligné sur les heures (index t) de la demande nette
    prévue pour l'heure t (faite à t-1), NaN si indisponible. Requis en mode
    prédictif. `observateur(t, deficit_kw, batteries, evs, hvacs)` est appelé
    juste avant chaque dispatch (utilisé par la validation LP).
    """
    quartier = entrees["quartier"]
    hvac_matrice = entrees["hvac"]
    n_heures = len(quartier)
    orchestre = mode != "sans_orchestration"
    predictif = mode == "predictif"
    if predictif and previsions is None:
        raise ValueError("Le mode prédictif nécessite des prévisions.")
    previsions = np.full(n_heures, np.nan) if previsions is None else np.asarray(previsions, dtype=float)
    pic_prevu = np.nan_to_num(previsions, nan=0.0) * (1 + FORECAST_SAFETY_MARGIN) > steg_capacity

    house_ids = list(hvac_matrice.columns)
    batteries = [Battery(f"BAT-{h}", house_id=h) for h in house_ids[:MAISONS_AVEC_BATTERIE]]
    hvacs = [HVAC(f"CLIM-{h}", house_id=h) for h in house_ids]
    ev_houses = sorted(sessions["house_id"].unique())
    evs = [EV(f"VE-{h}", house_id=h) for h in ev_houses]
    arrivees = {}
    for row in sessions.itertuples():
        t_arrivee = int(row.jour) * 24 + int(row.arrivee_h)
        arrivees.setdefault(t_arrivee, []).append(
            (row.house_id, (int(row.jour) + 1) * 24 + int(row.depart_h), int(row.depart_h), float(row.soc_arrivee), float(row.energie_kwh))
        )
    ev_par_maison = {ev.house_id: ev for ev in evs}

    jours = quartier["jour"].to_numpy()
    heures = quartier["heure"].to_numpy()
    dates = quartier["date"].to_numpy()
    base = quartier["base_load_kw"].to_numpy()
    pv = quartier["pv_kw"].to_numpy()
    disponible = quartier["steg_available"].to_numpy()
    hvac_valeurs = hvac_matrice.to_numpy()

    bilan, actions, etats = [], [], []
    for t in range(n_heures):
        jour, heure, date = int(jours[t]), int(heures[t]), dates[t]
        steg_dispo = steg_capacity if disponible[t] else 0.0
        coupure = not disponible[t]

        # Départs puis arrivées des VE
        ve_non_livre = 0.0
        for ev in evs:
            if ev.connected and t >= ev.t_depart:
                ve_non_livre += ev.debrancher()
        for house_id, t_depart, depart_h, soc_arrivee, energie in arrivees.get(t, []):
            ev_par_maison[house_id].brancher(t, t_depart, depart_h, soc_arrivee, energie)
        for ev in evs:
            ev.debut_heure(t)
        for hvac, demande in zip(hvacs, hvac_valeurs[t]):
            hvac.debut_heure(float(demande))
        for battery in batteries:
            battery.debut_heure()

        ev_demande = sum(ev.demande_kw() for ev in evs)
        hvac_demande = float(hvac_valeurs[t].sum())
        charge_hors_recharge = float(base[t]) + hvac_demande + ev_demande
        recharge = 0.0
        anticipe = 0.0
        heure_actions = []

        def tracer(device, device_type, action_type, declencheur, puissance, justification):
            heure_actions.append({
                "device_id": device.id, "device_type": device_type, "action_type": action_type,
                "declencheur": declencheur, "power_kw": puissance, "justification": justification,
            })

        if orchestre:
            # (b) Prédictif : la recharge des VE non urgents ne démarre pas pendant un pic prévu.
            if predictif and pic_prevu[t] and not coupure:
                plafond = max(0.0, charge_hors_recharge - float(pv[t]))
                for ev in evs:
                    if ev.a_charge_heure_precedente or ev.demande_kw() <= EPS or anticipe >= plafond:
                        continue
                    p = ev.retarder(min(ev.flexibilite_disponible(), plafond - anticipe))
                    if p > EPS:
                        anticipe += p
                        tracer(ev, "ev", "DELAY", "anticipation", p,
                               f"Pic prévu de {fmt(previsions[t], 0)} kW à {heure} h -> recharge de {ev.id} "
                               f"non démarrée ({fmt(p, 2)} kW reportés, départ à {ev.depart_h} h)")

            # Recharge 1 : surplus PV
            surplus = max(float(pv[t]) - (charge_hors_recharge - anticipe), 0.0)
            for battery, p in recharger(batteries, surplus, SOC_MAX):
                recharge += p
                tracer(battery, "battery", "CHARGE", "recharge", p,
                       f"Batterie {battery.id} rechargée par le surplus PV : +{fmt(p, 2)} kW")

            def marge_steg():
                demande = max(charge_hors_recharge + recharge - float(pv[t]), 0.0) - anticipe
                return max(0.0, steg_dispo - demande)

            # Recharge 2 : STEG en heures creuses, sans jamais dépasser la capacité
            if heure in HEURES_CREUSES and not coupure:
                for battery, p in recharger(batteries, marge_steg(), SOC_CIBLE):
                    recharge += p
                    tracer(battery, "battery", "CHARGE", "recharge", p,
                           f"Batterie {battery.id} rechargée en heures creuses (tarif {fmt(tarif_tnd_kwh(heure), 2)} TND/kWh) : "
                           f"+{fmt(p, 2)} kW")

            # (a) Prédictif : préchargement si un pic est prévu à l'heure suivante et que STEG a de la marge
            if predictif and t + 1 < n_heures and pic_prevu[t + 1] and not coupure:
                for battery, p in recharger(batteries, marge_steg(), SOC_CIBLE):
                    recharge += p
                    tracer(battery, "battery", "PRECHARGE", "anticipation", p,
                           f"Pic prévu de {fmt(previsions[t + 1], 0)} kW à {int(heures[t + 1])} h -> "
                           f"batterie {battery.id} préchargée de {fmt(p, 1)} kW")

        charge_totale = charge_hors_recharge + recharge
        pv_utilise = min(float(pv[t]), charge_totale)
        demande_nette = charge_totale - pv_utilise
        deficit = max(demande_nette - steg_dispo, 0.0)

        reactif = 0.0
        if orchestre:
            deficit_restant = max(demande_nette - anticipe - steg_dispo, 0.0)
            if deficit_restant > EPS:
                ordre = ORDRE_DELESTAGE if coupure else ORDRE_MERITE
                if observateur is not None and not coupure:
                    observateur(t, deficit_restant, batteries, evs, hvacs)
                couverture, _ = dispatch(deficit_restant, batteries, evs, hvacs, ordre=ordre, delestage=coupure)
                for action in couverture:
                    reactif += action["power_kw"]
                    heure_actions.append({**action, "declencheur": "deficit"})
            contribution = anticipe + reactif
            non_desservie = max(demande_nette - contribution - steg_dispo, 0.0)
            steg_import = demande_nette - contribution - non_desservie
        else:
            contribution = 0.0
            non_desservie = 0.0 if disponible[t] else demande_nette
            steg_import = demande_nette if disponible[t] else 0.0

        decharge = sum(a["power_kw"] for a in heure_actions if a["action_type"] == "DISCHARGE")
        ve_reporte = sum(a["power_kw"] for a in heure_actions if a["device_type"] == "ev")
        hvac_reduit = sum(a["power_kw"] for a in heure_actions if a["device_type"] == "hvac")

        for ev in evs:
            ev.fin_heure()

        bilan.append({
            "scenario": scenario, "mode": mode, "date": date, "jour": jour, "heure": heure,
            "charge_totale_kw": charge_totale,
            "pv_kw": float(pv[t]),
            "pv_utilise_kw": pv_utilise,
            "demande_nette_kw": demande_nette,
            "steg_disponible_kw": steg_dispo,
            "deficit_kw": deficit,
            "steg_import_kw": steg_import,
            "decharge_batteries_kw": decharge,
            "recharge_batteries_kw": recharge,
            "ve_reporte_kw": ve_reporte,
            "hvac_reduit_kw": hvac_reduit,
            "contribution_der_kw": contribution,
            "energie_non_desservie_kw": non_desservie,
            "depassement_steg_kw": max(steg_import - steg_capacity, 0.0),
            "ve_non_livre_kwh": ve_non_livre,
            "prevision_demande_nette_kw": None if math.isnan(previsions[t]) else float(previsions[t]),
            "tarif_tnd_kwh": tarif_tnd_kwh(heure),
        })
        if orchestre:
            for action in heure_actions:
                actions.append({"scenario": scenario, "mode": mode, "date": date, "jour": jour, "heure": heure, **action})
        for battery in batteries:
            etats.append({
                "scenario": scenario, "mode": mode, "jour": jour, "heure": heure,
                "device_id": battery.id, "house_id": battery.house_id,
                "soc_debut": battery.soc_debut, "soc": battery.soc,
                "puissance_kw": battery.puissance_heure_kw, "stress_score": battery.stress_score,
            })

    colonnes_actions = ["scenario", "mode", "date", "jour", "heure", "device_id", "device_type",
                        "action_type", "declencheur", "power_kw", "justification"]
    return {
        "bilan": pd.DataFrame(bilan),
        "actions": pd.DataFrame(actions, columns=colonnes_actions),
        "etat_batteries": pd.DataFrame(etats),
    }


def simuler_tous_modes(entrees, sessions, scenario, previsions, steg_capacity=STEG_CAPACITY_KW, modes=MODES):
    resultats = [simuler_scenario(entrees, sessions, scenario, mode, steg_capacity, previsions if mode == "predictif" else None)
                 for mode in modes]
    return {cle: pd.concat([r[cle] for r in resultats], ignore_index=True) for cle in ("bilan", "actions", "etat_batteries")}


def run_simulation(scenarios=SCENARIOS, previsions_par_scenario=None):
    """Simule tous les scénarios et modes, puis remplace les résultats en base (pas d'ajout en double)."""
    from backend.forecasting_ml import previsions_demande_nette

    sessions = load_ev_sessions()
    bilans, actions, etats = [], [], []
    for scenario in scenarios:
        measurements = load_measurements(scenario)
        if measurements.empty:
            raise RuntimeError(f"Aucune mesure pour le scénario {scenario} : lancez d'abord generate_dataset.py")
        entrees = preparer_entrees(measurements)
        if previsions_par_scenario is not None:
            previsions = previsions_par_scenario[scenario]
        else:
            previsions = previsions_demande_nette(entrees["quartier"], scenario)
        resultat = simuler_tous_modes(entrees, sessions, scenario, previsions)
        bilans.append(resultat["bilan"])
        actions.append(resultat["actions"])
        etats.append(resultat["etat_batteries"])

    bilan = pd.concat(bilans, ignore_index=True)
    kpi = calculer_kpi(bilan)
    vider_tables(TABLES_SIMULATION)
    ecrire_table("bilan_horaire", bilan)
    ecrire_table("etat_batteries", pd.concat(etats, ignore_index=True))
    ecrire_table("orchestrator_actions", pd.concat(actions, ignore_index=True))
    ecrire_table("kpi_results", kpi)
    return {"bilan": bilan, "kpi": kpi}


if __name__ == "__main__":
    resultat = run_simulation()
    print(resultat["kpi"].groupby(["scenario", "mode"])[["pic_steg_apres_kw", "energie_non_desservie_kwh", "economie_tnd"]]
          .agg({"pic_steg_apres_kw": "max", "energie_non_desservie_kwh": "sum", "economie_tnd": "sum"}).round(2))
