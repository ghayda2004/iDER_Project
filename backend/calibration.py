import numpy as np
import pandas as pd


def calibrer_dataset(df, scenario_ref="normal", target_peak_kw=180.0):
    """Calibre le dataset sur un pic cible pour le scénario de référence.

    Le but est de sécuriser le jeu de données contre une dérive de
    paramètres: on mesure le pic du scenario_ref, on calcule un facteur,
    puis on l'applique à base_load_kw et hvac_kw pour tous les scénarios.
    """
    if df is None or df.empty:
        raise ValueError("Le DataFrame fourni est vide, impossible de calibrer le dataset.")

    ref = df[df["scenario"] == scenario_ref]
    if ref.empty:
        raise ValueError(f"Scénario de référence '{scenario_ref}' introuvable dans le dataset.")

    pic_actuel = float(ref.groupby(["jour", "heure"])["grid_import_kw"].sum().max())
    if pic_actuel <= 0:
        raise ValueError(f"Pic brut mesuré nul pour {scenario_ref}: {pic_actuel} kW, calibration impossible.")

    facteur = target_peak_kw / pic_actuel
    print(f"[Calibration] Pic brut mesuré : {pic_actuel:.2f} kW -> facteur appliqué : {facteur:.4f}")

    calibrated = df.copy()
    calibrated["base_load_kw"] = calibrated["base_load_kw"] * facteur
    calibrated["hvac_kw"] = calibrated["hvac_kw"] * facteur
    calibrated["grid_import_kw"] = np.maximum(0.0, calibrated["base_load_kw"] + calibrated["hvac_kw"] - calibrated["pv_kw"]).round(4)
    return calibrated
