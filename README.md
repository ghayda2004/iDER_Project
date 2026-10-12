# iDER — STEG et orchestration des ressources distribuées

## Table des matières

- [1. Concept](#1-concept)
- [2. Exécution](#2-exécution)
- [3. Architecture et structure](#3-architecture-et-structure)
- [4. Bilan énergétique](#4-bilan-énergétique)
- [5. Jeu de données](#5-jeu-de-données)
- [6. Base de données](#6-base-de-données)
- [7. Orchestration : modes et règles](#7-orchestration--modes-et-règles)
- [8. Prévision ML](#8-prévision-ml)
- [9. KPI : formules et unités](#9-kpi--formules-et-unités)
- [10. Résultats mesurés](#10-résultats-mesurés)
- [11. Tableau de bord](#11-tableau-de-bord)
- [12. Tests](#12-tests)
- [13. Limites](#13-limites)
- [14. Équipe](#14-équipe)

## 1. Concept

Proof-of-concept académique (cours « Digital Grid and Business Value »). Un quartier résidentiel de 20 maisons est alimenté par **STEG, source d'énergie de base**, dont la capacité est limitée à `STEG_CAPACITY_KW = 150 kW`. Les ressources distribuées (DER) — 13 installations PV, 7 batteries, 8 véhicules électriques (VE), 20 climatisations (HVAC) — servent à **couvrir le déficit**, c'est-à-dire la part de la demande que STEG ne peut pas fournir, et à décaler les achats vers les heures creuses.

Une **prévision par Machine Learning** (forêt aléatoire) de la charge et du PV à T+1 h permet un mode **prédictif**, comparé à un mode **réactif** et à une référence **sans orchestration**.

Les données sont synthétiques ; aucun matériel réel n'est piloté. Les tarifs et le facteur CO2 sont **illustratifs**.

Explication complète, avec les valeurs réelles de la base suivies sur une journée : [docs/DOCUMENTATION_DETAILLEE.md](docs/DOCUMENTATION_DETAILLEE.md).

## 2. Exécution

Environnement vérifié : Python 3.11.9 sous Windows.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python run_pipeline.py            # données -> modèles ML -> simulations -> KPI (~30 s)
python -m pytest -q               # 28 tests
streamlit run app.py              # tableau de bord
```

`run_pipeline.py --validation-lp` ajoute la comparaison règles/LP. Les étapes peuvent aussi être lancées séparément : `python backend/generate_dataset.py`, `python backend/forecasting_ml.py`, `python backend/simulation.py`, `python backend/optimizer_lp.py`.

`ider.db` et `models/` sont des artefacts régénérés (graine fixe) et ne sont pas versionnés.

**Vidéo de démonstration (~4 min)** : avec le tableau de bord lancé sur le port 8501, `python demo/generer_video_demo.py` produit `demo/iDER_demo.mp4`. Le script pilote Microsoft Edge (Playwright), alterne des écrans animés ([demo/animations.py](demo/animations.py) : intro, ressources, orchestration, modes, fin) et des passages dans le tableau de bord, ajoute les sous-titres et une voix off française (synthèse vocale Windows), puis assemble le tout avec ffmpeg. La voix est calée sur l'image grâce à des marqueurs de couleur, effacés au montage. Il nécessite `pip install playwright imageio-ffmpeg`. Les chiffres cités sont lus dans la base au moment de la génération.

## 3. Architecture et structure

```text
config.py (constantes, tarifs, dates dynamiques)
     |
generate_dataset.py --> measurements, ev_sessions (SQLite)
     |
forecasting_ml.py ----> models/*.joblib, forecasts, model_metrics, feature_importances
     |
simulation.py --------> bilan_horaire, etat_batteries, orchestrator_actions, kpi_results
  |-- models.py         Battery / EV / HVAC (état continu sur la période)
  |-- orchestrator.py   dispatch par ordre de mérite
  +-- kpi.py            agrégation quartier et KPI
     |
app.py (Streamlit) ---> lit SQLite ; sandbox = simulation en mémoire
optimizer_lp.py ------> validation d'optimalité, hors boucle principale
```

| Fichier | Rôle |
|---|---|
| `backend/config.py` | Constantes commentées avec unités, `tarif_tnd_kwh(heure)`, `dates_simulation()`. |
| `backend/generate_dataset.py` | Profils synthétiques, météo, sessions VE, scénario de coupure ; un seul `rng`. |
| `backend/database.py` | Schéma SQLite, lecture/écriture. |
| `backend/models.py` | Batterie (SoC, rendement, `stress_score`), VE (report borné par le départ), HVAC. |
| `backend/orchestrator.py` | `dispatch()` : batteries → VE → HVAC, plafond d'équité, ordre de délestage. |
| `backend/simulation.py` | Bilan horaire, recharge des batteries, modes réactif/prédictif, persistance. |
| `backend/kpi.py` | Agrégation par somme des maisons, KPI journaliers et synthèse. |
| `backend/forecasting_ml.py` | Variables sans fuite, découpage chronologique, 3 modèles, métriques. |
| `backend/optimizer_lp.py` | LP PuLP comparé aux règles sur chaque heure de déficit. |
| `run_pipeline.py` | Enchaîne tout et imprime le rapport. |
| `app.py` | Tableau de bord. |

## 4. Bilan énergétique

Pour un scénario, une heure et un mode, au niveau du quartier (somme des 20 maisons) :

```text
charge_totale_kw   = base + HVAC + recharge VE demandée + recharge batteries
pv_utilise_kw      = min(pv_kw, charge_totale_kw)
demande_nette_kw   = charge_totale_kw - pv_utilise_kw        (= max(charge - PV, 0))
steg_disponible_kw = STEG_CAPACITY_KW, ou 0 pendant une coupure
deficit_kw         = max(demande_nette_kw - steg_disponible_kw, 0)
contribution_DER   = décharge batteries + recharge VE reportée + HVAC réduit
energie_non_desservie_kw = max(demande_nette_kw - contribution_DER - steg_disponible_kw, 0)
steg_import_kw     = demande_nette_kw - contribution_DER - energie_non_desservie_kw
```

Identité vérifiée à chaque heure de chaque mode (tolérance 1e-6, test `test_bilan_energetique`) :

```text
steg_import + contribution_DER + pv_utilise + energie_non_desservie = charge_totale
```

Le surplus PV éventuel sert d'abord à recharger les batteries. Au niveau du quartier, la production PV reste inférieure à la charge à toute heure dans les données générées, donc ce cas n'apparaît pas en pratique.

**Sans orchestration**, STEG fournit toute la demande nette, même au-delà de sa capacité : l'excès est compté comme `depassement_steg_kw` (surcharge), pas comme énergie non desservie.

### Recharge des batteries

Dans les modes orchestrés, une batterie se recharge (1) avec le surplus PV, puis (2) avec STEG pendant les heures creuses (23h-6h) jusqu'à `SOC_CIBLE = 0,90`, uniquement dans la marge restante sous la capacité STEG. Le rendement `ROUND_TRIP_EFFICIENCY = 0,90` s'applique à la charge (1 kWh acheté → 0,9 kWh stocké). SoC borné à [0,10 ; 1,0], puissance maximale de 5 kW en charge et en décharge.

### État continu

Pour chaque scénario et chaque mode, les objets DER sont créés une seule fois (SoC initial 0,50) et leur état se propage sur les 45 jours. La recharge de nuit prépare la pointe du lendemain. `stress_score` (kWh déchargés cumulés) ne diminue jamais. La table `etat_batteries` enregistre le SoC de début et de fin de chaque heure, et le test `test_stress_score_monotone_et_continuite` vérifie la continuité, y compris à minuit.

## 5. Jeu de données

- **Période** : `N_DAYS = 45` jours se terminant à la date du jour (`date.today()`). Aucune date n'est codée en dur.
- **Scénarios** :
  - `normal` ;
  - `nuageux` : couverture nuageuse ≈ 0,4, température −2 °C ;
  - `canicule` : +8 à +12 °C selon le jour ;
  - `coupure_steg` : copie exacte de `normal`, avec STEG indisponible de 20h à 23h le jour `N_DAYS − 3`.
- **Reproductibilité** : `rng = np.random.default_rng(SEED)` est créé une fois avant toutes les boucles. Les tirages de charge, de bruit et de VE sont partagés entre scénarios, si bien que seule la météo les distingue.
- **Charge de base** : profil horaire par maison (`PROFIL_BASE_KW`) multiplié par :
  - un facteur de maison (0,85 à 1,15) ;
  - un facteur journalier N(1 ; 0,04) ;
  - un bruit horaire N(1 ; 0,05) ;
  - un facteur week-end (samedi et dimanche) : ×1,3 de 9h à 16h, ×0,85 de 6h à 8h.
- **HVAC** : occupation horaire × (0,25 + 0,11 kW/°C au-dessus de 21 °C).
- **Température** : sinusoïde (24 °C ± 6 °C, maximum vers 15h) + écart journalier N(0 ; 1,2) + bruit.
- **Irradiance** : courbe solaire de 6h à 19h30 (950 W/m² en ciel clair) × facteur nuageux journalier. PV = puissance crête (3 à 4 kWc) × irradiance × 0,85 × perte thermique (0,4 %/°C au-delà de 25 °C).
- **VE** : arrivée vers 18h (17h à 21h), départ le lendemain vers 7h, SoC d'arrivée de 0,55 à 0,80 (0,70 à 0,85 le week-end). Sans pilotage, recharge à 7 kW dès l'arrivée jusqu'à 90 %.
- **Forme de la courbe** : obtenue directement par les profils. L'ancienne calibration par facteur uniforme a été supprimée.

Pic journalier de demande nette agrégée sans orchestration, sur les 45 jours (sortie de `generate_dataset.py`) :

| Scénario | Moyenne (kW) | Min (kW) | Max (kW) | Max hors 17h-22h (kW) |
|---|---:|---:|---:|---:|
| normal | 180,75 | 147,95 | 203,98 | 71,92 |
| nuageux | 176,64 | 148,29 | 199,57 | 80,34 |
| canicule | 202,09 | 170,77 | 229,96 | 88,42 |

Le pic de `nuageux` est un peu plus bas que celui de `normal` : il fait 2 °C de moins, et le pic tombe à 19h, quand le PV est presque nul. En revanche, la production PV de 17h-18h y est environ 2,2 fois plus faible, ce qui rend la demande de fin d'après-midi plus élevée. Les jours de week-end dépendent de la date d'exécution : les chiffres peuvent donc varier légèrement d'un jour à l'autre.

## 6. Base de données

La base est régénérée par le pipeline (pas de migration de données). Lignes après `run_pipeline.py` :

| Table | Contenu | Lignes |
|---|---|---:|
| `measurements` | scénario, date, jour, heure, maison, `day_of_week`, `is_weekend`, `temperature_c`, `irradiance_wm2`, `steg_available`, `base_load_kw`, `hvac_kw`, `ev_charge_kw`, `ev_connected`, `ev_soc`, `pv_kw`, `charge_totale_kw` | 86 400 |
| `ev_sessions` | maison, jour d'arrivée, `arrivee_h`, `depart_h` (lendemain), `soc_arrivee`, `energie_kwh` | 360 |
| `bilan_horaire` | bilan de la section 4 par scénario, mode et heure, plus `prevision_demande_nette_kw` et `tarif_tnd_kwh` | 12 960 |
| `etat_batteries` | `soc_debut`, `soc`, `puissance_kw` (+ charge, − décharge), `stress_score` par batterie et par heure | 90 720 |
| `orchestrator_actions` | scénario, `mode` (`reactif`/`predictif`), heure, ressource, `action_type` (DISCHARGE, DELAY, REDUCE, CHARGE, PRECHARGE), `declencheur` (deficit, anticipation, recharge), `power_kw`, `justification` | 14 793 |
| `kpi_results` | KPI de la section 9 par scénario, mode et jour | 540 |
| `forecasts` | scénario, date, heure, `cible`, `y_pred`, `y_true`, `modele`, `split` | 28 512 |
| `model_metrics` | MAE, RMSE, MAPE, MAE en pointe, détection du déficit par modèle, cible et split | 27 |
| `feature_importances` | importance de chaque variable par cible | 22 |

L'ancienne colonne `grid_import_kw` (par maison) n'existe plus. L'import STEG est une grandeur du quartier, `bilan_horaire.steg_import_kw`. La simulation réécrit ses tables à chaque exécution (pas de doublons).

## 7. Orchestration : modes et règles

| Mode | Comportement |
|---|---|
| `sans_orchestration` | Référence « avant » : batteries inactives, VE rechargés dès l'arrivée, PV autoconsommé, STEG sans limite (dépassement compté). |
| `reactif` | À chaque heure, le déficit observé est couvert par batteries → VE (report) → HVAC (réduction de 30 % au plus). Recharge des batteries en heures creuses. |
| `predictif` | Comme le réactif, avec en plus la prévision ML de l'heure suivante. Si `demande_nette_prévue × 1,05 > capacité` : (a) préchargement des batteries sous `SOC_CIBLE` si STEG a de la marge à l'heure courante ; (b) les VE non urgents ne démarrent pas leur recharge pendant l'heure de pic prévue ; (c) la couverture réactive reste le filet de sécurité si la prévision est fausse. |

Règles importantes :

- **Équité des batteries** : tri par `stress_score` croissant. Une batterie est plafonnée à 50 % de sa puissance si une autre est plus sollicitée qu'elle. Cette règle répartit l'usure mais s'écarte de l'optimum de coût (section 10.4).
- **Report VE borné** : on ne reporte jamais plus que ce qui permet de finir la recharge avant le départ (`x ≤ P·(H−1) − E + demande`). Aucune recharge VE n'est restée incomplète au départ, dans aucun scénario.
- **Coupure STEG** : ordre de délestage batteries → HVAC (jusqu'à 100 %) → VE → charge de base (énergie non desservie). Le plafond d'équité est levé, car la continuité d'alimentation prime sur l'usure. Le quartier est supposé pouvoir fonctionner en îlot (le PV continue de produire).
- Les justifications sont lisibles, par exemple : « Pic prévu de 181 kW à 19 h -> recharge de VE-H03 non démarrée ».

## 8. Prévision ML

- **Cibles** : charge totale et PV du quartier à T+1 h. Demande nette prévue = max(charge − PV, 0).
- **Variables** (connues à t = T−1) :
  - `heure_sin`, `heure_cos`, `day_of_week`, `is_weekend` de T ;
  - météo prévue de T (`temperature_prevue_c`, `irradiance_prevue_wm2`) ;
  - `charge_lag_1h`, `charge_lag_24h`, `pv_lag_1h`, `pv_lag_24h` ;
  - `charge_moy_3h`, la moyenne de t−2 à t.
- **Prévision météo simulée** : valeur réelle + bruit gaussien (σ = 1 °C et 50 W/m², `WEATHER_FORECAST_NOISE_*`), reproductible par scénario. La nuit, l'irradiance prévue reste nulle.
- **Anti-fuite** : `test_pas_de_fuite_ml` falsifie toutes les données à partir d'une heure k et vérifie que les variables jusqu'à k sont inchangées.
- **Découpage chronologique** par jours entiers, sans mélange : 70 % train (jours 0 à 30), 15 % val (31 à 36), 15 % test (37 à 44). Le premier jour est exclu, faute de valeurs décalées de 24 h. Les scénarios météo sont mélangés dans chaque split ; `coupure_steg`, copie de `normal`, en est exclu.
- **Modèles** :
  - persistance (même heure la veille) ;
  - baseline (moyenne de la même heure sur les jours précédents du même scénario, version quartier de l'ancienne prévision) ;
  - ML : `RandomForestRegressor`, 200 arbres, `random_state = 42`. Choisi pour sa robustesse, son peu d'hyperparamètres et ses importances de variables natives. Profondeur et taille de feuille sont choisies sur val parmi {6, 9, 12} × {1, 4} ; résultat : profondeur 12, feuille 1. Un modèle par cible, sauvegardé dans `models/`.
- **MAPE** : calculé seulement quand la valeur réelle dépasse 5 kW (le PV est nul la nuit).

## 9. KPI : formules et unités

Calculés par (scénario, jour, mode) à partir de `bilan_horaire`, déjà agrégé par somme des maisons. Une ligne correspond à 1 h, donc kW × 1 h = kWh.

| KPI | Formule | Unité |
|---|---|---|
| `pic_steg_avant_kw` | max_h steg_import (sans orchestration) | kW |
| `pic_steg_apres_kw` | max_h steg_import (mode évalué) | kW |
| `reduction_pic_pct` | (avant − après) / avant × 100 | % |
| `energie_deplacee_kwh` | Σ_h contribution_DER | kWh |
| `energie_steg_avant/apres_kwh` | Σ_h steg_import | kWh |
| `consommation_kwh` | Σ_h (charge_totale − recharge batteries − VE reportés − HVAC réduit − non desservi) | kWh |
| `taux_autonomie_pct` | (1 − energie_steg / consommation) × 100 | % |
| `facture_steg_avant/apres_tnd` | Σ_h steg_import × tarif(h) | TND |
| `economie_tnd` | facture avant − facture après | TND |
| `co2_evite_kg` | (energie_steg avant − après) × 0,45 | kg CO2 |
| `energie_non_desservie_kwh` | Σ_h energie_non_desservie | kWh |
| `depassement_steg_kwh` | Σ_h max(steg_import − capacité, 0) | kWh |

Tarifs illustratifs, à remplacer par la grille officielle STEG :

- creux (23h-6h) : 0,15 TND/kWh ;
- pointe (18h-21h) : 0,35 TND/kWh ;
- plein (autres heures) : 0,25 TND/kWh.

Le facteur CO2 de 0,45 kg/kWh est aussi illustratif et reste à sourcer. L'ancienne formule `(pic_avant − pic_après) [kW] × prix [€/kWh]`, dimensionnellement fausse, a été supprimée.

**Signe du CO2 et de l'autonomie** : l'orchestration achète la nuit l'énergie qu'elle restitue en pointe. Les pertes de rendement des batteries (10 %) augmentent l'énergie STEG totale. Le CO2 évité est donc négatif, et le taux d'autonomie un peu plus bas que sans orchestration. Le signe n'est jamais forcé. Seul le PV est une source locale ; l'orchestration agit sur le moment des achats (pic, facture), pas sur leur volume.

## 10. Résultats mesurés

Valeurs issues de `python run_pipeline.py --validation-lp` (exécution du 2026-10-11, période du 2026-08-28 au 2026-10-11).

### 10.1 Métriques ML (période de test, 576 heures, 3 scénarios météo)

| Modèle | Cible | MAE (kW) | RMSE (kW) | MAPE (%) | MAE 17h-22h (kW) | Précision déficit | Rappel déficit | Faux positifs | Faux négatifs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ML | charge | 3,316 | 6,194 | 3,36 | 9,155 | | | | |
| ML | pv | 0,260 | 0,495 | 3,15 | 0,092 | | | | |
| ML | demande nette | 3,379 | 6,240 | 4,13 | 9,188 | 0,795 | 0,921 | 15 | 5 |
| Baseline | charge | 6,776 | 9,291 | 8,23 | 10,198 | | | | |
| Baseline | pv | 0,572 | 1,103 | 7,16 | 0,187 | | | | |
| Baseline | demande nette | 6,834 | 9,457 | 11,67 | 10,217 | 0,750 | 0,952 | 20 | 3 |
| Persistance | charge | 7,093 | 11,798 | 7,88 | 14,735 | | | | |
| Persistance | pv | 0,688 | 1,333 | 9,23 | 0,221 | | | | |
| Persistance | demande nette | 7,199 | 11,783 | 10,45 | 14,758 | 0,797 | 0,810 | 13 | 12 |

Le ML divise par deux environ la MAE de la baseline sur la journée. En pointe, l'écart est faible (9,2 contre 10,2 kW) : c'est la partie la plus difficile à prévoir, à cause des arrivées de VE aléatoires. Pour la détection du déficit, le ML a moins de faux positifs que la baseline (15 contre 20) mais un peu plus de faux négatifs (5 contre 3). Variables les plus importantes : `charge_lag_24h` (0,943) pour la charge ; `irradiance_prevue_wm2` (0,729) et `pv_lag_24h` (0,259) pour le PV. Ces scores reflètent en partie la régularité du générateur synthétique.

### 10.2 KPI sur toute la période (45 jours)

| Scénario | Mode | Pic STEG (kW) | Réduction moy. du pic (%) | Énergie déplacée (kWh) | Énergie STEG (kWh) | Autonomie (%) | Facture (TND) | Économie (TND) | CO2 évité (kg) | Non desservi (kWh) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| normal | sans orchestration | 203,98 | 0,00 | 0,00 | 66 263,00 | 15,84 | 18 458,92 | 0,00 | 0,00 | 0,00 |
| normal | réactif | 150,00 | 16,62 | 2 820,07 | 66 483,30 | 15,56 | 18 116,90 | 342,02 | −99,13 | 0,00 |
| normal | prédictif | 150,00 | 16,68 | 5 513,73 | 66 382,16 | 15,69 | 18 103,27 | 355,66 | −53,62 | 0,00 |
| nuageux | sans orchestration | 199,57 | 0,00 | 0,00 | 71 052,96 | 7,31 | 19 600,34 | 0,00 | 0,00 | 0,00 |
| nuageux | réactif | 150,00 | 14,69 | 2 280,18 | 71 253,06 | 7,05 | 19 307,75 | 292,59 | −90,05 | 0,00 |
| nuageux | prédictif | 150,00 | 14,80 | 5 032,08 | 71 161,82 | 7,17 | 19 310,19 | 290,15 | −48,99 | 0,00 |
| canicule | sans orchestration | 229,96 | 0,00 | 0,00 | 78 749,81 | 14,32 | 21 782,65 | 0,00 | 0,00 | 0,00 |
| canicule | réactif | 150,00 | 25,45 | 8 222,70 | 78 781,03 | 14,05 | 20 859,96 | 922,69 | −14,05 | 0,65 |
| canicule | prédictif | 150,00 | 25,45 | 9 211,60 | 78 767,39 | 14,07 | 20 848,32 | 934,33 | −7,91 | 0,65 |
| coupure_steg | sans orchestration | 203,98 | 0,00 | 0,00 | 65 835,28 | 15,92 | 18 318,87 | 0,00 | 0,00 | 427,73 |
| coupure_steg | réactif | 150,00 | 16,62 | 2 973,69 | 66 150,74 | 15,62 | 17 995,04 | 323,82 | −141,96 | 295,10 |
| coupure_steg | prédictif | 150,00 | 16,68 | 5 641,39 | 66 062,31 | 15,74 | 17 986,33 | 332,54 | −102,16 | 287,12 |

### 10.3 Réactif contre prédictif (période de test, jours 37 à 44)

| Scénario | Mode | Pic STEG (kW) | Énergie déplacée (kWh) | Facture (TND) | Économie (TND) | CO2 évité (kg) | Non desservi (kWh) |
|---|---|---:|---:|---:|---:|---:|---:|
| normal | réactif | 150,00 | 434,09 | 3 193,80 | 56,10 | −14,55 | 0,00 |
| normal | prédictif | 150,00 | 979,34 | 3 179,90 | 69,99 | −5,43 | 0,00 |
| nuageux | réactif | 150,00 | 358,52 | 3 426,18 | 47,06 | −12,41 | 0,00 |
| nuageux | prédictif | 150,00 | 814,29 | 3 419,93 | 53,32 | −5,92 | 0,00 |
| canicule | réactif | 150,00 | 1 318,22 | 3 718,42 | 164,89 | −3,11 | 0,00 |
| canicule | prédictif | 150,00 | 1 564,26 | 3 720,48 | 162,83 | −8,74 | 0,00 |
| coupure_steg | réactif | 150,00 | 587,71 | 3 071,93 | 37,90 | −57,38 | 295,10 |
| coupure_steg | prédictif | 150,00 | 1 131,94 | 3 059,37 | 50,47 | −53,12 | 287,12 |

Lecture honnête :

- **Les deux modes tiennent la capacité de 150 kW.** La seule énergie non desservie hors coupure est de 0,65 kWh, sur une heure de canicule (jour 34, 19h), quand toutes les flexibilités sont épuisées.
- **Le prédictif agit surtout sur l'usure des batteries.** En reportant plus tôt la recharge des VE (4 493 kWh d'anticipation sur 45 jours en scénario normal), il réduit la décharge des batteries : 792 kWh contre 1 703 kWh en réactif. Le `stress_score` final par batterie tombe d'environ 243 à 113 kWh (normal), 217 à 100 kWh (nuageux) et 358 à 302 kWh (canicule). Il limite aussi les pertes de rendement, d'où un CO2 moins négatif.
- **Le gain de facture est faible et pas systématique** : +13,9 TND en normal sur la période de test, mais −2,1 TND en canicule. L'énergie déplacée est plus élevée en prédictif, car les reports anticipés de VE comptent dans la contribution des DER même quand le pic prévu ne se réalise pas (faux positifs).

### 10.4 Coupure STEG (20h-23h, jour 42)

- **Sans orchestration** : 427,73 kWh non desservis sur la période (toute la demande des trois heures de coupure).
- **Réactif** : 295,10 kWh. Au début de la coupure, les batteries ne disposent que d'environ 38,5 kWh utilisables (7 batteries à 65 % de SoC), car elles ont déjà écrêté la pointe de 19h. Elles délivrent 35 kW à 20h puis s'épuisent. Le reste vient du délestage HVAC et VE.
- **Prédictif** : 287,12 kWh.
- **Durée d'autonomie complète du quartier** : 0 h. Les DER ne remplacent pas STEG pendant une pointe du soir.

### 10.5 Validation LP

Scénario normal, mode réactif : 123 heures de déficit comparées. Avec des coûts de 1 (batterie), 2 (VE) et 3 (HVAC) par kW, le coût total est de 3 937,45 avec les règles contre 3 122,23 avec le LP (+26 %). Les règles coûtent plus cher sur 78 heures. L'écart vient du plafond d'équité à 50 %, qui fait appel aux VE alors que des batteries ont encore de la puissance. C'est le prix de la répartition de l'usure, que le LP ignore. Le LP reste un module de **validation d'optimalité, hors boucle principale**.

## 11. Tableau de bord

`streamlit run app.py`. Barre latérale : scénario, jour (les jours de test ML sont signalés), mode, curseur de **capacité STEG**. À une autre valeur que 150 kW, la simulation est recalculée en mémoire sur toute la période, sans rien écrire en base.

- **Cartes KPI** : pic STEG avant et après, réduction du pic, énergie déplacée, taux d'autonomie, économie (TND), CO2 évité, énergie non desservie.
- **Bilan énergétique** : barres empilées horaires (STEG, PV utilisé, décharge des batteries, VE reportés, HVAC réduit, non desservi), courbe de la charge totale, ligne de capacité STEG, SoC des batteries, tableau horaire.
- **Prévision ML** : prévu contre réel (ML, baseline, persistance) sur un jour de test, tableau des métriques, histogramme des erreurs, importances, avertissement sur les données synthétiques.
- **Réactif vs Prédictif** : pic maximal et économie par scénario sur la période de test, tableau complet.
- **Actions de l'orchestrateur** : journal filtrable par déclencheur, avec justifications.
- **Parc de ressources** : batteries (SoC, stress), sessions VE, PV, HVAC.

## 12. Tests

`python -m pytest -q` donne **28 passed**. Les tests du pipeline s'exécutent sur une base et un dossier de modèles temporaires (20 jours), sans toucher `ider.db`.

| Fichier | Vérifications |
|---|---|
| `test_orchestrator.py` | Les 6 tests d'origine (adaptés aux SoC en fraction et au nouveau modèle VE) + plafond d'équité levé en coupure. |
| `test_dataset.py` | Reproductibilité, variabilité journalière, dates dynamiques, courbe hors pointe < capacité, PV nuageux réduit, coupure qui ne change que `steg_available`. |
| `test_bilan.py` | Identité du bilan (3 modes), capacité STEG, bornes de SoC, `stress_score` monotone et continuité du SoC, filet de sécurité du prédictif (prévision forcée à 0), coupure, recharge VE non pilotée identique au dataset. |
| `test_kpi.py` | Pic = max des sommes horaires (cas jouet calculé à la main), économie = 10 kWh × (0,35 − 0,15) TND, KPI sans doublon et cohérents avec le bilan. |
| `test_ml.py` | Absence de fuite, split chronologique, modèles sauvegardés et rechargeables, métriques sur le même ensemble de test, `predict_next_hour` cohérent avec le calcul par lot. |
| `test_lp.py` | Le LP ne coûte jamais plus que les règles, et l'écart provient du plafond d'équité. |

## 13. Limites

- Données synthétiques : le ML apprend en partie le générateur, et ses performances ne sont pas transférables à de vraies données.
- Tarifs STEG et facteur CO2 illustratifs, à remplacer par des valeurs officielles et sourcées.
- Proof-of-concept sans matériel réel : pas de contraintes de tension ou de fréquence, pas de pertes réseau ; quartier supposé capable de fonctionner en îlot pendant une coupure.
- HVAC : réduction sans effet rebond ni modèle thermique.
- VE : recharge à pas horaire, une session par jour et par véhicule.
- `stress_score` : cumul d'énergie déchargée, pas un modèle de dégradation électrochimique.
- La prévision ne connaît pas les coupures STEG. Le mode prédictif ne prépare donc pas les batteries à une coupure.
- Les batteries non pilotées (référence) restent à 50 % de SoC : la différence d'énergie stockée en fin de période n'est pas corrigée dans les KPI (au plus 7 × 10 kWh × 0,5, négligeable sur 45 jours).
- Les jours de week-end suivent la date réelle d'exécution : les chiffres de la section 10 peuvent varier légèrement selon le jour où le pipeline est lancé.

## 14. Équipe

À compléter par l'équipe :

- Responsable backend / simulation :
- Responsable tableau de bord Streamlit :
- Responsable validation / tests :
- Responsable documentation et revue :
