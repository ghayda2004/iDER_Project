"""Génère le jeu de données synthétique du quartier (mesures horaires par maison).

Méthode : la forme de la courbe de charge vient directement des profils de
`config.py` (base horaire par maison, occupation HVAC, sessions VE), sans
facteur de calibration global. Un seul générateur `rng` est créé avant toutes
les boucles ; les tirages communs (charges, VE, bruit) sont partagés entre les
scénarios météo pour que seules la température et l'ensoleillement les
distinguent.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import (
    COUCHER_SOLEIL_H,
    COUPURE_HEURES,
    COUPURE_JOURS_AVANT_FIN,
    ECART_TEMPERATURE_CANICULE_C,
    ECART_TEMPERATURE_NUAGEUX_C,
    EV_ARRIVEE_MOYENNE_H,
    EV_BATTERY_CAPACITY_KWH,
    EV_DEPART_MOYEN_H,
    EV_MAX_CHARGE_KW,
    EV_SOC_ARRIVEE_SEMAINE,
    EV_SOC_ARRIVEE_WEEKEND,
    EV_TARGET_SOC,
    FACTEUR_NUAGES_CANICULE,
    FACTEUR_NUAGES_NORMAL,
    FACTEUR_NUAGES_NUAGEUX,
    FACTEUR_WEEKEND_JOURNEE,
    FACTEUR_WEEKEND_MATIN,
    FENETRE_POINTE_SOIR,
    HVAC_KW_FIXE,
    HVAC_KW_PAR_DEGRE,
    HVAC_SEUIL_C,
    IRRADIANCE_CIEL_CLAIR_WM2,
    LEVER_SOLEIL_H,
    MAISONS_AVEC_EV,
    MAISONS_AVEC_PV,
    N_DAYS,
    NB_MAISONS,
    OCCUPATION_HVAC,
    OCCUPATION_HVAC_WEEKEND_JOURNEE,
    PROFIL_BASE_KW,
    PV_PERFORMANCE_RATIO,
    PV_PERTE_PAR_DEGRE,
    PV_PUISSANCE_CRETE_KWC,
    SCENARIO_COUPURE,
    SCENARIOS_METEO,
    SEED,
    TEMPERATURE_AMPLITUDE_C,
    TEMPERATURE_MOYENNE_C,
    dates_simulation,
)
from backend.database import compter_lignes, ecrire_table, reinitialiser_schema

HEURES = np.arange(24)


def irradiance_ciel_clair():
    """Irradiance (W/m²) au milieu de chaque heure : 0 la nuit, maximum vers 12h45."""
    milieu = HEURES + 0.5
    duree_jour = COUCHER_SOLEIL_H - LEVER_SOLEIL_H
    courbe = np.sin(np.pi * (milieu - LEVER_SOLEIL_H) / duree_jour)
    return IRRADIANCE_CIEL_CLAIR_WM2 * np.where((milieu > LEVER_SOLEIL_H) & (milieu < COUCHER_SOLEIL_H), courbe, 0.0)


def sessions_ve(rng, n_days, weekend):
    """Tire les sessions de recharge et calcule la recharge non pilotée (dès l'arrivée, à pleine puissance)."""
    n_ev = MAISONS_AVEC_EV
    # depart[d] = départ le matin du jour d (session de la veille) ; depart[0] clôt une session fictive pleine.
    depart = np.clip(np.rint(rng.normal(EV_DEPART_MOYEN_H, 0.7, (n_days + 1, n_ev))), 6, 8).astype(int)
    arrivee = np.clip(np.rint(rng.normal(EV_ARRIVEE_MOYENNE_H, 1.0, (n_days, n_ev))), 17, 21).astype(int)
    soc_semaine = rng.uniform(*EV_SOC_ARRIVEE_SEMAINE, (n_days, n_ev))
    soc_weekend = rng.uniform(*EV_SOC_ARRIVEE_WEEKEND, (n_days, n_ev))
    soc_arrivee = np.where(weekend[:, None] == 1, soc_weekend, soc_semaine)

    n_heures = n_days * 24
    charge = np.zeros((n_heures, n_ev))
    connecte = np.zeros((n_heures, n_ev), dtype=int)
    soc = np.full((n_heures, n_ev), np.nan)
    sessions = []
    for k in range(n_ev):
        connecte[: depart[0, k], k] = 1
        soc[: depart[0, k], k] = EV_TARGET_SOC
        for jour in range(n_days):
            t_arrivee = jour * 24 + arrivee[jour, k]
            t_depart = (jour + 1) * 24 + depart[jour + 1, k]
            energie = (EV_TARGET_SOC - soc_arrivee[jour, k]) * EV_BATTERY_CAPACITY_KWH
            restant, niveau = energie, soc_arrivee[jour, k]
            for t in range(t_arrivee, min(t_depart, n_heures)):
                puissance = min(EV_MAX_CHARGE_KW, restant)
                restant -= puissance
                niveau += puissance / EV_BATTERY_CAPACITY_KWH
                charge[t, k] = puissance
                connecte[t, k] = 1
                soc[t, k] = niveau
            sessions.append({
                "house_id": f"H{k + 1:02d}",
                "jour": jour,
                "arrivee_h": int(arrivee[jour, k]),
                "depart_h": int(depart[jour + 1, k]),
                "soc_arrivee": round(float(soc_arrivee[jour, k]), 4),
                "energie_kwh": round(float(energie), 4),
            })
    return charge, connecte, soc, pd.DataFrame(sessions)


def construire_dataset(n_days=N_DAYS, seed=SEED, date_fin=None):
    """Construit les mesures (4 scénarios) et les sessions VE, sans écrire en base."""
    rng = np.random.default_rng(seed)
    n_maisons = NB_MAISONS
    dates = dates_simulation(n_days, date_fin)
    day_of_week = np.array([d.weekday() for d in dates])
    weekend = (day_of_week >= 5).astype(int)          # samedi et dimanche

    # Caractéristiques fixes des maisons
    facteur_maison = rng.uniform(0.85, 1.15, n_maisons)
    facteur_hvac_maison = rng.uniform(0.8, 1.2, n_maisons)
    puissance_crete = rng.uniform(*PV_PUISSANCE_CRETE_KWC, n_maisons)
    puissance_crete[MAISONS_AVEC_PV:] = 0.0

    # Variabilité journalière et horaire (partagée entre scénarios)
    facteur_jour = rng.normal(1.0, 0.04, (n_days, n_maisons))
    bruit_base = np.clip(rng.normal(1.0, 0.05, (n_days, 24, n_maisons)), 0.85, 1.15)
    bruit_hvac = np.clip(rng.normal(1.0, 0.05, (n_days, 24, n_maisons)), 0.85, 1.15)
    bruit_pv = np.clip(rng.normal(1.0, 0.04, (n_days, 24, n_maisons)), 0.9, 1.1)

    # Météo journalière
    ecart_temperature_jour = rng.normal(0.0, 1.2, n_days)
    bruit_temperature = rng.normal(0.0, 0.5, (n_days, 24))
    nuages = {
        "normal": rng.uniform(*FACTEUR_NUAGES_NORMAL, n_days),
        "nuageux": rng.uniform(*FACTEUR_NUAGES_NUAGEUX, n_days),
        "canicule": rng.uniform(*FACTEUR_NUAGES_CANICULE, n_days),
    }
    ecart_temperature = {
        "normal": np.zeros(n_days),
        "nuageux": np.full(n_days, ECART_TEMPERATURE_NUAGEUX_C),
        "canicule": rng.uniform(*ECART_TEMPERATURE_CANICULE_C, n_days),
    }

    ev_charge, ev_connecte, ev_soc, sessions = sessions_ve(rng, n_days, weekend)
    sessions["date"] = sessions["jour"].map(lambda j: dates[j].isoformat())

    # Charge de base (kW) : profil horaire x week-end x maison x jour x bruit
    facteur_horaire = np.ones((n_days, 24))
    facteur_horaire[weekend == 1, 9:17] = FACTEUR_WEEKEND_JOURNEE
    facteur_horaire[weekend == 1, 6:9] = FACTEUR_WEEKEND_MATIN
    base = (
        np.array(PROFIL_BASE_KW)[None, :, None]
        * facteur_horaire[:, :, None]
        * facteur_maison[None, None, :]
        * facteur_jour[:, None, :]
        * bruit_base
    )
    occupation = np.tile(np.array(OCCUPATION_HVAC, dtype=float), (n_days, 1))
    occupation[weekend == 1, 9:17] = OCCUPATION_HVAC_WEEKEND_JOURNEE

    # VE : tableaux (jour, heure, maison), nuls pour les maisons sans VE
    ve_kw = np.zeros((n_days, 24, n_maisons))
    ve_connecte = np.zeros((n_days, 24, n_maisons), dtype=int)
    ve_soc = np.full((n_days, 24, n_maisons), np.nan)
    ve_kw[:, :, :MAISONS_AVEC_EV] = ev_charge.reshape(n_days, 24, -1)
    ve_connecte[:, :, :MAISONS_AVEC_EV] = ev_connecte.reshape(n_days, 24, -1)
    ve_soc[:, :, :MAISONS_AVEC_EV] = ev_soc.reshape(n_days, 24, -1)

    temperature_normale = (
        TEMPERATURE_MOYENNE_C
        + TEMPERATURE_AMPLITUDE_C * np.sin(2 * np.pi * (HEURES - 9) / 24)[None, :]
        + ecart_temperature_jour[:, None]
        + bruit_temperature
    )
    ciel_clair = irradiance_ciel_clair()
    index_jour, index_heure, index_maison = np.meshgrid(np.arange(n_days), HEURES, np.arange(n_maisons), indexing="ij")

    frames = []
    for scenario in SCENARIOS_METEO:
        temperature = temperature_normale + ecart_temperature[scenario][:, None]
        irradiance = ciel_clair[None, :] * nuages[scenario][:, None]
        hvac = (
            occupation[:, :, None]
            * facteur_hvac_maison[None, None, :]
            * (HVAC_KW_FIXE + HVAC_KW_PAR_DEGRE * np.maximum(temperature - HVAC_SEUIL_C, 0.0))[:, :, None]
            * bruit_hvac
        )
        rendement = 1.0 - PV_PERTE_PAR_DEGRE * np.maximum(temperature - 25.0, 0.0)
        pv = (
            puissance_crete[None, None, :]
            * (irradiance / 1000.0 * PV_PERFORMANCE_RATIO * rendement)[:, :, None]
            * bruit_pv
        )
        base_r, hvac_r, ve_r, pv_r = (np.round(a, 4) for a in (base, hvac, ve_kw, pv))
        frames.append(pd.DataFrame({
            "scenario": scenario,
            "date": [dates[j].isoformat() for j in index_jour.ravel()],
            "jour": index_jour.ravel(),
            "heure": index_heure.ravel(),
            "house_id": [f"H{m + 1:02d}" for m in index_maison.ravel()],
            "day_of_week": day_of_week[index_jour.ravel()],
            "is_weekend": weekend[index_jour.ravel()],
            "temperature_c": np.round(np.repeat(temperature.ravel(), n_maisons), 2),
            "irradiance_wm2": np.round(np.repeat(irradiance.ravel(), n_maisons), 1),
            "steg_available": 1,
            "base_load_kw": base_r.ravel(),
            "hvac_kw": hvac_r.ravel(),
            "ev_charge_kw": ve_r.ravel(),
            "ev_connected": ve_connecte.ravel(),
            "ev_soc": np.round(ve_soc.ravel(), 4),
            "pv_kw": pv_r.ravel(),
            "charge_totale_kw": (base_r + hvac_r + ve_r).ravel(),
        }))

    # Scénario coupure_steg : mêmes mesures que normal, STEG indisponible pendant la plage configurée
    coupure = frames[0].copy()
    coupure["scenario"] = SCENARIO_COUPURE
    jour_coupure = max(0, n_days - COUPURE_JOURS_AVANT_FIN)
    masque = (coupure["jour"] == jour_coupure) & coupure["heure"].isin(COUPURE_HEURES)
    coupure.loc[masque, "steg_available"] = 0
    frames.append(coupure)

    measurements = pd.concat(frames, ignore_index=True)
    return measurements, sessions[["house_id", "jour", "date", "arrivee_h", "depart_h", "soc_arrivee", "energie_kwh"]]


def demande_quartier(measurements):
    """Demande nette agrégée du quartier, sans orchestration : somme des 20 maisons, puis max(charge - PV, 0)."""
    agregat = measurements.groupby(["scenario", "jour", "heure"], as_index=False)[["charge_totale_kw", "pv_kw"]].sum()
    agregat["demande_nette_kw"] = (agregat["charge_totale_kw"] - agregat["pv_kw"]).clip(lower=0.0)
    return agregat


def resume(measurements):
    agregat = demande_quartier(measurements)
    print(f"Période : {measurements['date'].min()} -> {measurements['date'].max()} "
          f"({measurements['jour'].nunique()} jours)")
    pics = agregat.groupby(["scenario", "jour"])["demande_nette_kw"].max()
    hors_pointe = agregat[~agregat["heure"].isin(FENETRE_POINTE_SOIR)].groupby("scenario")["demande_nette_kw"].max()
    print("Pic journalier de demande nette agrégée, sans orchestration (kW) :")
    for scenario, serie in pics.groupby(level=0):
        print(f"  {scenario:13s} moyenne {serie.mean():7.2f} | min {serie.min():7.2f} | max {serie.max():7.2f}"
              f" | max hors 17h-22h {hors_pointe[scenario]:7.2f}")


def generate_dataset(n_days=N_DAYS, seed=SEED):
    measurements, sessions = construire_dataset(n_days, seed)
    reinitialiser_schema()
    ecrire_table("measurements", measurements)
    ecrire_table("ev_sessions", sessions)
    print("Lignes par table :")
    for table, n in compter_lignes().items():
        print(f"  {table}: {n}")
    resume(measurements)
    return measurements, sessions


if __name__ == "__main__":
    generate_dataset()
