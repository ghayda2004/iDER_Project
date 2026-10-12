from datetime import date

import pandas as pd
import pytest

from backend.config import COUPURE_HEURES, FENETRE_POINTE_SOIR, N_DAYS, STEG_CAPACITY_KW
from backend.generate_dataset import construire_dataset, demande_quartier


@pytest.fixture(scope="module")
def dataset_complet():
    return construire_dataset(n_days=N_DAYS, date_fin=date(2026, 1, 31))


def test_dataset_reproductible():
    m1, s1 = construire_dataset(n_days=10, seed=42, date_fin=date(2026, 1, 31))
    m2, s2 = construire_dataset(n_days=10, seed=42, date_fin=date(2026, 1, 31))
    pd.testing.assert_frame_equal(m1, m2)
    pd.testing.assert_frame_equal(s1, s2)
    m3, _ = construire_dataset(n_days=10, seed=7, date_fin=date(2026, 1, 31))
    assert not m1["base_load_kw"].equals(m3["base_load_kw"])


def test_variabilite_journaliere(dataset_complet):
    measurements, _ = dataset_complet
    pics = demande_quartier(measurements).groupby(["scenario", "jour"])["demande_nette_kw"].max().unstack(0)
    for scenario in ["normal", "nuageux", "canicule"]:
        assert pics[scenario].std() > 0
    assert not (pics["normal"].equals(pics["nuageux"]) and pics["normal"].equals(pics["canicule"]))
    assert pics["canicule"].mean() > pics["normal"].mean()


def test_dates_dynamiques(pipeline):
    derniere = date.fromisoformat(pipeline["measurements"]["date"].max())
    assert abs((derniere - date.today()).days) <= 1
    assert pipeline["measurements"]["jour"].nunique() == pipeline["measurements"]["date"].nunique()


def test_courbe_hors_pointe(dataset_complet):
    measurements, _ = dataset_complet
    agregat = demande_quartier(measurements)
    normal = agregat[agregat["scenario"] == "normal"]
    hors_pointe = normal[~normal["heure"].isin(FENETRE_POINTE_SOIR)]
    assert hors_pointe["demande_nette_kw"].max() < STEG_CAPACITY_KW
    assert normal[normal["heure"].isin(FENETRE_POINTE_SOIR)]["demande_nette_kw"].max() > STEG_CAPACITY_KW


def test_nuageux_moins_de_pv_en_fin_de_journee(dataset_complet):
    measurements, _ = dataset_complet
    pv = measurements[measurements["heure"].isin([17, 18])].groupby("scenario")["pv_kw"].sum()
    assert pv["nuageux"] < 0.6 * pv["normal"]


def test_coupure_ne_change_que_la_disponibilite(dataset_complet):
    measurements, _ = dataset_complet
    normal = measurements[measurements["scenario"] == "normal"].reset_index(drop=True)
    coupure = measurements[measurements["scenario"] == "coupure_steg"].reset_index(drop=True)
    colonnes = [c for c in normal.columns if c not in ("scenario", "steg_available")]
    pd.testing.assert_frame_equal(normal[colonnes], coupure[colonnes])
    heures_coupees = coupure[coupure["steg_available"] == 0]
    assert sorted(heures_coupees["heure"].unique()) == COUPURE_HEURES
    assert heures_coupees["jour"].nunique() == 1
    assert (normal["steg_available"] == 1).all()
