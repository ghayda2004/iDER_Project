from datetime import date

import numpy as np
import pandas as pd
import pytest

from backend.forecasting_ml import (
    FEATURES,
    chemin_modele,
    construire_features,
    jeu_de_donnees,
    load_models,
    predict_next_hour,
    serie_horaire,
)
from backend.database import lire
from backend.generate_dataset import construire_dataset
from backend.kpi import agreger_quartier


def serie_normale(n_days=10):
    measurements, _ = construire_dataset(n_days=n_days, date_fin=date(2026, 1, 31))
    return serie_horaire(agreger_quartier(measurements[measurements["scenario"] == "normal"]))


def test_pas_de_fuite_ml(pipeline):
    serie = serie_normale()
    k = 150                                                # on falsifie tout à partir de l'heure k
    modifiee = serie.copy()
    modifiee.loc[k:, ["charge_kw", "pv_kw"]] *= 10
    f1 = construire_features(serie, "normal")
    f2 = construire_features(modifiee, "normal")
    position = f1["jour"] * 24 + f1["heure"]
    passe = (position <= k).to_numpy()
    colonnes = FEATURES + ["baseline_charge", "baseline_pv", "persistance_charge", "persistance_pv"]
    pd.testing.assert_frame_equal(f1.loc[passe, colonnes], f2.loc[passe, colonnes])
    assert not f1.loc[~passe, "charge_lag_1h"].equals(f2.loc[~passe, "charge_lag_1h"])

    data = jeu_de_donnees()
    jours = data.groupby("split")["jour"].agg(["min", "max"])
    assert jours.loc["train", "max"] < jours.loc["val", "min"] <= jours.loc["val", "max"] < jours.loc["test", "min"]
    dates = data.groupby("split")["date"].agg(["min", "max"])
    assert dates.loc["train", "max"] < dates.loc["test", "min"]


def test_ml_metriques(pipeline):
    assert chemin_modele("charge").exists() and chemin_modele("pv").exists()
    m_charge, m_pv = load_models()
    assert hasattr(m_charge, "predict") and hasattr(m_pv, "predict")
    metrics = lire("SELECT * FROM model_metrics WHERE split = 'test'")
    assert set(metrics["modele"]) == {"ml", "baseline", "persistance"}
    charge = metrics[metrics["cible"] == "charge"].set_index("modele")
    assert charge.loc["ml", "n_echantillons"] == charge.loc["baseline", "n_echantillons"] > 0
    assert charge["mae_kw"].notna().all()
    dn = metrics[metrics["cible"] == "demande_nette"].set_index("modele")
    assert dn["vrais_positifs"].notna().all()
    assert lire("SELECT COUNT(*) AS n FROM forecasts")["n"].iloc[0] > 0
    assert lire("SELECT COUNT(*) AS n FROM feature_importances")["n"].iloc[0] == 2 * len(FEATURES)


def test_predict_next_hour_coherent_avec_le_lot(pipeline):
    serie = serie_horaire(agreger_quartier(pipeline["measurements"].query("scenario == 'normal'")))
    features = construire_features(serie, "normal")
    ligne = features.iloc[100]
    t = int(ligne["jour"]) * 24 + int(ligne["heure"]) - 1          # heure courante
    historique = serie.iloc[: t + 1]
    resultat = predict_next_hour(
        "normal", historique["date"].iloc[-1], int(historique["heure"].iloc[-1]), historique,
        {"temperature_c": ligne["temperature_prevue_c"], "irradiance_wm2": ligne["irradiance_prevue_wm2"]},
    )
    m_charge, m_pv = load_models()
    attendu = m_charge.predict(features.iloc[[100]][FEATURES])[0]
    assert resultat["charge_kw"] == pytest.approx(attendu)
    assert resultat["demande_nette_kw"] == pytest.approx(max(resultat["charge_kw"] - resultat["pv_kw"], 0.0))
    assert np.isfinite(resultat["pv_kw"])
