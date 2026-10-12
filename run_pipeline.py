"""Pipeline complet iDER : données -> modèles ML -> simulations (3 modes) -> KPI.

Usage : python run_pipeline.py [--validation-lp]
"""

import argparse
import sys
import time

import pandas as pd

from backend.config import N_DAYS, SPLIT_TRAIN, SPLIT_VAL
from backend.database import compter_lignes
from backend.forecasting_ml import train_models
from backend.generate_dataset import generate_dataset
from backend.kpi import synthese_kpi
from backend.simulation import run_simulation

COLONNES_RAPPORT = [
    "scenario", "mode", "pic_steg_apres_kw", "reduction_pic_moy_pct", "energie_deplacee_kwh", "energie_steg_kwh",
    "taux_autonomie_pct", "facture_steg_tnd", "economie_tnd", "co2_evite_kg", "energie_non_desservie_kwh",
]


def titre(texte):
    print(f"\n=== {texte} ===")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation-lp", action="store_true", help="compare aussi règles et LP (scénario normal)")
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="replace")
    pd.set_option("display.width", 200)
    debut = time.time()

    titre("1. Génération du jeu de données")
    generate_dataset()

    titre("2. Entraînement et évaluation des modèles ML")
    ml = train_models()
    print("Hyperparamètres retenus (sur val) :", ml["selection"])
    test = ml["metrics"][ml["metrics"]["split"] == "test"]
    print(test[["modele", "cible", "mae_kw", "rmse_kw", "mape_pct", "mae_pointe_kw", "n_echantillons",
                "precision_deficit", "rappel_deficit", "faux_positifs", "faux_negatifs"]].round(3).to_string(index=False))

    titre("3. Simulation (sans orchestration, réactif, prédictif)")
    resultat = run_simulation()
    kpi = resultat["kpi"]

    titre("4. KPI sur toute la période")
    print(synthese_kpi(kpi)[COLONNES_RAPPORT].round(2).to_string(index=False))

    jour_debut_test = int(N_DAYS * SPLIT_TRAIN) + int(N_DAYS * SPLIT_VAL)
    titre(f"5. KPI sur la période de test ML (jours {jour_debut_test} à {N_DAYS - 1})")
    print(synthese_kpi(kpi[kpi["jour"] >= jour_debut_test])[COLONNES_RAPPORT].round(2).to_string(index=False))

    if args.validation_lp:
        from backend.optimizer_lp import valider_scenario

        titre("6. Validation LP (scénario normal, mode réactif)")
        lp = valider_scenario("normal")
        ecart = lp["cout_regles"] - lp["cout_lp"]
        print(f"Heures de déficit : {len(lp)} | coût règles {lp['cout_regles'].sum():.2f} | coût LP {lp['cout_lp'].sum():.2f}"
              f" | heures où les règles coûtent plus : {(ecart > 1e-6).sum()}")

    titre("Lignes par table")
    for table, n in compter_lignes().items():
        print(f"  {table}: {n}")
    print(f"\nDurée totale : {time.time() - debut:.1f} s")


if __name__ == "__main__":
    main()
