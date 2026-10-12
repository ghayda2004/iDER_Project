import numpy as np
import pytest

from backend.config import (
    BATTERY_CAPACITY_KWH,
    MODES,
    ROUND_TRIP_EFFICIENCY,
    SOC_INIT,
    SOC_MAX,
    SOC_MIN,
    STEG_CAPACITY_KW,
)
from backend.database import lire
from backend.simulation import preparer_entrees, simuler_scenario

TOL = 1e-6


def test_bilan_energetique(pipeline):
    bilan = lire("SELECT * FROM bilan_horaire")
    assert set(bilan["mode"]) == set(MODES)
    ecart = (
        bilan["steg_import_kw"] + bilan["contribution_der_kw"] + bilan["pv_utilise_kw"]
        + bilan["energie_non_desservie_kw"] - bilan["charge_totale_kw"]
    )
    assert ecart.abs().max() < TOL
    # Identité de l'énoncé, quand toute la demande est desservie
    desservie = bilan[bilan["energie_non_desservie_kw"] == 0]
    ecart = desservie["steg_import_kw"] + desservie["contribution_der_kw"] + desservie["pv_utilise_kw"] - desservie["charge_totale_kw"]
    assert ecart.abs().max() < TOL
    assert (bilan[["steg_import_kw", "contribution_der_kw", "energie_non_desservie_kw"]] >= -TOL).all().all()


def test_steg_capacite(pipeline):
    bilan = lire("SELECT * FROM bilan_horaire WHERE mode != 'sans_orchestration'")
    assert (bilan["steg_import_kw"] <= bilan["steg_disponible_kw"] + TOL).all()
    assert (bilan["steg_import_kw"] <= STEG_CAPACITY_KW + TOL).all()
    sans = lire("SELECT * FROM bilan_horaire WHERE mode = 'sans_orchestration' AND steg_disponible_kw > 0")
    assert sans["steg_import_kw"].max() > STEG_CAPACITY_KW            # la référence dépasse bien la capacité
    np.testing.assert_allclose(sans["steg_import_kw"], sans["demande_nette_kw"])


def test_soc_bornes(pipeline):
    etat = lire("SELECT soc, soc_debut FROM etat_batteries")
    assert etat["soc"].min() >= SOC_MIN - TOL
    assert etat["soc"].max() <= SOC_MAX + TOL


def test_stress_score_monotone_et_continuite(pipeline):
    etat = lire("SELECT * FROM etat_batteries ORDER BY scenario, mode, device_id, jour, heure")
    for _, serie in etat.groupby(["scenario", "mode", "device_id"]):
        assert (serie["stress_score"].diff().dropna() >= -1e-12).all()
        # Le SoC de début d'heure est le SoC de fin de l'heure précédente, y compris à minuit.
        np.testing.assert_allclose(serie["soc_debut"].to_numpy()[1:], serie["soc"].to_numpy()[:-1], atol=1e-12)
        # La variation de SoC correspond à la puissance de l'heure (rendement appliqué à la charge).
        p = serie["puissance_kw"].to_numpy()
        attendu = np.where(p > 0, p * ROUND_TRIP_EFFICIENCY, p) / BATTERY_CAPACITY_KWH
        np.testing.assert_allclose(serie["soc"] - serie["soc_debut"], attendu, atol=1e-9)
    minuit = etat[(etat["mode"] == "reactif") & (etat["heure"] == 0) & (etat["jour"] > 0)]
    assert not np.allclose(minuit["soc_debut"], SOC_INIT)               # pas de réinitialisation quotidienne
    reactif = etat[etat["mode"] == "reactif"]
    assert reactif.groupby(["scenario", "device_id"])["stress_score"].max().min() > 0


def test_predictif_filet_securite(pipeline):
    """Prévision volontairement fausse (toujours 0) : le prédictif retombe sur la couverture réactive."""
    measurements = pipeline["measurements"]
    sessions = pipeline["sessions"]
    for scenario in ["canicule", "coupure_steg"]:
        entrees = preparer_entrees(measurements[measurements["scenario"] == scenario])
        reactif = simuler_scenario(entrees, sessions, scenario, "reactif")["bilan"]
        zeros = np.zeros(len(entrees["quartier"]))
        predictif = simuler_scenario(entrees, sessions, scenario, "predictif", previsions=zeros)["bilan"]
        assert predictif["energie_non_desservie_kw"].sum() <= reactif["energie_non_desservie_kw"].sum() + TOL
        assert (predictif["steg_import_kw"] <= STEG_CAPACITY_KW + TOL).all()


def test_coupure_steg(pipeline):
    bilan = lire("SELECT * FROM bilan_horaire WHERE scenario = 'coupure_steg'")
    coupure = bilan[bilan["steg_disponible_kw"] == 0]
    assert len(coupure) == 3 * len(MODES)
    assert (coupure["steg_import_kw"].abs() < TOL).all()
    sans = coupure[coupure["mode"] == "sans_orchestration"]
    np.testing.assert_allclose(sans["energie_non_desservie_kw"], sans["demande_nette_kw"])
    reactif = coupure[coupure["mode"] == "reactif"]
    assert reactif["energie_non_desservie_kw"].sum() < sans["energie_non_desservie_kw"].sum()
    # Les autres scénarios ne sont pas touchés : normal et coupure_steg identiques hors coupure.
    normal = lire("SELECT * FROM bilan_horaire WHERE scenario = 'normal' AND mode = 'sans_orchestration' ORDER BY jour, heure")
    sans_tout = bilan[bilan["mode"] == "sans_orchestration"].sort_values(["jour", "heure"])
    hors = sans_tout["steg_disponible_kw"].to_numpy() > 0
    np.testing.assert_allclose(sans_tout["steg_import_kw"].to_numpy()[hors], normal["steg_import_kw"].to_numpy()[hors])


def test_recharge_ve_non_pilotee_identique_au_dataset(pipeline):
    measurements = pipeline["measurements"]
    normal = measurements[measurements["scenario"] == "normal"]
    attendu = normal.groupby(["jour", "heure"])["charge_totale_kw"].sum().to_numpy()
    bilan = lire("SELECT charge_totale_kw FROM bilan_horaire WHERE scenario = 'normal' AND mode = 'sans_orchestration' ORDER BY jour, heure")
    np.testing.assert_allclose(bilan["charge_totale_kw"], attendu, atol=1e-6)
    assert lire("SELECT SUM(ve_non_livre_kwh) AS s FROM bilan_horaire WHERE scenario != 'coupure_steg'")["s"].iloc[0] == pytest.approx(0.0, abs=TOL)
