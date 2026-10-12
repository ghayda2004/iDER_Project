from __future__ import annotations

from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from backend.config import (
    FACTEUR_CO2_KG_KWH,
    MAPE_SEUIL_KW,
    MODES,
    N_DAYS,
    SCENARIOS,
    SCENARIOS_METEO,
    SOC_CIBLE,
    SPLIT_TRAIN,
    SPLIT_VAL,
    STEG_CAPACITY_KW,
    TARIF_CREUX_TND_KWH,
    TARIF_PLEIN_TND_KWH,
    TARIF_POINTE_TND_KWH,
    WEATHER_FORECAST_NOISE_IRR_WM2,
    WEATHER_FORECAST_NOISE_TEMP_C,
)
from backend.database import lire, load_ev_sessions, load_measurements, schema_a_jour
from backend.kpi import calculer_kpi, synthese_kpi

st.set_page_config(page_title="iDER | STEG et DER", page_icon="⚡", layout="wide")
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    :root {
        --green-900: #0B3D2E;
        --green-700: #1F6F50;
        --green-500: #3CB371;
        --green-300: #8FD9B6;
        --green-100: #E3F5EC;
        --bg: #F7FAF8;
        --text: #1C2620;
        --alert: #E76F51;
    }
    html, body, [class*="st-"] { font-family: 'Inter', sans-serif; }
    .stApp { background: var(--bg); color: var(--text); }
    section[data-testid="stSidebar"] { background: var(--green-900); }
    section[data-testid="stSidebar"] * { color: var(--green-100); }
    section[data-testid="stSidebar"] [data-baseweb="select"] > div {
        background: var(--green-100);
        border-color: var(--green-300);
    }
    section[data-testid="stSidebar"] [data-baseweb="select"] * { color: var(--green-900); }
    [data-testid="stIconMaterial"], .material-symbols-rounded { font-family: 'Material Symbols Rounded' !important; }
    .ider-brand { color: var(--green-100); font-size: 1.55rem; font-weight: 700; }
    .ider-brand-note { color: var(--green-300); font-size: 0.82rem; }
    .ider-legend { margin-top: 1.25rem; padding-top: 0.9rem; border-top: 1px solid color-mix(in srgb, var(--green-100) 25%, transparent); }
    .legend-line { margin: 0.3rem 0; font-size: 0.82rem; }
    .legend-dot { display: inline-block; width: 0.58rem; height: 0.58rem; border-radius: 50%; margin-right: 0.45rem;
                  border: 1px solid var(--green-100); }
    .stTabs [data-baseweb="tab-list"] { gap: 0.35rem; }
    .stTabs [aria-selected="true"] { color: var(--green-700); }
    [data-testid="stMetricLabel"] { color: var(--green-900); font-weight: 600; }
    [data-testid="stMetricValue"] { color: var(--text); }
    .resource-title { color: var(--green-900); font-weight: 600; margin-bottom: 0.25rem; }
    .resource-meta { color: color-mix(in srgb, var(--text) 70%, transparent); font-size: 0.84rem; }
    .soc-track { height: 0.58rem; width: 100%; background: var(--green-100); border-radius: 1rem; overflow: hidden; margin: 0.7rem 0 0.35rem; }
    .soc-fill { height: 100%; border-radius: inherit; }
    .status-badge { display: inline-block; padding: 0.18rem 0.5rem; border-radius: 1rem; background: var(--green-100); color: var(--green-700); font-size: 0.76rem; font-weight: 600; }
    .sandbox-note { border-left: 3px solid var(--green-500); padding-left: 0.75rem; color: var(--text); margin-bottom: 0.8rem; }
    .alert-note { border-left: 3px solid var(--alert); padding-left: 0.75rem; color: var(--text); margin-bottom: 0.8rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

COULEURS = {
    "green_900": "#0B3D2E",
    "green_700": "#1F6F50",
    "green_500": "#3CB371",
    "green_300": "#8FD9B6",
    "text": "#1C2620",
    "alert": "#E76F51",
}
# Une couleur par source du bilan énergétique
COULEURS_SOURCES = {
    "steg_import_kw": ("STEG", "#0B3D2E"),
    "pv_utilise_kw": ("PV utilisé", "#E9C46A"),
    "decharge_batteries_kw": ("Décharge batteries", "#3CB371"),
    "ve_reporte_kw": ("Recharge VE reportée", "#8FD9B6"),
    "hvac_reduit_kw": ("HVAC réduit", "#2A9D8F"),
    "energie_non_desservie_kw": ("Énergie non desservie", "#E76F51"),
}
COULEURS_MODES = {"sans_orchestration": "#8FD9B6", "reactif": "#3CB371", "predictif": "#0B3D2E"}
LIBELLES_MODES = {"sans_orchestration": "Sans orchestration", "reactif": "Réactif", "predictif": "Prédictif"}
LIBELLES_SCENARIOS = {"normal": "Normal", "nuageux": "Nuageux", "canicule": "Canicule", "coupure_steg": "Coupure STEG"}
LIBELLES_MODELES = {"ml": "ML (forêt aléatoire)", "baseline": "Baseline (moyenne même heure)", "persistance": "Persistance (veille)"}
LIBELLES_CIBLES = {"demande_nette": "Demande nette", "charge": "Charge totale", "pv": "Production PV"}
JOUR_DEBUT_TEST = int(N_DAYS * SPLIT_TRAIN) + int(N_DAYS * SPLIT_VAL)


def mise_en_page(figure, titre, axe_x, axe_y, hauteur=420):
    figure.update_layout(
        title=titre,
        xaxis_title=axe_x,
        yaxis_title=axe_y,
        height=hauteur,
        margin={"l": 20, "r": 20, "t": 70, "b": 20},
        paper_bgcolor="rgba(0, 0, 0, 0)",
        plot_bgcolor="rgba(0, 0, 0, 0)",
        font={"family": "Inter, sans-serif", "color": COULEURS["text"]},
        legend={"orientation": "h", "y": -0.18},
        xaxis={"gridcolor": "rgba(11, 61, 46, 0.08)"},
        yaxis={"gridcolor": "rgba(11, 61, 46, 0.08)"},
    )
    return figure


@st.cache_data(ttl=60)
def requete(query: str, params: tuple = ()) -> pd.DataFrame:
    return lire(query, params)


@st.cache_resource
def modeles_ml():
    from backend.forecasting_ml import chemin_modele, load_models

    if not (chemin_modele("charge").exists() and chemin_modele("pv").exists()):
        return None
    return load_models()


@st.cache_data(show_spinner="Recalcul de la simulation en mémoire…")
def simulation_sandbox(scenario: str, mode: str, capacite: float) -> dict:
    """Rejoue le scénario avec une autre capacité STEG ; rien n'est écrit en base."""
    from backend.forecasting_ml import previsions_demande_nette
    from backend.simulation import preparer_entrees, simuler_scenario

    entrees = preparer_entrees(load_measurements(scenario))
    sessions = load_ev_sessions()
    previsions = None
    if mode == "predictif":
        modeles = modeles_ml()
        if modeles is None:
            return {}
        previsions = previsions_demande_nette(entrees["quartier"], scenario, modeles)
    modes = ["sans_orchestration"] if mode == "sans_orchestration" else ["sans_orchestration", mode]
    resultats = {m: simuler_scenario(entrees, sessions, scenario, m, capacite, previsions if m == "predictif" else None) for m in modes}
    bilan = pd.concat([r["bilan"] for r in resultats.values()], ignore_index=True)
    return {
        "bilan": bilan[bilan["mode"] == mode],
        "kpi": calculer_kpi(bilan).query("mode == @mode"),
        "actions": resultats[mode]["actions"],
        "etat_batteries": resultats[mode]["etat_batteries"],
    }


def donnees_du_jour(scenario, mode, jour, capacite):
    if capacite == STEG_CAPACITY_KW:
        params = (scenario, mode, jour)
        return {
            "bilan": requete("SELECT * FROM bilan_horaire WHERE scenario = ? AND mode = ? AND jour = ? ORDER BY heure", params),
            "kpi": requete("SELECT * FROM kpi_results WHERE scenario = ? AND mode = ? AND jour = ?", params),
            "actions": requete("SELECT * FROM orchestrator_actions WHERE scenario = ? AND mode = ? AND jour = ? ORDER BY heure, id", params),
            "etat_batteries": requete("SELECT * FROM etat_batteries WHERE scenario = ? AND mode = ? AND jour = ? ORDER BY heure, device_id", params),
        }
    resultat = simulation_sandbox(scenario, mode, float(capacite))
    if not resultat:
        return {}
    return {cle: df[df["jour"] == jour] for cle, df in resultat.items()}


def carte_metriques(metriques, colonnes=4):
    for debut in range(0, len(metriques), colonnes):
        cols = st.columns(colonnes)
        for col, item in zip(cols, metriques[debut: debut + colonnes]):
            with col, st.container(border=True):
                st.metric(item["label"], item["value"], delta=item.get("delta"), delta_color=item.get("delta_color", "normal"),
                          help=item.get("help"))


def fmt(valeur, decimales=1):
    return f"{valeur:,.{decimales}f}".replace(",", " ").replace(".", ",")


# ---------------------------------------------------------------------------
st.title("iDER | STEG et ressources distribuées")
st.caption("STEG est la source de base du quartier ; les DER couvrent le déficit. Lecture directe de SQLite.")

if not schema_a_jour() or requete("SELECT COUNT(*) AS n FROM bilan_horaire")["n"].iloc[0] == 0:
    st.error("Base absente, ancienne ou incomplète. Lancez `python run_pipeline.py` depuis la racine du projet.")
    st.stop()

dates = requete("SELECT DISTINCT jour, date FROM measurements ORDER BY jour")
scenarios_dispo = requete("SELECT DISTINCT scenario FROM bilan_horaire")["scenario"].tolist()
with st.sidebar:
    st.markdown('<div class="ider-brand">iDER</div>', unsafe_allow_html=True)
    st.markdown('<div class="ider-brand-note">STEG + orchestration des DER</div>', unsafe_allow_html=True)
    st.divider()
    scenario = st.selectbox("Scénario", [s for s in SCENARIOS if s in scenarios_dispo], format_func=LIBELLES_SCENARIOS.get,
                            key="scenario")
    date_par_jour = dict(zip(dates["jour"], dates["date"]))
    jour = st.selectbox(
        "Jour", dates["jour"].tolist(), index=len(dates) - 1, key="jour",
        format_func=lambda j: f"{date_par_jour[j]} · jour {j}" + (" · test ML" if j >= JOUR_DEBUT_TEST else ""),
    )
    mode = st.radio("Mode", MODES, index=1, format_func=LIBELLES_MODES.get, key="mode")
    capacite = st.slider("Capacité STEG (kW) · sandbox", min_value=100, max_value=220, value=int(STEG_CAPACITY_KW), step=5, key="capacite",
                         help="Toute autre valeur que 150 kW recalcule la simulation en mémoire, sans rien enregistrer.")
    st.markdown(
        """
        <div class="ider-legend">
          <div class="legend-line"><span class="legend-dot" style="background:#0B3D2E"></span>STEG</div>
          <div class="legend-line"><span class="legend-dot" style="background:#E9C46A"></span>PV</div>
          <div class="legend-line"><span class="legend-dot" style="background:var(--green-500)"></span>Ressources DER</div>
          <div class="legend-line"><span class="legend-dot" style="background:var(--alert)"></span>Dépassement / non desservi</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

donnees = donnees_du_jour(scenario, mode, jour, capacite)
if capacite != STEG_CAPACITY_KW:
    st.markdown(f'<div class="sandbox-note">Sandbox : capacité STEG de {capacite} kW. Résultats recalculés en mémoire sur toute la '
                f'période (état continu des batteries), non enregistrés.</div>', unsafe_allow_html=True)
if not donnees or donnees["bilan"].empty:
    st.warning("Aucune donnée pour cette sélection (les modèles ML sont peut-être absents pour le mode prédictif).")
    st.stop()

bilan = donnees["bilan"]
st.subheader(f"{LIBELLES_SCENARIOS[scenario]} · {date_par_jour[jour]} · {LIBELLES_MODES[mode]}")
if not donnees["kpi"].empty:
    k = donnees["kpi"].iloc[0]
    ecart_capacite = k["pic_steg_apres_kw"] - capacite
    carte_metriques([
        {"label": "Pic STEG avant", "value": f"{fmt(k['pic_steg_avant_kw'])} kW", "help": "Sans orchestration : max horaire de l'import STEG."},
        {"label": "Pic STEG après", "value": f"{fmt(k['pic_steg_apres_kw'])} kW",
         "delta": f"{fmt(ecart_capacite)} kW vs capacité" if abs(ecart_capacite) >= 0.05 else "au niveau de la capacité",
         "delta_color": "inverse" if abs(ecart_capacite) >= 0.05 else "off"},
        {"label": "Réduction du pic", "value": f"{fmt(k['reduction_pic_pct'])} %"},
        {"label": "Énergie déplacée", "value": f"{fmt(k['energie_deplacee_kwh'])} kWh", "help": "Décharge batteries + recharge VE reportée + HVAC réduit."},
        {"label": "Taux d'autonomie", "value": f"{fmt(k['taux_autonomie_pct'])} %", "help": "1 − énergie STEG / consommation servie."},
        {"label": "Économie", "value": f"{fmt(k['economie_tnd'], 2)} TND", "help": "Facture sans orchestration − facture du mode (tarifs illustratifs)."},
        {"label": "CO2 évité", "value": f"{fmt(k['co2_evite_kg'], 2)} kg", "help": "Peut être négatif : pertes de rendement des batteries."},
        {"label": "Énergie non desservie", "value": f"{fmt(k['energie_non_desservie_kwh'], 2)} kWh"},
    ])
st.caption(
    f"Tarifs ILLUSTRATIFS (à remplacer par la grille officielle STEG) : creux {TARIF_CREUX_TND_KWH}, plein {TARIF_PLEIN_TND_KWH}, "
    f"pointe {TARIF_POINTE_TND_KWH} TND/kWh. Facteur CO2 illustratif : {FACTEUR_CO2_KG_KWH} kg/kWh."
)

onglet_bilan, onglet_ml, onglet_comparaison, onglet_actions, onglet_parc = st.tabs(
    ["Bilan énergétique", "Prévision ML", "Réactif vs Prédictif", "Actions de l'orchestrateur", "Parc de ressources"]
)

with onglet_bilan:
    figure = go.Figure()
    for colonne, (libelle, couleur) in COULEURS_SOURCES.items():
        if bilan[colonne].abs().sum() > 1e-9:
            figure.add_trace(go.Bar(x=bilan["heure"], y=bilan[colonne], name=libelle, marker_color=couleur))
    figure.add_trace(go.Scatter(x=bilan["heure"], y=bilan["charge_totale_kw"], name="Charge totale (dont recharge batteries)",
                                mode="lines+markers", line={"color": COULEURS["text"], "width": 2}))
    figure.add_trace(go.Scatter(x=bilan["heure"], y=bilan["steg_disponible_kw"], name="Capacité STEG disponible",
                                mode="lines", line={"color": COULEURS["alert"], "width": 2, "dash": "dash", "shape": "hv"}))
    figure.update_layout(barmode="stack", xaxis={"dtick": 1})
    st.plotly_chart(mise_en_page(figure, "Couverture horaire de la charge du quartier", "Heure", "Puissance (kW)", 470), width="stretch")
    if mode == "sans_orchestration" and bilan["depassement_steg_kw"].max() > 0:
        st.markdown(f'<div class="alert-note">Sans orchestration, STEG dépasse sa capacité de '
                    f'{fmt(bilan["depassement_steg_kw"].max())} kW au maximum ({fmt(bilan["depassement_steg_kw"].sum())} kWh sur la journée).</div>',
                    unsafe_allow_html=True)
    st.caption("Identité vérifiée à chaque heure : STEG + contribution DER + PV utilisé + énergie non desservie = charge totale.")

    etat = donnees["etat_batteries"]
    if not etat.empty:
        soc = go.Figure()
        for device_id, serie in etat.groupby("device_id"):
            soc.add_trace(go.Scatter(x=serie["heure"], y=serie["soc"] * 100, name=device_id, mode="lines"))
        soc.add_hline(y=SOC_CIBLE * 100, line_dash="dot", line_color=COULEURS["green_700"], annotation_text="SoC cible")
        st.plotly_chart(mise_en_page(soc, "État de charge des batteries (fin d'heure)", "Heure", "SoC (%)", 340), width="stretch")
    with st.expander("Tableau horaire du bilan"):
        st.dataframe(bilan.drop(columns=["scenario", "mode", "date", "jour"]).round(3), width="stretch", hide_index=True)

with onglet_ml:
    st.markdown('<div class="alert-note">Données synthétiques : le modèle apprend en partie le générateur. Les performances ci-dessous '
                'ne sont pas transférables à un réseau réel.</div>', unsafe_allow_html=True)
    metriques = requete("SELECT * FROM model_metrics WHERE split = 'test'")
    if metriques.empty:
        st.info("Aucune métrique en base. Lancez `python run_pipeline.py`.")
    else:
        cible = st.selectbox("Grandeur prévue (T+1 h)", list(LIBELLES_CIBLES), format_func=LIBELLES_CIBLES.get)
        scenario_ml = scenario if scenario in SCENARIOS_METEO else "normal"
        jours_test = requete("SELECT DISTINCT jour, date FROM forecasts WHERE split = 'test' ORDER BY jour")
        jour_ml = st.selectbox("Jour de test", jours_test["jour"].tolist(),
                               format_func=lambda j: dict(zip(jours_test["jour"], jours_test["date"]))[j])
        prev = requete("SELECT * FROM forecasts WHERE scenario = ? AND jour = ? AND cible = ? ORDER BY heure",
                       (scenario_ml, jour_ml, cible))
        courbe = go.Figure()
        reel = prev[prev["modele"] == "ml"]
        courbe.add_trace(go.Scatter(x=reel["heure"], y=reel["y_true"], name="Réel", mode="lines+markers",
                                    line={"color": COULEURS["text"], "width": 3}))
        for modele, couleur in (("ml", COULEURS["green_500"]), ("baseline", "#E9C46A"), ("persistance", COULEURS["green_300"])):
            part = prev[prev["modele"] == modele]
            courbe.add_trace(go.Scatter(x=part["heure"], y=part["y_pred"], name=LIBELLES_MODELES[modele], mode="lines",
                                        line={"color": couleur, "width": 2, "dash": "solid" if modele == "ml" else "dash"}))
        if cible == "demande_nette":
            courbe.add_hline(y=STEG_CAPACITY_KW, line_dash="dot", line_color=COULEURS["alert"], annotation_text="Capacité STEG")
        st.plotly_chart(mise_en_page(courbe, f"{LIBELLES_CIBLES[cible]} : prévu vs réel ({LIBELLES_SCENARIOS[scenario_ml]})",
                                     "Heure", "Puissance (kW)"), width="stretch")

        tableau = metriques.copy()
        tableau["modele"] = tableau["modele"].map(LIBELLES_MODELES)
        tableau["cible"] = tableau["cible"].map(LIBELLES_CIBLES)
        tableau = tableau.rename(columns={
            "modele": "Modèle", "cible": "Cible", "mae_kw": "MAE (kW)", "rmse_kw": "RMSE (kW)", "mape_pct": "MAPE (%)",
            "mae_pointe_kw": "MAE 17h-22h (kW)", "precision_deficit": "Précision déficit", "rappel_deficit": "Rappel déficit",
            "faux_positifs": "Faux positifs", "faux_negatifs": "Faux négatifs", "n_echantillons": "Échantillons",
        })
        st.markdown("**Métriques sur la période de test (tous scénarios météo)**")
        st.dataframe(tableau.drop(columns=["split", "horizon_h", "vrais_positifs"]).round(3), width="stretch", hide_index=True)
        st.caption(f"MAPE calculé seulement quand la valeur réelle dépasse {MAPE_SEUIL_KW} kW (PV nul la nuit). Déficit = demande nette "
                   f"> {STEG_CAPACITY_KW:.0f} kW. Météo prévue = réelle + bruit gaussien (σ {WEATHER_FORECAST_NOISE_TEMP_C} °C, "
                   f"{WEATHER_FORECAST_NOISE_IRR_WM2} W/m²).")

        col_hist, col_imp = st.columns(2)
        erreurs = requete("SELECT modele, y_pred - y_true AS erreur FROM forecasts WHERE split = 'test' AND cible = ? AND modele IN ('ml', 'baseline')",
                          (cible,))
        hist = go.Figure()
        for modele, couleur in (("baseline", "#E9C46A"), ("ml", COULEURS["green_500"])):
            hist.add_trace(go.Histogram(x=erreurs.loc[erreurs["modele"] == modele, "erreur"], name=LIBELLES_MODELES[modele],
                                        marker_color=couleur, opacity=0.75, nbinsx=50))
        hist.update_layout(barmode="overlay")
        col_hist.plotly_chart(mise_en_page(hist, "Distribution de l'erreur (test)", "Erreur prévu − réel (kW)", "Nombre d'heures", 380),
                              width="stretch")
        cible_imp = "pv" if cible == "pv" else "charge"
        importances = requete("SELECT feature, importance FROM feature_importances WHERE cible = ? ORDER BY importance", (cible_imp,))
        barres = go.Figure(go.Bar(x=importances["importance"], y=importances["feature"], orientation="h",
                                  marker_color=COULEURS["green_700"], name="Importance"))
        col_imp.plotly_chart(mise_en_page(barres, f"Importance des variables (modèle {LIBELLES_CIBLES[cible_imp].lower()})",
                                          "Importance (réduction d'impureté)", "Variable", 380), width="stretch")

with onglet_comparaison:
    kpi_test = requete("SELECT * FROM kpi_results WHERE jour >= ?", (JOUR_DEBUT_TEST,))
    if kpi_test.empty:
        st.info("Aucun KPI sur la période de test.")
    else:
        st.markdown(f"Période de test ML : jours {JOUR_DEBUT_TEST} à {N_DAYS - 1}, capacité STEG {STEG_CAPACITY_KW:.0f} kW.")
        synthese = synthese_kpi(kpi_test)
        barres = go.Figure()
        for m in MODES:
            part = synthese[synthese["mode"] == m]
            barres.add_trace(go.Bar(x=part["scenario"].map(LIBELLES_SCENARIOS), y=part["pic_steg_apres_kw"], name=LIBELLES_MODES[m],
                                    marker_color=COULEURS_MODES[m]))
        barres.add_hline(y=STEG_CAPACITY_KW, line_dash="dash", line_color=COULEURS["alert"], annotation_text="Capacité STEG")
        barres.update_layout(barmode="group")
        col_pic, col_eco = st.columns(2)
        col_pic.plotly_chart(mise_en_page(barres, "Pic STEG maximal par scénario", "Scénario", "Puissance (kW)", 380), width="stretch")
        eco = go.Figure()
        for m in ("reactif", "predictif"):
            part = synthese[synthese["mode"] == m]
            eco.add_trace(go.Bar(x=part["scenario"].map(LIBELLES_SCENARIOS), y=part["economie_tnd"], name=LIBELLES_MODES[m],
                                 marker_color=COULEURS_MODES[m]))
        eco.update_layout(barmode="group")
        col_eco.plotly_chart(mise_en_page(eco, "Économie cumulée sur la période de test", "Scénario", "Économie (TND)", 380), width="stretch")
        affichage = synthese.assign(scenario=synthese["scenario"].map(LIBELLES_SCENARIOS), mode=synthese["mode"].map(LIBELLES_MODES)).rename(columns={
            "scenario": "Scénario", "mode": "Mode", "jours": "Jours", "pic_steg_avant_kw": "Pic avant (kW)",
            "pic_steg_apres_kw": "Pic après (kW)", "reduction_pic_moy_pct": "Réduction moy. (%)",
            "energie_deplacee_kwh": "Énergie déplacée (kWh)", "energie_steg_kwh": "Énergie STEG (kWh)",
            "consommation_kwh": "Consommation (kWh)", "facture_steg_tnd": "Facture (TND)", "economie_tnd": "Économie (TND)",
            "co2_evite_kg": "CO2 évité (kg)", "energie_non_desservie_kwh": "Non desservi (kWh)",
            "depassement_steg_kwh": "Dépassement STEG (kWh)", "taux_autonomie_pct": "Autonomie (%)",
        })
        st.dataframe(affichage.round(2), width="stretch", hide_index=True)
        st.caption("Le prédictif reporte plus tôt la recharge des VE quand un pic est prévu, ce qui épargne les batteries ; "
                   "son effet sur la facture reste faible et n'est pas garanti sur chaque scénario.")

with onglet_actions:
    actions = donnees["actions"]
    if mode == "sans_orchestration":
        st.info("Aucune action : la référence « sans orchestration » ne pilote aucune ressource.")
    elif actions.empty:
        st.info("Aucune action enregistrée pour cette journée.")
    else:
        declencheurs = {"deficit": "Couverture du déficit", "anticipation": "Anticipation (prévision ML)", "recharge": "Recharge batteries"}
        choix = st.multiselect("Déclencheur", list(declencheurs), default=list(declencheurs), format_func=declencheurs.get)
        filtre = actions[actions["declencheur"].isin(choix)]
        resume = filtre.groupby(["declencheur", "device_type"])["power_kw"].agg(["count", "sum"]).reset_index()
        st.caption(" · ".join(f"{declencheurs[r.declencheur]} / {r.device_type} : {r['count']} actions, {fmt(r['sum'])} kWh"
                              for _, r in resume.iterrows()))
        st.dataframe(
            filtre.assign(power_kw=filtre["power_kw"].round(2), declencheur=filtre["declencheur"].map(declencheurs))[
                ["heure", "device_id", "device_type", "action_type", "declencheur", "power_kw", "justification"]
            ].rename(columns={"heure": "Heure", "device_id": "Ressource", "device_type": "Type", "action_type": "Action",
                              "declencheur": "Déclencheur", "power_kw": "Puissance (kW)", "justification": "Justification"}),
            width="stretch", hide_index=True,
        )

with onglet_parc:
    mesures = requete("SELECT * FROM measurements WHERE scenario = ? AND jour = ?", (scenario, jour))
    sessions = requete("SELECT * FROM ev_sessions WHERE jour = ?", (jour,))
    etat_fin = donnees["etat_batteries"]
    etat_fin = etat_fin[etat_fin["heure"] == etat_fin["heure"].max()] if not etat_fin.empty else etat_fin
    onglet_bat, onglet_ve, onglet_pv, onglet_hvac = st.tabs(["Batteries", "VE", "PV", "HVAC"])
    with onglet_bat:
        st.caption("SoC à 23h et score d'équité cumulé depuis le début de la période (kWh déchargés).")
        lignes = list(etat_fin.itertuples())
        for debut in range(0, len(lignes), 4):
            for col, row in zip(st.columns(4), lignes[debut: debut + 4]):
                with col, st.container(border=True):
                    st.markdown(f'<div class="resource-title">{escape(row.device_id)}</div>', unsafe_allow_html=True)
                    st.markdown(
                        f'<div class="soc-track"><div class="soc-fill" style="width:{row.soc * 100:.1f}%;background:var(--green-700)"></div></div>'
                        f'<div class="resource-meta">SoC {row.soc * 100:.0f} % · stress {row.stress_score:.1f} kWh</div>',
                        unsafe_allow_html=True,
                    )
    with onglet_ve:
        if sessions.empty:
            st.info("Aucune session VE ce jour.")
        else:
            st.dataframe(sessions.rename(columns={"house_id": "Maison", "arrivee_h": "Arrivée (h)", "depart_h": "Départ le lendemain (h)",
                                                  "soc_arrivee": "SoC arrivée", "energie_kwh": "Énergie à livrer (kWh)"})
                         .drop(columns=["jour", "date"]).round(2), width="stretch", hide_index=True)
    with onglet_pv:
        pv = mesures[mesures["pv_kw"] > 0].groupby("house_id")["pv_kw"].agg(["max", "sum"]).reset_index()
        st.dataframe(pv.rename(columns={"house_id": "Maison", "max": "Puissance max (kW)", "sum": "Production du jour (kWh)"}).round(2),
                     width="stretch", hide_index=True)
    with onglet_hvac:
        hvac = mesures.groupby("house_id")["hvac_kw"].agg(["mean", "max", "sum"]).reset_index()
        st.dataframe(hvac.rename(columns={"house_id": "Maison", "mean": "Moyenne (kW)", "max": "Max (kW)", "sum": "Énergie (kWh)"}).round(2),
                     width="stretch", hide_index=True)
