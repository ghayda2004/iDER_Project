import pandas as pd
import pytest

from backend.config import TARIF_CREUX_TND_KWH, TARIF_POINTE_TND_KWH
from backend.database import lire
from backend.kpi import calculer_kpi, calculer_kpi_jour
from backend.simulation import preparer_entrees, simuler_scenario

SESSIONS_VIDES = pd.DataFrame(columns=["house_id", "jour", "arrivee_h", "depart_h", "soc_arrivee", "energie_kwh"])


def mesures_jouet():
    """20 maisons, 2 heures : 20 x 5 kW à 0h (100 kW) ; à 1h, H01 tire 12 kW et les autres 1 kW (31 kW)."""
    lignes = []
    for heure in (0, 1):
        for m in range(1, 21):
            charge = 5.0 if heure == 0 else (12.0 if m == 1 else 1.0)
            lignes.append({
                "scenario": "normal", "date": "2026-01-01", "jour": 0, "heure": heure, "house_id": f"H{m:02d}",
                "day_of_week": 3, "is_weekend": 0, "temperature_c": 20.0, "irradiance_wm2": 0.0, "steg_available": 1,
                "base_load_kw": charge, "hvac_kw": 0.0, "ev_charge_kw": 0.0, "ev_connected": 0, "ev_soc": None,
                "pv_kw": 0.0, "charge_totale_kw": charge,
            })
    return pd.DataFrame(lignes)


def test_kpi_agregation():
    mesures = mesures_jouet()
    bilan = simuler_scenario(preparer_entrees(mesures), SESSIONS_VIDES, "normal", "sans_orchestration")["bilan"]
    kpi = calculer_kpi(bilan).iloc[0]
    assert kpi["pic_steg_avant_kw"] == pytest.approx(100.0)          # max des sommes horaires
    assert kpi["pic_steg_avant_kw"] != pytest.approx(mesures["charge_totale_kw"].max())   # pas 12 kW
    assert kpi["energie_steg_avant_kwh"] == pytest.approx(131.0)


def bilan_jouet(steg_par_heure):
    lignes = []
    for heure in range(24):
        steg = steg_par_heure.get(heure, 50.0)
        lignes.append({
            "heure": heure, "steg_import_kw": steg, "charge_totale_kw": steg, "recharge_batteries_kw": 0.0,
            "ve_reporte_kw": 0.0, "hvac_reduit_kw": 0.0, "energie_non_desservie_kw": 0.0,
            "contribution_der_kw": 0.0, "depassement_steg_kw": 0.0, "ve_non_livre_kwh": 0.0,
        })
    return pd.DataFrame(lignes)


def test_economie_unites():
    """10 kWh déplacés de la pointe (19h) vers une heure creuse (2h)."""
    avant = bilan_jouet({19: 60.0})
    apres = bilan_jouet({2: 60.0})
    kpi = calculer_kpi_jour(avant, apres)
    assert kpi["economie_tnd"] == pytest.approx(10 * (TARIF_POINTE_TND_KWH - TARIF_CREUX_TND_KWH))
    assert kpi["co2_evite_kg"] == pytest.approx(0.0)
    assert kpi["pic_steg_apres_kw"] == pytest.approx(60.0)


def test_kpi_uniques_et_coherents(pipeline):
    kpi = lire("SELECT * FROM kpi_results")
    assert not kpi.duplicated(["scenario", "mode", "jour"]).any()
    sans = kpi[kpi["mode"] == "sans_orchestration"]
    assert (sans["economie_tnd"].abs() < 1e-9).all()
    orchestre = kpi[kpi["mode"] != "sans_orchestration"]
    assert (orchestre["pic_steg_apres_kw"] <= orchestre["pic_steg_avant_kw"] + 1e-6).all()
    bilan = lire("SELECT scenario, mode, jour, MAX(steg_import_kw) AS pic FROM bilan_horaire GROUP BY scenario, mode, jour")
    fusion = kpi.merge(bilan, on=["scenario", "mode", "jour"])
    assert (fusion["pic"] - fusion["pic_steg_apres_kw"]).abs().max() < 1e-9
