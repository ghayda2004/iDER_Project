"""Prévision à T+1 h de la charge et du PV agrégés du quartier.

Trois modèles sont comparés sur un découpage chronologique (jamais de mélange) :
- persistance : valeur de la même heure la veille ;
- baseline : moyenne de la même heure sur les jours précédents du même scénario ;
- ml : RandomForestRegressor (robuste, peu d'hyperparamètres et importances de
  variables natives).

Pour prédire l'heure T depuis l'heure t = T - 1, les variables n'utilisent
que des données connues à t. La météo de T est une prévision : valeur réelle
plus un bruit gaussien (WEATHER_FORECAST_NOISE_*) qui simule l'erreur d'un
service météo. Les données étant synthétiques, le modèle apprend en partie le
générateur : ses performances ne sont pas transférables à un réseau réel.
"""

from __future__ import annotations

import sys
from datetime import date as date_type, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sklearn.ensemble import RandomForestRegressor

from backend import config
from backend.config import (
    FENETRE_POINTE_SOIR,
    MAPE_SEUIL_KW,
    SCENARIOS,
    SCENARIOS_METEO,
    SEED,
    SPLIT_TRAIN,
    SPLIT_VAL,
    STEG_CAPACITY_KW,
    WEATHER_FORECAST_NOISE_IRR_WM2,
    WEATHER_FORECAST_NOISE_TEMP_C,
)
from backend.database import TABLES_ML, ecrire_table, load_measurements, vider_tables
from backend.kpi import agreger_quartier

FEATURES = [
    "heure_sin", "heure_cos", "day_of_week", "is_weekend",
    "temperature_prevue_c", "irradiance_prevue_wm2",
    "charge_lag_1h", "charge_lag_24h", "pv_lag_1h", "pv_lag_24h", "charge_moy_3h",
]
CIBLES = {"charge": "charge_kw", "pv": "pv_kw"}
GRILLE_DEFAUT = [
    {"max_depth": depth, "min_samples_leaf": leaf} for depth in (6, 9, 12) for leaf in (1, 4)
]
HORIZON_H = 1


def serie_horaire(quartier):
    """Série horaire agrégée d'un scénario, triée chronologiquement."""
    serie = quartier.sort_values(["jour", "heure"], ignore_index=True)
    return serie.rename(columns={"charge_totale_kw": "charge_kw"})[
        ["date", "jour", "heure", "day_of_week", "is_weekend", "temperature_c", "irradiance_wm2", "charge_kw", "pv_kw"]
    ]


def meteo_prevue(serie, scenario):
    """Prévision météo simulée : vraie valeur + bruit gaussien reproductible (par scénario)."""
    rng = np.random.default_rng(SEED + 1000 + SCENARIOS.index(scenario))
    bruit_t = rng.normal(0.0, WEATHER_FORECAST_NOISE_TEMP_C, len(serie))
    bruit_i = rng.normal(0.0, WEATHER_FORECAST_NOISE_IRR_WM2, len(serie))
    temperature = serie["temperature_c"].to_numpy() + bruit_t
    # La nuit, l'irradiance prévue reste nulle (heures de lever et coucher connues).
    irradiance = np.where(serie["irradiance_wm2"].to_numpy() > 0, np.maximum(serie["irradiance_wm2"].to_numpy() + bruit_i, 0.0), 0.0)
    return temperature, irradiance


def construire_features(serie, scenario):
    """Une ligne par heure cible T ; variables connues à t = T - 1 (plus la météo prévue de T)."""
    temperature, irradiance = meteo_prevue(serie, scenario)
    charge, pv = serie["charge_kw"], serie["pv_kw"]
    f = pd.DataFrame({
        "scenario": scenario,
        "date": serie["date"],
        "jour": serie["jour"],
        "heure": serie["heure"],
        "heure_sin": np.sin(2 * np.pi * serie["heure"] / 24),
        "heure_cos": np.cos(2 * np.pi * serie["heure"] / 24),
        "day_of_week": serie["day_of_week"],
        "is_weekend": serie["is_weekend"],
        "temperature_prevue_c": temperature,
        "irradiance_prevue_wm2": irradiance,
        "charge_lag_1h": charge.shift(1),
        "charge_lag_24h": charge.shift(24),
        "pv_lag_1h": pv.shift(1),
        "pv_lag_24h": pv.shift(24),
        "charge_moy_3h": charge.shift(1).rolling(3).mean(),
        "y_charge": charge,
        "y_pv": pv,
    })
    # Baseline : moyenne de la même heure sur les jours strictement antérieurs.
    for nom, colonne in CIBLES.items():
        f[f"baseline_{nom}"] = serie.groupby("heure")[colonne].transform(lambda x: x.shift(1).expanding().mean())
        f[f"persistance_{nom}"] = f[f"{nom}_lag_24h"]
    return f.dropna(subset=["charge_lag_24h", "baseline_charge"]).reset_index(drop=True)


def attribuer_split(jours, n_jours):
    """Découpage chronologique par jours entiers : 70 % train, 15 % val, 15 % test."""
    n_train = int(n_jours * SPLIT_TRAIN)
    n_val = int(n_jours * SPLIT_VAL)
    return np.where(jours < n_train, "train", np.where(jours < n_train + n_val, "val", "test"))


def jeu_de_donnees(scenarios=SCENARIOS_METEO):
    frames = []
    n_jours = None
    for scenario in scenarios:
        quartier = agreger_quartier(load_measurements(scenario))
        n_jours = quartier["jour"].nunique()
        frames.append(construire_features(serie_horaire(quartier), scenario))
    data = pd.concat(frames, ignore_index=True)
    data["split"] = attribuer_split(data["jour"].to_numpy(), n_jours)
    return data


def metriques(y_true, y_pred, heures):
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    erreur = y_pred - y_true
    masque_mape = y_true > MAPE_SEUIL_KW
    pointe = np.isin(heures, FENETRE_POINTE_SOIR)
    return {
        "mae_kw": float(np.mean(np.abs(erreur))),
        "rmse_kw": float(np.sqrt(np.mean(erreur ** 2))),
        "mape_pct": float(np.mean(np.abs(erreur[masque_mape]) / y_true[masque_mape]) * 100) if masque_mape.any() else None,
        "mae_pointe_kw": float(np.mean(np.abs(erreur[pointe]))) if pointe.any() else None,
        "n_echantillons": int(len(y_true)),
    }


def detection_deficit(dn_true, dn_pred, capacite=STEG_CAPACITY_KW):
    reel = np.asarray(dn_true) > capacite
    prevu = np.asarray(dn_pred) > capacite
    vp = int(np.sum(reel & prevu))
    fp = int(np.sum(~reel & prevu))
    fn = int(np.sum(reel & ~prevu))
    return {
        "precision_deficit": vp / (vp + fp) if vp + fp else None,
        "rappel_deficit": vp / (vp + fn) if vp + fn else None,
        "vrais_positifs": vp,
        "faux_positifs": fp,
        "faux_negatifs": fn,
    }


def chemin_modele(cible):
    return Path(config.MODEL_DIR) / f"modele_{cible}.joblib"


def train_models(grille=None, n_estimators=200):
    """Entraîne, évalue, sauvegarde les modèles et écrit prévisions et métriques en base."""
    grille = grille or GRILLE_DEFAUT
    data = jeu_de_donnees()
    train, val = data[data["split"] == "train"], data[data["split"] == "val"]
    Path(config.MODEL_DIR).mkdir(parents=True, exist_ok=True)

    selection = {}
    importances = []
    for cible in CIBLES:
        meilleur = None
        for params in grille:
            modele = RandomForestRegressor(n_estimators=n_estimators, random_state=SEED, n_jobs=-1, **params)
            modele.fit(train[FEATURES], train[f"y_{cible}"])
            mae_val = float(np.mean(np.abs(modele.predict(val[FEATURES]) - val[f"y_{cible}"])))
            if meilleur is None or mae_val < meilleur[0]:
                meilleur = (mae_val, params, modele)
        mae_val, params, modele = meilleur
        selection[cible] = {"params": params, "mae_val_kw": mae_val}
        joblib.dump({"modele": modele, "features": FEATURES, "params": params}, chemin_modele(cible))
        data[f"ml_{cible}"] = modele.predict(data[FEATURES])
        importances += [{"cible": cible, "feature": f, "importance": float(v)} for f, v in zip(FEATURES, modele.feature_importances_)]

    for modele in ("ml", "baseline", "persistance"):
        data[f"{modele}_demande_nette"] = (data[f"{modele}_charge"] - data[f"{modele}_pv"]).clip(lower=0.0)
    data["y_demande_nette"] = (data["y_charge"] - data["y_pv"]).clip(lower=0.0)

    lignes_metriques, lignes_previsions = [], []
    for modele in ("ml", "baseline", "persistance"):
        for cible in ("charge", "pv", "demande_nette"):
            for split, part in data.groupby("split"):
                ligne = {"modele": modele, "cible": cible, "split": split, "horizon_h": HORIZON_H,
                         **metriques(part[f"y_{cible}"], part[f"{modele}_{cible}"], part["heure"])}
                if cible == "demande_nette":
                    ligne.update(detection_deficit(part["y_demande_nette"], part[f"{modele}_demande_nette"]))
                lignes_metriques.append(ligne)
            lignes_previsions.append(pd.DataFrame({
                "scenario": data["scenario"], "date": data["date"], "jour": data["jour"], "heure": data["heure"],
                "cible": cible, "y_pred": data[f"{modele}_{cible}"], "y_true": data[f"y_{cible}"],
                "modele": modele, "split": data["split"],
            }))

    metrics = pd.DataFrame(lignes_metriques)
    vider_tables(TABLES_ML)
    ecrire_table("model_metrics", metrics)
    ecrire_table("forecasts", pd.concat(lignes_previsions, ignore_index=True))
    ecrire_table("feature_importances", pd.DataFrame(importances))
    return {"metrics": metrics, "selection": selection, "importances": pd.DataFrame(importances)}


def load_models():
    """Charge les modèles (charge, pv) depuis MODEL_DIR ; les entraîne s'ils sont absents."""
    if not (chemin_modele("charge").exists() and chemin_modele("pv").exists()):
        train_models()
    return joblib.load(chemin_modele("charge"))["modele"], joblib.load(chemin_modele("pv"))["modele"]


def previsions_demande_nette(quartier, scenario, modeles=None):
    """Demande nette prévue pour chaque heure du scénario (faite à l'heure précédente), NaN sans historique."""
    m_charge, m_pv = modeles or load_models()
    serie = serie_horaire(quartier)
    features = construire_features(serie, scenario)
    prevision = np.full(len(serie), np.nan)
    if not features.empty:
        dn = np.maximum(m_charge.predict(features[FEATURES]) - m_pv.predict(features[FEATURES]), 0.0)
        position = {(j, h): i for i, (j, h) in enumerate(zip(serie["jour"], serie["heure"]))}
        for (j, h), valeur in zip(zip(features["jour"], features["heure"]), dn):
            prevision[position[(j, h)]] = valeur
    return prevision


def predict_next_hour(scenario, date, heure, historique_df, meteo_prevue_t1, modeles=None):
    """Prévision de l'heure suivant (date, heure).

    `historique_df` : série horaire (colonnes charge_kw, pv_kw) se terminant à
    l'heure courante incluse, au moins 24 lignes. `meteo_prevue_t1` : dict
    {'temperature_c', 'irradiance_wm2'} prévu pour l'heure suivante.
    """
    if len(historique_df) < 24:
        raise ValueError("Au moins 24 heures d'historique sont nécessaires.")
    m_charge, m_pv = modeles or load_models()
    jour_courant = date if isinstance(date, date_type) else date_type.fromisoformat(str(date))
    cible = pd.Timestamp(jour_courant) + timedelta(hours=int(heure) + 1)
    charge, pv = historique_df["charge_kw"].to_numpy(), historique_df["pv_kw"].to_numpy()
    ligne = pd.DataFrame([{
        "heure_sin": np.sin(2 * np.pi * cible.hour / 24),
        "heure_cos": np.cos(2 * np.pi * cible.hour / 24),
        "day_of_week": cible.dayofweek,
        "is_weekend": int(cible.dayofweek >= 5),
        "temperature_prevue_c": meteo_prevue_t1["temperature_c"],
        "irradiance_prevue_wm2": meteo_prevue_t1["irradiance_wm2"],
        "charge_lag_1h": charge[-1],
        "charge_lag_24h": charge[-24],
        "pv_lag_1h": pv[-1],
        "pv_lag_24h": pv[-24],
        "charge_moy_3h": charge[-3:].mean(),
    }])[FEATURES]
    charge_kw = float(m_charge.predict(ligne)[0])
    pv_kw = float(m_pv.predict(ligne)[0])
    return {"scenario": scenario, "charge_kw": charge_kw, "pv_kw": pv_kw, "demande_nette_kw": max(charge_kw - pv_kw, 0.0)}


if __name__ == "__main__":
    resultat = train_models()
    print(resultat["selection"])
    test = resultat["metrics"][resultat["metrics"]["split"] == "test"]
    print(test.round(3).to_string(index=False))
