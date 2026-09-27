import pandas as pd


def prevoir_demande(df_historique, jour_actuel, heure_cible):
    """Prédit la demande réseau à une heure donnée.

    Sur les jours précédents du même scénario, la prédiction est la moyenne de
    la demande réseau sur le même créneau horaire. Pour le premier jour, on
    reprend la mesure réelle de l'heure précédente comme approximation simple et
    robuste.
    """
    if df_historique is None or df_historique.empty:
        return 0.0

    if jour_actuel == 0:
        prev_hour = max(0, heure_cible - 1)
        prev = df_historique[df_historique["heure"] == prev_hour]
        if prev.empty:
            return float(df_historique["grid_import_kw"].mean()) if not df_historique.empty else 0.0
        return float(prev["grid_import_kw"].mean())

    historique_meme_heure = df_historique[
        (df_historique["jour"] < jour_actuel) & (df_historique["heure"] == heure_cible)
    ]
    if historique_meme_heure.empty:
        fallback = df_historique[df_historique["heure"] == heure_cible]
        if fallback.empty:
            return 0.0
        return float(fallback["grid_import_kw"].mean())
    return float(historique_meme_heure["grid_import_kw"].mean())
