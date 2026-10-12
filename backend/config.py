"""Constantes du quartier iDER : STEG, ressources DER, scénarios, tarifs et ML.

Toutes les puissances sont en kW, les énergies en kWh, les états de charge
(SoC) en fraction de 0 à 1, les tarifs en TND/kWh.
"""

from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- Reproductibilité et période -------------------------------------------
SEED = 42                      # graine unique du générateur aléatoire
N_DAYS = 45                    # jours générés (nécessaire pour entraîner le ML)

# --- Quartier ---------------------------------------------------------------
NB_MAISONS = 20
MAISONS_AVEC_PV = 13           # maisons H01..H13
MAISONS_AVEC_BATTERIE = 7      # maisons H01..H07
MAISONS_AVEC_EV = 8            # maisons H01..H08

# --- STEG : source de base du quartier -------------------------------------
STEG_CAPACITY_KW = 150.0       # capacité maximale fournie par STEG au quartier (kW)
HEURES_CREUSES = list(range(23, 24)) + list(range(0, 6))   # 23h-6h
HEURES_POINTE = [18, 19, 20, 21]
FENETRE_POINTE_SOIR = list(range(17, 23))                   # 17h-22h, pointe du soir

# Tarifs ILLUSTRATIFS en TND/kWh, à remplacer par la grille officielle STEG (à vérifier)
TARIF_CREUX_TND_KWH = 0.15
TARIF_PLEIN_TND_KWH = 0.25
TARIF_POINTE_TND_KWH = 0.35
# Facteur d'émission ILLUSTRATIF du réseau, kg CO2 par kWh (à sourcer avant soutenance)
FACTEUR_CO2_KG_KWH = 0.45

# --- Scénarios --------------------------------------------------------------
SCENARIOS_METEO = ["normal", "nuageux", "canicule"]
SCENARIO_COUPURE = "coupure_steg"
SCENARIOS = SCENARIOS_METEO + [SCENARIO_COUPURE]
MODES = ["sans_orchestration", "reactif", "predictif"]

# Scénario coupure_steg : copie du scénario normal avec STEG indisponible
COUPURE_JOURS_AVANT_FIN = 3    # la coupure a lieu le jour (N_DAYS - 3), dans la période de test
COUPURE_HEURES = [20, 21, 22]  # 20h-23h, STEG fournit 0 kW

# Écarts météo appliqués au scénario normal (°C et facteur d'ensoleillement)
ECART_TEMPERATURE_NUAGEUX_C = -2.0
ECART_TEMPERATURE_CANICULE_C = (8.0, 12.0)    # tirage uniforme par jour
FACTEUR_NUAGES_NORMAL = (0.75, 1.0)           # couverture nuageuse journalière
FACTEUR_NUAGES_NUAGEUX = (0.30, 0.50)         # ≈ 0,4 en moyenne
FACTEUR_NUAGES_CANICULE = (0.95, 1.0)

# --- Profil de charge (kW par maison, jour ouvré, avant facteurs) ----------
PROFIL_BASE_KW = [
    1.3, 1.2, 1.1, 1.1, 1.1, 1.3,     # 0h-5h
    2.2, 3.2, 3.0, 2.4, 2.2, 2.2,     # 6h-11h
    2.6, 2.6, 2.2, 2.2, 2.6, 4.2,     # 12h-17h
    5.6, 6.4, 6.4, 5.6, 4.2, 2.6,     # 18h-23h
]
FACTEUR_WEEKEND_JOURNEE = 1.30         # 9h-16h : présence accrue le week-end
FACTEUR_WEEKEND_MATIN = 0.85           # 6h-8h : réveil plus tardif
OCCUPATION_HVAC = [0.3] * 6 + [0.6] * 3 + [0.4] * 8 + [1.0] * 6 + [0.5]   # 0h..23h
OCCUPATION_HVAC_WEEKEND_JOURNEE = 0.8
HVAC_KW_FIXE = 0.25                    # ventilation/veille par maison (kW)
HVAC_KW_PAR_DEGRE = 0.11               # kW par °C au-dessus du seuil
HVAC_SEUIL_C = 21.0

# --- Météo ------------------------------------------------------------------
TEMPERATURE_MOYENNE_C = 24.0
TEMPERATURE_AMPLITUDE_C = 6.0          # pic vers 15h
IRRADIANCE_CIEL_CLAIR_WM2 = 950.0
LEVER_SOLEIL_H = 6.0
COUCHER_SOLEIL_H = 19.5

# --- PV ---------------------------------------------------------------------
PV_PUISSANCE_CRETE_KWC = (3.0, 4.0)    # tirage par maison équipée
PV_PERFORMANCE_RATIO = 0.85
PV_PERTE_PAR_DEGRE = 0.004             # baisse de rendement au-dessus de 25 °C

# --- Batteries --------------------------------------------------------------
BATTERY_CAPACITY_KWH = 10.0
BATTERY_MAX_POWER_KW = 5.0             # charge et décharge
SOC_MIN = 0.10
SOC_MAX = 1.0
SOC_CIBLE = 0.90                       # cible de recharge en heures creuses
SOC_INIT = 0.50                        # SoC au début de chaque scénario
ROUND_TRIP_EFFICIENCY = 0.90           # appliqué à la charge : 1 kWh acheté -> 0,9 kWh stocké

# --- Véhicules électriques ---------------------------------------------------
EV_BATTERY_CAPACITY_KWH = 60.0
EV_MAX_CHARGE_KW = 7.0
EV_TARGET_SOC = 0.90
EV_ARRIVEE_MOYENNE_H = 18.3
EV_DEPART_MOYEN_H = 7.0
EV_SOC_ARRIVEE_SEMAINE = (0.55, 0.80)
EV_SOC_ARRIVEE_WEEKEND = (0.70, 0.85)

# --- HVAC -------------------------------------------------------------------
HVAC_REDUCTION_MAX = 0.30              # réduction maximale tolérée (confort), fraction de la demande

# --- Prévision ML -----------------------------------------------------------
FORECAST_SAFETY_MARGIN = 0.05          # marge de sécurité sur le déficit prévu
WEATHER_FORECAST_NOISE_TEMP_C = 1.0    # écart-type de l'erreur de prévision météo (°C)
WEATHER_FORECAST_NOISE_IRR_WM2 = 50.0  # écart-type de l'erreur de prévision d'irradiance (W/m²)
MAPE_SEUIL_KW = 5.0                    # MAPE calculé seulement quand la valeur réelle dépasse ce seuil
SPLIT_TRAIN = 0.70
SPLIT_VAL = 0.15
MODEL_DIR = ROOT / "models"


def tarif_tnd_kwh(heure):
    """Tarif STEG illustratif (TND/kWh) selon l'heure : creux, pointe ou plein."""
    if heure in HEURES_CREUSES:
        return TARIF_CREUX_TND_KWH
    if heure in HEURES_POINTE:
        return TARIF_POINTE_TND_KWH
    return TARIF_PLEIN_TND_KWH


def dates_simulation(n_days=N_DAYS, date_fin=None):
    """Dates de la période simulée, la dernière étant aujourd'hui (calcul dynamique)."""
    fin = date_fin or date.today()
    return [fin - timedelta(days=n_days - 1 - jour) for jour in range(n_days)]
