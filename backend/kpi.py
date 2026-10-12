"""Indicateurs (KPI) calculés par scénario, jour et mode à partir du bilan horaire du quartier.

Chaque ligne du bilan représente une heure : une puissance en kW maintenue
1 h vaut une énergie en kWh. Les tarifs et le facteur CO2 sont illustratifs.
"""

import pandas as pd

from backend.config import FACTEUR_CO2_KG_KWH, tarif_tnd_kwh

DUREE_PAS_H = 1.0


def agreger_quartier(measurements):
    """Somme des 20 maisons heure par heure (jamais le max d'une ligne maison-heure)."""
    colonnes = ["base_load_kw", "hvac_kw", "ev_charge_kw", "pv_kw", "charge_totale_kw"]
    agregat = measurements.groupby(["jour", "heure"], as_index=False)[colonnes].sum()
    meteo = measurements.groupby(["jour", "heure"], as_index=False).agg(
        date=("date", "first"),
        temperature_c=("temperature_c", "first"),
        irradiance_wm2=("irradiance_wm2", "first"),
        day_of_week=("day_of_week", "first"),
        is_weekend=("is_weekend", "first"),
        steg_available=("steg_available", "min"),
    )
    agregat = agregat.merge(meteo, on=["jour", "heure"]).sort_values(["jour", "heure"], ignore_index=True)
    agregat["demande_nette_kw"] = (agregat["charge_totale_kw"] - agregat["pv_kw"]).clip(lower=0.0)
    return agregat


def facture_tnd(bilan):
    return float((bilan["steg_import_kw"] * DUREE_PAS_H * bilan["heure"].map(tarif_tnd_kwh)).sum())


def consommation_servie_kwh(bilan):
    """Énergie réellement consommée par les maisons (kWh).

    Demande moins reports VE, réductions HVAC et énergie non desservie ; la
    recharge des batteries est exclue (stockage, pas consommation).
    """
    servie = (
        bilan["charge_totale_kw"] - bilan["recharge_batteries_kw"] - bilan["ve_reporte_kw"]
        - bilan["hvac_reduit_kw"] - bilan["energie_non_desservie_kw"]
    )
    return float(servie.sum() * DUREE_PAS_H)


def calculer_kpi_jour(avant, apres):
    """KPI d'une journée : `avant` = bilan sans orchestration, `apres` = bilan du mode évalué."""
    pic_avant = float(avant["steg_import_kw"].max())
    pic_apres = float(apres["steg_import_kw"].max())
    energie_avant = float(avant["steg_import_kw"].sum() * DUREE_PAS_H)
    energie_apres = float(apres["steg_import_kw"].sum() * DUREE_PAS_H)
    consommation = consommation_servie_kwh(apres)
    facture_avant = facture_tnd(avant)
    facture_apres = facture_tnd(apres)
    return {
        "pic_steg_avant_kw": pic_avant,
        "pic_steg_apres_kw": pic_apres,
        "reduction_pic_pct": (pic_avant - pic_apres) / pic_avant * 100.0 if pic_avant > 0 else 0.0,
        "energie_deplacee_kwh": float(apres["contribution_der_kw"].sum() * DUREE_PAS_H),
        "energie_steg_avant_kwh": energie_avant,
        "energie_steg_apres_kwh": energie_apres,
        "consommation_kwh": consommation,
        "taux_autonomie_pct": (1.0 - energie_apres / consommation) * 100.0 if consommation > 0 else 0.0,
        "facture_steg_avant_tnd": facture_avant,
        "facture_steg_apres_tnd": facture_apres,
        "economie_tnd": facture_avant - facture_apres,
        "co2_evite_kg": (energie_avant - energie_apres) * FACTEUR_CO2_KG_KWH,
        "energie_non_desservie_kwh": float(apres["energie_non_desservie_kw"].sum() * DUREE_PAS_H),
        "depassement_steg_kwh": float(apres["depassement_steg_kw"].sum() * DUREE_PAS_H),
        "ve_non_livre_kwh": float(apres["ve_non_livre_kwh"].sum()),
    }


def synthese_kpi(kpi):
    """Agrège les KPI journaliers par scénario et mode (sommes d'énergie, max des pics)."""
    groupes = kpi.groupby(["scenario", "mode"], sort=False)
    synthese = groupes.agg(
        jours=("jour", "nunique"),
        pic_steg_avant_kw=("pic_steg_avant_kw", "max"),
        pic_steg_apres_kw=("pic_steg_apres_kw", "max"),
        reduction_pic_moy_pct=("reduction_pic_pct", "mean"),
        energie_deplacee_kwh=("energie_deplacee_kwh", "sum"),
        energie_steg_kwh=("energie_steg_apres_kwh", "sum"),
        consommation_kwh=("consommation_kwh", "sum"),
        facture_steg_tnd=("facture_steg_apres_tnd", "sum"),
        economie_tnd=("economie_tnd", "sum"),
        co2_evite_kg=("co2_evite_kg", "sum"),
        energie_non_desservie_kwh=("energie_non_desservie_kwh", "sum"),
        depassement_steg_kwh=("depassement_steg_kwh", "sum"),
    ).reset_index()
    synthese["taux_autonomie_pct"] = (1 - synthese["energie_steg_kwh"] / synthese["consommation_kwh"]) * 100
    return synthese


def calculer_kpi(bilan):
    """KPI pour chaque (scénario, mode, jour) d'un bilan contenant le mode sans_orchestration."""
    lignes = []
    reference = bilan[bilan["mode"] == "sans_orchestration"]
    for (scenario, mode, jour), apres in bilan.groupby(["scenario", "mode", "jour"], sort=True):
        avant = reference[(reference["scenario"] == scenario) & (reference["jour"] == jour)]
        lignes.append({
            "scenario": scenario,
            "mode": mode,
            "date": apres["date"].iloc[0],
            "jour": int(jour),
            **calculer_kpi_jour(avant, apres),
        })
    return pd.DataFrame(lignes)
