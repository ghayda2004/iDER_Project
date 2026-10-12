# iDER — Documentation détaillée

> **Comment lire ce document.** Tous les chiffres viennent de la base `ider.db` produite par `python run_pipeline.py` le 11/10/2026 (période simulée : du 28/08/2026 au 11/10/2026). Le fil conducteur est une seule journée : le **vendredi 9 octobre 2026 (jour 42)**. C'est un jour de la période de test du ML et le jour de la coupure du scénario `coupure_steg`. Les dates suivent la date d'exécution : si le pipeline est relancé un autre jour, les dates changent, et les jours de week-end aussi. Les tirages aléatoires, eux, restent identiques (graine 42) ; les chiffres peuvent donc bouger un peu.
>
> Ce document remplace `docs/EXPLICATION_PROJET.md`, qui décrit l'ancienne version du projet (calibration uniforme, colonne `grid_import_kw`, 7 jours).

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [D'où viennent les valeurs (paramètres et références)](#2-doù-viennent-les-valeurs-paramètres-et-références)
3. [Génération du jeu de données](#3-génération-du-jeu-de-données)
4. [Les scénarios](#4-les-scénarios)
5. [La base de données, table par table](#5-la-base-de-données-table-par-table)
6. [La référence « sans orchestration »](#6-la-référence--sans-orchestration-)
7. [Modèles des ressources (batterie, VE, HVAC)](#7-modèles-des-ressources-batterie-ve-hvac)
8. [Comment le pic est couvert (mode réactif)](#8-comment-le-pic-est-couvert-mode-réactif)
9. [Le mode prédictif](#9-le-mode-prédictif)
10. [Le modèle de Machine Learning](#10-le-modèle-de-machine-learning)
11. [Les KPI, avec un calcul complet](#11-les-kpi-avec-un-calcul-complet)
12. [Le scénario de coupure STEG](#12-le-scénario-de-coupure-steg)
13. [La validation par optimisation linéaire (LP)](#13-la-validation-par-optimisation-linéaire-lp)
14. [Résultats globaux](#14-résultats-globaux)
15. [Où retrouver chaque élément dans le tableau de bord](#15-où-retrouver-chaque-élément-dans-le-tableau-de-bord)
16. [Tests automatiques](#16-tests-automatiques)
17. [Limites](#17-limites)
18. [Questions probables et réponses](#18-questions-probables-et-réponses)
19. [Glossaire](#19-glossaire)

---

## 1. Vue d'ensemble

### 1.1 Le concept en une phrase

**STEG alimente le quartier jusqu'à 150 kW ; au-delà, les ressources locales (batteries, report de recharge des VE, réduction de la climatisation) couvrent le déficit, et une prévision ML permet d'agir une heure à l'avance.**

### 1.2 Le quartier

| Élément | Nombre | Maisons | Caractéristiques |
|---|---:|---|---|
| Maisons | 20 | H01 à H20 | charge de base + climatisation (HVAC) |
| Panneaux PV | 13 | H01 à H13 | 3 à 4 kWc par maison |
| Batteries | 7 | H01 à H07 | 10 kWh, 5 kW en charge et en décharge |
| Véhicules électriques | 8 | H01 à H08 | batterie de 60 kWh, recharge à 7 kW |
| Climatisations | 20 | H01 à H20 | réductibles de 30 % au plus |

Par exemple, H01 a tout (PV, batterie, VE), H09 n'a que du PV et H15 n'a ni PV, ni batterie, ni VE.

### 1.3 La chaîne de traitement

```text
python run_pipeline.py
 │
 ├─ 1. generate_dataset.py   crée 86 400 mesures horaires (4 scénarios × 45 jours × 24 h × 20 maisons)
 │                           et 360 sessions de recharge VE (8 VE × 45 jours)
 ├─ 2. forecasting_ml.py     entraîne 2 forêts aléatoires (charge, PV), les compare à 2 méthodes simples,
 │                           écrit 28 512 prévisions et 27 lignes de métriques
 ├─ 3. simulation.py         rejoue chaque scénario heure par heure dans 3 modes :
 │                           sans orchestration, réactif, prédictif
 └─ 4. kpi.py                calcule 540 lignes de KPI (4 scénarios × 3 modes × 45 jours)

streamlit run app.py         lit la base et affiche tout ; le curseur de capacité relance la simulation en mémoire
```

Durée mesurée du pipeline : environ 26 secondes.

---

## 2. D'où viennent les valeurs (paramètres et références)

**Point essentiel : aucune valeur ne provient d'un jeu de données réel ou d'une publication STEG.** Tous les paramètres sont des **hypothèses de conception** regroupées dans [backend/config.py](../backend/config.py). Ils ont été choisis pour deux raisons :

- avoir des ordres de grandeur plausibles pour un équipement résidentiel ;
- obtenir la forme de courbe demandée : moins de 140 kW hors 17h-22h, environ 175-185 kW en pointe dans le scénario normal, plus de 200 kW en canicule.

| Paramètre | Valeur | Rôle | Origine |
|---|---|---|---|
| `STEG_CAPACITY_KW` | 150 kW | capacité maximale fournie par STEG | reprise de l'ancienne « limite réseau » du projet |
| `N_DAYS` | 45 | jours simulés | assez de jours pour entraîner et tester un modèle ML |
| `SEED` | 42 | graine aléatoire | rend les résultats reproductibles |
| `PROFIL_BASE_KW` | 1,1 à 6,4 kW/maison selon l'heure | consommation hors climatisation et VE | dessiné pour obtenir une pointe le soir (18h-21h) |
| `BATTERY_CAPACITY_KWH` / `BATTERY_MAX_POWER_KW` | 10 kWh / 5 kW | batterie domestique | ordre de grandeur courant pour une batterie résidentielle |
| `ROUND_TRIP_EFFICIENCY` | 0,90 | pertes de stockage | hypothèse courante |
| `SOC_MIN` / `SOC_CIBLE` / `SOC_MAX` / `SOC_INIT` | 0,10 / 0,90 / 1,0 / 0,50 | bornes et cible de charge | protection de la batterie et cible de recharge de nuit |
| `EV_BATTERY_CAPACITY_KWH` / `EV_MAX_CHARGE_KW` | 60 kWh / 7 kW | VE et borne domestique | 7 kW ≈ borne monophasée 32 A |
| `EV_ARRIVEE_MOYENNE_H` / `EV_DEPART_MOYEN_H` | 18,3 h / 7 h | habitudes de trajet | hypothèse « retour du travail » |
| `HVAC_REDUCTION_MAX` | 30 % | confort | hypothèse : réduction tolérable sans gêne majeure |
| `HVAC_KW_PAR_DEGRE` / `HVAC_SEUIL_C` | 0,11 kW/°C / 21 °C | sensibilité de la climatisation à la chaleur | choisie pour que la canicule ajoute environ 20 kW en pointe |
| `PV_PUISSANCE_CRETE_KWC` | 3 à 4 kWc | taille des installations PV | ordre de grandeur résidentiel |
| `TEMPERATURE_MOYENNE_C` / amplitude | 24 °C ± 6 °C | climat de fin d'été | hypothèse |
| Tarifs creux / plein / pointe | 0,15 / 0,25 / 0,35 TND/kWh | facture | **ILLUSTRATIFS**, à remplacer par la grille officielle STEG |
| `HEURES_CREUSES` / `HEURES_POINTE` | 23h-6h / 18h-21h | périodes tarifaires | **illustratives** |
| `FACTEUR_CO2_KG_KWH` | 0,45 kg/kWh | émissions du réseau | **ILLUSTRATIF**, à sourcer avant la soutenance |
| `FORECAST_SAFETY_MARGIN` | 5 % | marge sur la prévision | choix de conception |
| `WEATHER_FORECAST_NOISE_*` | 1 °C et 50 W/m² | erreur simulée de la prévision météo | choix de conception |

**Et « la référence » ?** Le mot a deux sens dans le projet :

1. **La référence de comparaison des KPI** est le mode `sans_orchestration`, calculé à partir des mêmes données que les autres modes (section 6). Ce n'est pas une donnée externe.
2. **Les valeurs de référence des paramètres** sont celles du tableau ci-dessus, toutes définies dans `config.py`.

---

## 3. Génération du jeu de données

Fichier : [backend/generate_dataset.py](../backend/generate_dataset.py).

### 3.1 Un seul générateur aléatoire

`rng = np.random.default_rng(42)` est créé **une seule fois**, au début de `construire_dataset()`. Tous les tirages sont faits dans un ordre fixe : maisons, variabilité journalière et horaire, météo, VE. Les tirages de charge, de bruit et de VE sont **communs aux scénarios** : le scénario normal et le scénario canicule ont exactement les mêmes habitants et les mêmes voitures, seule la météo change. Le test `test_dataset_reproductible` vérifie que deux générations avec la même graine sont identiques.

### 3.2 Les dates

`dates_simulation()` produit 45 dates qui se terminent **aujourd'hui** : ici du 28/08/2026 (jour 0) au 11/10/2026 (jour 44). `day_of_week` vaut 0 le lundi et 6 le dimanche. `is_weekend` vaut 1 le samedi et le dimanche. Le jour 42 est un vendredi (`day_of_week = 4`, `is_weekend = 0`).

### 3.3 Formules, maison par maison et heure par heure

**Charge de base :**

```text
base = PROFIL_BASE_KW[heure] × facteur_weekend × facteur_maison × facteur_jour × bruit
```

| Terme | Valeur |
|---|---|
| `PROFIL_BASE_KW` | 0h-5h : 1,1-1,3 kW ; 7h : 3,2 kW ; journée : 2,2-2,6 kW ; 17h : 4,2 kW ; **18h : 5,6 ; 19h : 6,4 ; 20h : 6,4 ; 21h : 5,6 kW** ; 22h : 4,2 ; 23h : 2,6 kW |
| `facteur_weekend` | 1,30 de 9h à 16h et 0,85 de 6h à 8h le week-end ; 1 sinon |
| `facteur_maison` | tiré une fois par maison entre 0,85 et 1,15 |
| `facteur_jour` | tiré par maison et par jour, loi normale N(1 ; 0,04) |
| `bruit` | tiré par maison et par heure, N(1 ; 0,05), borné entre 0,85 et 1,15 |

**Climatisation (HVAC) :**

```text
hvac = occupation[heure] × facteur_hvac_maison × (0,25 + 0,11 × max(T − 21, 0)) × bruit
```

L'occupation vaut 0,3 la nuit, 0,6 de 6h à 8h, 0,4 en journée (0,8 le week-end), 1,0 de 17h à 22h et 0,5 à 23h. Le facteur de maison est tiré entre 0,8 et 1,2.

**Température :**

```text
T = 24 + 6 × sin(2π (heure − 9) / 24) + écart_jour + bruit + écart_scénario
```

La sinusoïde est maximale vers 15h. L'écart du jour suit N(0 ; 1,2) et le bruit horaire N(0 ; 0,5).

**Irradiance :**

```text
irradiance = 950 × sin(π (heure + 0,5 − 6) / 13,5) × facteur_nuages_du_jour
```

Elle est nulle avant 6h et après 19h30.

**PV :**

```text
pv = kWc × irradiance / 1000 × 0,85 × (1 − 0,004 × max(T − 25, 0)) × bruit
```

0,85 est le ratio de performance de l'installation. Le terme suivant est la perte due à la chaleur. Le bruit suit N(1 ; 0,04), borné entre 0,9 et 1,1.

**VE (recharge non pilotée) :** chaque soir, chaque VE arrive vers 18h (entre 17h et 21h) avec un SoC entre 0,55 et 0,80 (0,70 à 0,85 le week-end). Il repart le lendemain vers 7h (entre 6h et 8h). Sans pilotage, il recharge à 7 kW dès son arrivée jusqu'à 90 %.

**Total par maison :** `charge_totale = base + hvac + recharge VE`.

### 3.4 Exemple réel : 3 maisons le vendredi 9 octobre (scénario normal)

| Colonne | H01 13h | H09 13h | H15 13h | **H01 19h** | H09 19h | H15 19h |
|---|---:|---:|---:|---:|---:|---:|
| `temperature_c` | 29,1 | 29,1 | 29,1 | 27,1 | 27,1 | 27,1 |
| `irradiance_wm2` | 761,6 | 761,6 | 761,6 | 0,0 | 0,0 | 0,0 |
| `base_load_kw` | 3,1015 | 2,3587 | 2,6390 | **7,6193** | 5,5647 | 6,4917 |
| `hvac_kw` | 0,5120 | 0,3613 | 0,4473 | **1,0435** | 0,7891 | 0,8722 |
| `ev_charge_kw` | 0 | 0 | 0 | **4,4842** | 0 | 0 |
| `ev_connected` / `ev_soc` | 0 / — | — | — | **1 / 0,90** | — | — |
| `pv_kw` | 1,9726 | 2,4524 | 0 (pas de PV) | 0 | 0 | 0 |
| `charge_totale_kw` | 3,6135 | 2,7200 | 3,0863 | **13,1470** | 6,3538 | 7,3639 |

Les valeurs de H01 à 19h se reconstruisent ainsi :

- **Base** : profil 6,4 kW × facteur combiné (maison × jour × bruit) de 1,1905 = 7,6193 kW.
- **HVAC** : 0,25 + 0,11 × (27,1 − 21) = 0,921 kW. Multiplié par une occupation de 1,0 et un facteur combiné (maison × bruit) de 1,133, cela donne 1,0435 kW.
- **PV à 13h** : 1,9726 / (0,7616 × 0,85 × (1 − 0,004 × 4,1)) donne une puissance crête effective (bruit compris) d'environ 3,10 kWc pour H01. Le même calcul donne environ 3,85 kWc pour H09.
- **Charge totale** : 7,6193 + 1,0435 + 4,4842 = 13,1470 kW.

### 3.5 Exemple réel : la session VE de H01

| `jour` | date d'arrivée | `arrivee_h` | `depart_h` (lendemain) | `soc_arrivee` | `energie_kwh` |
|---:|---|---:|---:|---:|---:|
| 41 | 08/10 | 19 | 7 | 0,6779 | 13,3248 |
| 42 | 09/10 | 18 | 8 | 0,7086 | 11,4842 |

Énergie à livrer le jour 42 : (0,90 − 0,7086) × 60 kWh = 11,48 kWh. Sans pilotage, la voiture recharge 7 kW à 18h (SoC 0,8253) puis 4,48 kW à 19h (SoC 0,90). Elle reste ensuite branchée sans consommer jusqu'à son départ le samedi à 8h.

### 3.6 De la maison au quartier : la somme

Toutes les grandeurs du quartier sont des **sommes sur les 20 maisons** (`kpi.agreger_quartier`), jamais le maximum d'une ligne maison-heure. Le vendredi 9 octobre, scénario normal :

| Heure | T (°C) | Irradiance (W/m²) | Base (kW) | HVAC (kW) | VE (kW) | PV (kW) | Charge totale (kW) | **Demande nette (kW)** |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 19,5 | 0 | 26,80 | 1,48 | 0 | 0 | 28,28 | 28,28 |
| 3 | 17,7 | 0 | 22,50 | 1,49 | 0 | 0 | 23,99 | 23,99 |
| 7 | 21,2 | 264,5 | 65,41 | 3,18 | 0 | 10,20 | 68,59 | 58,38 |
| 10 | 25,0 | 669,8 | 46,34 | 5,53 | 0 | 25,81 | 51,88 | 26,06 |
| 13 | 29,1 | 761,6 | 53,64 | 9,09 | 0 | 29,09 | 62,73 | 33,64 |
| 16 | 30,4 | 497,1 | 52,84 | 10,16 | 0 | 18,72 | 63,00 | 44,28 |
| 17 | 29,5 | 347,1 | 85,99 | 23,25 | 7,00 | 13,04 | 116,24 | 103,20 |
| 18 | 28,0 | 178,3 | 116,21 | 20,37 | 14,00 | 6,79 | 150,58 | 143,79 |
| **19** | 27,1 | 0 | 136,29 | 17,99 | 44,65 | 0 | 198,92 | **198,92** |
| 20 | 25,6 | 0 | 129,93 | 14,95 | 30,07 | 0 | 174,96 | 174,96 |
| 21 | 24,8 | 0 | 117,35 | 13,30 | 25,63 | 0 | 156,28 | 156,28 |
| 22 | 23,1 | 0 | 86,32 | 9,59 | 0,57 | 0 | 96,48 | 96,48 |
| 23 | 21,6 | 0 | 53,82 | 3,10 | 0 | 0 | 56,92 | 56,92 |

`demande_nette = max(charge_totale − PV, 0)`. À 19h, elle dépasse la capacité de 48,92 kW : c'est le **déficit** à couvrir.

---

## 4. Les scénarios

### 4.1 Définitions

| Scénario | Ce qui change par rapport à `normal` |
|---|---|
| `normal` | rien (référence météo) |
| `nuageux` | facteur nuageux entre 0,30 et 0,50 (≈ 0,4) au lieu de 0,75 à 1,0 ; température −2 °C (les nuages rafraîchissent) |
| `canicule` | température +8 à +12 °C selon le jour ; ciel clair (facteur 0,95 à 1,0) |
| `coupure_steg` | **copie exacte** de `normal`, sauf `steg_available = 0` le jour 42 de 20h à 22h inclus (3 heures sans STEG) |

### 4.2 Météo et énergie par scénario (moyennes sur 45 jours)

| Scénario | T moy. à 15h (°C) | T moy. à 19h (°C) | T min / max (°C) | Irradiance moy. à 12h (W/m²) | PV (kWh/jour) | HVAC (kWh/jour) | Base (kWh/jour) | VE (kWh/jour) | Charge totale (kWh/jour) |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
| normal | 30,24 | 27,16 | 15,1 / 32,7 | 845,4 | 277,1 | 209,4 | 1 447,0 | 93,1 | 1 749,6 |
| nuageux | 28,24 | 25,16 | 13,1 / 30,7 | 377,7 | 124,5 | 163,3 | 1 447,0 | 93,1 | 1 703,5 |
| canicule | 39,95 | 36,88 | 23,4 / 43,0 | 927,0 | 292,5 | 502,3 | 1 447,0 | 93,1 | 2 042,5 |

La base et les VE sont identiques dans les trois scénarios, puisque les tirages sont communs : seules la climatisation et le PV changent. La canicule fait plus que doubler l'énergie de climatisation (502 contre 209 kWh/jour). Le PV de canicule est un peu plus élevé grâce au ciel clair, malgré la perte due à la chaleur.

### 4.3 Profil moyen de la demande nette (kW, sans orchestration)

| Heure | normal | nuageux | canicule |
|---:|---:|---:|---:|
| 0 | 28,2 | 28,1 | 33,8 |
| 3 | 23,9 | 23,9 | 28,5 |
| 7 | 54,8 | 60,3 | 66,3 |
| 10 | 28,7 | 42,0 | 38,3 |
| 13 | 38,7 | 53,8 | 48,2 |
| 16 | 50,5 | 59,5 | 60,5 |
| 17 | 104,7 | 108,2 | 125,3 |
| 18 | 154,4 | 154,0 | 175,3 |
| **19** | **180,1** | **175,7** | **201,4** |
| 20 | 163,3 | 158,9 | 184,6 |
| 21 | 133,4 | 129,3 | 154,6 |
| 22 | 95,8 | 92,8 | 117,0 |
| 23 | 56,4 | 55,8 | 66,6 |

Lecture :

- Le pic tombe toujours à **19h**. Le retour à la maison, la cuisine, la climatisation et l'arrivée des VE s'y cumulent, et le soleil est couché.
- En journée, `nuageux` demande **plus** que `normal` (+13 à +15 kW à 10h-13h), faute de PV.
- À 19h, `nuageux` demande **moins** que `normal` : il n'y a plus de PV, et il fait 2 °C de moins, donc moins de climatisation.

### 4.4 Pics journaliers et déficits (sans orchestration)

| Scénario | Pic moyen (kW) | Écart-type (kW) | Pic min / max (kW) | Heures en déficit (sur 1 080) | Énergie de déficit (kWh) | Déficit moyen par jour (kWh) | Déficit horaire max (kW) | Jours sans déficit |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| normal | 180,75 | 12,76 | 147,95 / 203,98 | 110 | 2 321,57 | 51,59 | 53,98 | 1 |
| nuageux | 176,64 | 12,37 | 148,29 / 199,57 | 101 | 1 956,55 | 43,48 | 49,57 | 1 |
| canicule | 202,09 | 13,30 | 170,77 / 229,96 | 162 | 5 292,22 | 117,60 | 79,96 | 0 |

Répartition des heures de déficit (normal / nuageux / canicule) :

- 18h : 27 / 26 / 44 ;
- 19h : 44 / 43 / 45 ;
- 20h : 37 / 31 / 45 ;
- 21h : 2 / 1 / 28.

En dehors de ces heures, il n'y a **jamais** de déficit. Le maximum hors 17h-22h est de 71,9 kW en normal, 80,3 en nuageux et 88,4 en canicule.

**Effet du week-end** : pic moyen de 186,7 kW en semaine contre 167,6 kW le week-end (scénario normal). Le week-end, la consommation se déplace vers la journée, quand le PV produit.

---

## 5. La base de données, table par table

Fichier : [backend/database.py](../backend/database.py). Base SQLite locale `ider.db`, régénérée par le pipeline (aucune migration). Unités : kW pour une puissance, kWh pour une énergie, SoC en fraction de 0 à 1, TND, kg CO2.

### 5.1 `measurements` — 86 400 lignes

Une ligne par (scénario, jour, heure, maison) : 4 × 45 × 24 × 20.

| Colonne | Type | Sens |
|---|---|---|
| `id` | INTEGER | clé technique |
| `scenario` | TEXT | normal, nuageux, canicule, coupure_steg |
| `date`, `jour` | TEXT, INTEGER | date ISO et index 0 à 44 |
| `heure` | INTEGER | 0 à 23 |
| `house_id` | TEXT | H01 à H20 |
| `day_of_week`, `is_weekend` | INTEGER | 0 = lundi ; 1 si samedi ou dimanche |
| `temperature_c`, `irradiance_wm2` | REAL | météo de l'heure, commune aux 20 maisons |
| `steg_available` | INTEGER | 1 si STEG fonctionne, 0 pendant la coupure |
| `base_load_kw`, `hvac_kw`, `ev_charge_kw` | REAL | composantes de la consommation (VE sans pilotage) |
| `ev_connected`, `ev_soc` | INTEGER, REAL | VE branché ; SoC du VE (vide si pas de VE ou VE absent) |
| `pv_kw` | REAL | production PV |
| `charge_totale_kw` | REAL | base + HVAC + VE |

Exemple : voir la ligne de H01 à 19h dans la section 3.4 (`id = 20549`).

### 5.2 `ev_sessions` — 360 lignes

8 VE × 45 jours. Colonnes : `house_id`, `jour` et `date` de l'arrivée, `arrivee_h`, `depart_h` (le lendemain), `soc_arrivee`, `energie_kwh` (énergie à livrer pour atteindre 90 %). Exemple : voir la section 3.5. La simulation lit cette table pour créer les VE pilotables.

### 5.3 `bilan_horaire` — 12 960 lignes

4 scénarios × 3 modes × 1 080 heures. C'est **la table centrale des résultats** : le bilan énergétique du quartier, heure par heure.

| Colonne | Sens |
|---|---|
| `charge_totale_kw` | base + HVAC + demande VE (avant report) + recharge des batteries |
| `pv_kw`, `pv_utilise_kw` | production et part consommée sur place |
| `demande_nette_kw` | charge totale − PV utilisé |
| `steg_disponible_kw` | 150, ou 0 pendant la coupure |
| `deficit_kw` | max(demande nette − STEG disponible, 0), **avant** toute action |
| `steg_import_kw` | puissance réellement fournie par STEG |
| `decharge_batteries_kw`, `ve_reporte_kw`, `hvac_reduit_kw` | contribution de chaque type de DER |
| `recharge_batteries_kw` | puissance absorbée par les batteries |
| `contribution_der_kw` | somme des trois contributions |
| `energie_non_desservie_kw` | demande non servie (délestage) |
| `depassement_steg_kw` | excès au-delà de 150 kW (mode sans orchestration uniquement) |
| `ve_non_livre_kwh` | énergie VE manquante au départ (0 partout) |
| `prevision_demande_nette_kw` | prévision ML utilisée (mode prédictif uniquement) |
| `tarif_tnd_kwh` | tarif de l'heure |

Exemple réel (normal, réactif, jour 42, 19h) :

| `charge_totale` | `demande_nette` | `deficit` | `steg_import` | `decharge_batteries` | `ve_reporte` | `hvac_reduit` | `energie_non_desservie` |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 198,92 | 198,92 | 48,92 | **150,00** | 17,50 | 31,42 | 0 | 0 |

Vérification : 150,00 + (17,50 + 31,42) + 0 (PV utilisé) + 0 = 198,92. ✓

### 5.4 `etat_batteries` — 90 720 lignes

4 scénarios × 3 modes × 1 080 heures × 7 batteries. Colonnes :

- `soc_debut` et `soc` : SoC en début et en fin d'heure ;
- `puissance_kw` : positive en charge, négative en décharge ;
- `stress_score` : énergie déchargée cumulée depuis le jour 0, en kWh.

Exemple : la journée de BAT-H01, section 8.5.

### 5.5 `orchestrator_actions` — 14 793 lignes

Une ligne par décision.

| Colonne | Valeurs |
|---|---|
| `mode` | `reactif` ou `predictif` (la référence ne décide rien) |
| `device_id` | BAT-H01…H07, VE-H01…H08, CLIM-H01…H20 |
| `action_type` | `DISCHARGE` (batterie), `DELAY` (report VE), `REDUCE` (HVAC), `CHARGE` (recharge batterie), `PRECHARGE` (préchargement prédictif) |
| `declencheur` | `deficit` (couverture d'un déficit observé), `anticipation` (prévision ML), `recharge` (heures creuses) |
| `power_kw` | puissance non arrondie |
| `justification` | texte lisible |

Exemple : `reactif, 19h, BAT-H01, DISCHARGE, deficit, 2.5, « Batterie BAT-H01 choisie (score équité 235,3 kWh cumulés, SoC 65 %) : -2,50 kW »`.

### 5.6 `kpi_results` — 540 lignes

Une ligne par (scénario, mode, jour). Formules en section 11. Exemple complet en section 11.2.

### 5.7 `forecasts` — 28 512 lignes

Prévisions des 3 modèles pour 3 cibles (`charge`, `pv`, `demande_nette`), pour chaque heure prévisible des 3 scénarios météo. Calcul : 3 scénarios × 1 056 heures × 3 cibles × 3 modèles = 28 512 (les 24 premières heures n'ont pas d'historique de 24 h). Colonnes : `y_pred`, `y_true`, `modele` (`ml`, `baseline`, `persistance`), `split` (`train`, `val`, `test`).

### 5.8 `model_metrics` — 27 lignes et `feature_importances` — 22 lignes

- `model_metrics` : 3 modèles × 3 cibles × 3 splits. Colonnes : MAE, RMSE, MAPE, MAE en pointe, et pour la demande nette la précision, le rappel, les vrais positifs, les faux positifs et les faux négatifs de la détection du déficit.
- `feature_importances` : 11 variables × 2 modèles.

---

## 6. La référence « sans orchestration »

C'est l'état « avant », qui sert de point de comparaison à tous les KPI :

- les batteries ne font rien : SoC bloqué à 0,50 et `stress_score` à 0 ;
- les VE rechargent dès leur arrivée, à 7 kW ;
- la climatisation n'est jamais réduite ;
- le PV est consommé sur place ;
- **STEG fournit toute la demande nette, même au-delà de 150 kW.** L'excès est enregistré comme `depassement_steg_kw` : c'est la surcharge que l'orchestration doit supprimer.

Le vendredi 9 octobre (normal), STEG fournirait 198,92 kW à 19h, 174,96 à 20h et 156,28 à 21h. Le dépassement vaut 48,92 + 24,96 + 6,28 = **80,16 kWh** sur la journée.

Pendant une coupure, STEG fournit 0 kW et rien ne compense : toute la demande devient de l'énergie non desservie.

La simulation de cette référence **reproduit exactement** la recharge VE du jeu de données (test `test_recharge_ve_non_pilotee_identique_au_dataset`).

---

## 7. Modèles des ressources (batterie, VE, HVAC)

Fichier : [backend/models.py](../backend/models.py).

### 7.1 Batterie

- **Puissance de décharge possible** sur l'heure : `min(5 kW, (SoC − 0,10) × 10 kWh)`.
- **Décharge de P kW pendant 1 h** : `SoC −= P / 10`, et `stress_score += P` (en kWh).
- **Charge de P kW pendant 1 h** : `SoC += P × 0,90 / 10`, car le rendement s'applique à la charge.
- Une batterie ne charge et ne décharge jamais pendant la même heure.

Exemple : une batterie à SoC 0,90 qui décharge 2,5 kW passe à 0,65. Rechargée à 5 kW pendant 1 h depuis 0,15, elle stocke 4,5 kWh et passe à 0,60. On retrouve exactement ces valeurs dans la section 8.5.

### 7.2 Véhicule électrique

- **Demande de l'heure** : `min(7 kW, énergie restante)`. C'est ce que la voiture consommerait sans pilotage.
- **Report possible** (`flexibilite_disponible`) : on ne reporte jamais plus que ce qui permet de finir la recharge avant le départ. Avec E l'énergie restante, d la demande de l'heure, H le nombre d'heures avant le départ et P = 7 kW, reporter x kW laisse E − (d − x) kWh pour les H − 1 heures suivantes. Il faut donc :

```text
x ≤ P × (H − 1) − E + d
```

  Exemple (test `test_ev_proche_depart_non_retarde_excessivement`) : 10 kWh à livrer en 2 h. On peut reporter au plus 7 × 1 − 10 + 7 = **4 kW**. Avec 7 kWh à livrer en 1 h, on ne peut rien reporter.

- L'énergie reportée n'est pas perdue : elle est rechargée plus tard (voir l'effet rebond, section 8.4).
- Résultat : **0 kWh** de recharge VE manquante au départ, dans tous les scénarios et tous les modes.

### 7.3 Climatisation (HVAC)

- **Réduction possible** : 30 % de la demande de l'heure ; 100 % pendant une coupure STEG (délestage complet).
- C'est une réduction pure, sans effet rebond (simplification). Elle coûte du confort, pas de l'énergie différée.

---

## 8. Comment le pic est couvert (mode réactif)

Fichiers : [backend/simulation.py](../backend/simulation.py) et [backend/orchestrator.py](../backend/orchestrator.py).

### 8.1 L'algorithme, heure par heure

Pour chaque heure t de la chronologie continue (jour 0 à 0h, jusqu'au jour 44 à 23h) :

1. **VE** : les voitures dont l'heure de départ est atteinte se débranchent ; celles qui arrivent se branchent.
2. **Demandes de l'heure** : base (jeu de données), climatisation de chaque maison (jeu de données), demande de chaque VE (calculée par l'objet VE).
3. **Recharge des batteries**, dans les modes orchestrés :
   - d'abord avec le surplus PV, s'il y en a ;
   - puis, en heures creuses (23h-6h), avec STEG jusqu'à SoC 0,90, dans la limite de la marge sous 150 kW, les batteries les plus vides d'abord.
4. **Bilan** : `charge_totale = base + HVAC + VE + recharge`, `demande_nette = charge_totale − PV`, `déficit = max(demande_nette − 150, 0)`.
5. **Couverture du déficit** (`dispatch`), dans l'ordre de mérite :
   1. **batteries**, triées par `stress_score` croissant (la moins usée d'abord) ;
   2. **report de recharge des VE**, dans la limite calculée en 7.2 ;
   3. **réduction de la climatisation** (30 % au plus).
6. **Reste** : ce qui n'est pas couvert devient de l'énergie non desservie. STEG fournit `demande_nette − contribution DER − non desservi`, donc jamais plus de 150 kW.
7. **Fin d'heure** : les VE rechargent ce qui n'a pas été reporté, et l'état des batteries est enregistré.

Les objets batteries, VE et HVAC sont créés **une seule fois** par scénario et par mode. Le SoC et le `stress_score` passent donc d'un jour au suivant : la recharge de la nuit prépare la pointe du lendemain.

### 8.2 La règle d'équité à 50 % (et son effet réel)

Dans `dispatch()`, une batterie est plafonnée à 50 % de sa puissance (2,5 kW) si **une autre batterie a un `stress_score` plus élevé**. Le but est d'étaler l'usure.

**Effet réel, à connaître** : les scores sont mis à jour au fur et à mesure de la boucle. Quand vient le tour de la dernière batterie (la plus usée), les autres viennent de décharger et ont dépassé son score. Résultat : **toutes les batteries sont plafonnées à 2,5 kW**, soit 7 × 2,5 = **17,5 kW** au maximum par heure au lieu de 35 kW. On le voit à 19h, 20h et 21h le jour 42 (section 8.3). Ce comportement vient du code d'origine et a été conservé à la demande de l'énoncé. Il explique pourquoi les VE sont sollicités tôt, et pourquoi les règles coûtent plus cher que l'optimum LP (section 13).

La règle est **levée pendant une coupure STEG** : la continuité d'alimentation passe avant l'usure, et les batteries peuvent alors fournir 5 kW chacune.

Les scores restent très proches entre batteries, signe que l'équité fonctionne : sur 45 jours en scénario normal réactif, le `stress_score` final va de 242,2 à 244,1 kWh selon la batterie.

### 8.3 Exemple complet : vendredi 9 octobre, scénario normal

Bilan horaire (kW), de 17h à 23h, dans les trois modes :

| Heure | Mode | Charge totale | Demande nette | Déficit | **STEG** | Batteries | VE reportés | Recharge batt. |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 18 | sans orch. | 150,58 | 143,79 | 0 | 143,79 | 0 | 0 | 0 |
| 18 | réactif | 150,58 | 143,79 | 0 | 143,79 | 0 | 0 | 0 |
| 19 | sans orch. | 198,92 | 198,92 | 48,92 | **198,92** | 0 | 0 | 0 |
| 19 | réactif | 198,92 | 198,92 | 48,92 | **150,00** | 17,50 | 31,42 | 0 |
| 20 | sans orch. | 174,96 | 174,96 | 24,96 | **174,96** | 0 | 0 | 0 |
| 20 | réactif | 190,31 | 190,31 | 40,31 | **150,00** | 17,50 | 22,81 | 0 |
| 21 | sans orch. | 156,28 | 156,28 | 6,28 | **156,28** | 0 | 0 | 0 |
| 21 | réactif | 168,68 | 168,68 | 18,68 | **150,00** | 17,50 | 1,18 | 0 |
| 22 | sans orch. | 96,48 | 96,48 | 0 | 96,48 | 0 | 0 | 0 |
| 22 | réactif | 119,76 | 119,76 | 0 | 119,76 | 0 | 0 | 0 |
| 23 | sans orch. | 56,92 | 56,92 | 0 | 56,92 | 0 | 0 | 0 |
| 23 | réactif | 96,31 | 96,31 | 0 | 96,31 | 0 | 0 | **35,00** |

La climatisation n'a pas été sollicitée ce jour-là : les batteries et les VE suffisaient.

**Le détail de 19h en mode réactif** (journal `orchestrator_actions`) :

1. Déficit à couvrir : 198,92 − 150 = **48,92 kW**.
2. Batteries, de la moins usée à la plus usée : BAT-H06, H05, H04, H07, H02, H03, H01. Chacune fournit **2,50 kW** (plafond d'équité), soit 17,50 kW. Reste 31,42 kW.
3. VE : VE-H01 reporte 4,48 kW, VE-H03 7,00, VE-H04 7,00, VE-H05 5,24, VE-H06 7,00 et VE-H07 0,70 kW, soit 31,42 kW. Reste 0.
4. STEG fournit exactement **150,00 kW**.

### 8.4 L'effet rebond des VE

L'énergie reportée doit être rechargée plus tard. On le voit dans le tableau :

- à **20h**, la charge réactive vaut 190,31 kW contre 174,96 sans orchestration (+15,35 kW) : les VE reportés à 19h demandent de nouveau à recharger, et on doit encore les reporter (22,81 kW) ;
- à **22h**, après la pointe, ils rechargent : 119,76 contre 96,48 kW (+23,28 kW), bien sous la capacité.

Le pic n'est donc pas supprimé mais **déplacé** vers des heures où STEG a de la marge. La seule contrainte vérifiée est que chaque voiture soit pleine à son départ.

### 8.5 La journée d'une batterie : BAT-H01 (réactif)

| Heure | SoC début | SoC fin | Puissance (kW) | `stress_score` (kWh) | Explication |
|---:|---:|---:|---:|---:|---|
| 0 | 0,60 | 0,90 | +3,333 | 232,83 | fin de recharge de nuit (heure creuse) |
| 1 à 18 | 0,90 | 0,90 | 0 | 232,83 | attente : pas de déficit |
| 19 | 0,90 | 0,65 | −2,500 | 235,33 | pointe |
| 20 | 0,65 | 0,40 | −2,500 | 237,83 | pointe |
| 21 | 0,40 | 0,15 | −2,500 | 240,33 | pointe |
| 22 | 0,15 | 0,15 | 0 | 240,33 | 22h n'est pas une heure creuse |
| 23 | 0,15 | 0,60 | +5,000 | 240,33 | recharge à 0,15 TND/kWh : 5 × 0,9 = 4,5 kWh stockés |

La recharge commence à 23h et se termine à 0h le lendemain : la batterie est de nouveau à 0,90 pour la pointe suivante. Le `stress_score` (232,8 kWh au début du jour 42) cumule tout depuis le 28 août, sans remise à zéro à minuit.

---

## 9. Le mode prédictif

### 9.1 Le principe

À chaque heure t, le modèle ML a prévu la demande nette de l'heure t+1 (section 10). On déclenche une anticipation si :

```text
demande_nette_prévue × (1 + 5 %) > 150 kW,   soit   demande_nette_prévue > 142,86 kW
```

Dans ce cas, trois choses se passent :

- **(a) Préchargement** : à l'heure t, si STEG a de la marge et qu'une batterie est sous 0,90, on la recharge (`PRECHARGE`). En pratique, cela arrive très rarement (2 fois en 45 jours en scénario normal), car les batteries sont déjà à 0,90 après la recharge de nuit.
- **(b) Report anticipé des VE** : pendant l'heure de pic prévue, les VE non urgents qui n'avaient pas commencé leur recharge ne la démarrent pas (`DELAY`, déclencheur `anticipation`). Cela se fait **avant** de solliciter les batteries.
- **(c) Filet de sécurité** : la couverture réactive (section 8) s'applique ensuite au déficit restant. Si la prévision était fausse, on revient au comportement réactif. Le test `test_predictif_filet_securite` force une prévision nulle et vérifie qu'on n'obtient jamais plus d'énergie non desservie qu'en réactif.

### 9.2 Exemple : vendredi 9 octobre (normal, prédictif)

| Heure | Prévision (kW) | Réel sans orch. (kW) | Déclenché ? | STEG | Batteries | VE reportés | Commentaire |
|---:|---:|---:|:-:|---:|---:|---:|---|
| 17 | 97,48 | 103,20 | non | 103,20 | 0 | 0 | |
| 18 | 155,78 | 143,79 | **oui** | 136,79 | 0 | 7,00 | **faux positif** : pas de déficit réel, VE-H01 reporté pour rien |
| 19 | 183,20 | 198,92 | oui | 150,00 | 9,51 | 41,92 | 6 VE ne démarrent pas, puis 4 batteries couvrent le reste |
| 20 | 169,85 | 174,96 | oui | 144,88 | 0 | 48,92 | report anticipé plus grand que le déficit (43,81 kW) : STEG est sous 150 |
| 21 | 130,51 | 156,28 | non | 150,00 | 17,50 | 12,08 | **prévision trop basse** : le filet réactif prend le relais |
| 23 | 55,70 | 56,92 | non | 114,02 | 0 | 0 | rebond VE + recharge des batteries (28,33 kW) |

Les justifications enregistrées sont explicites, par exemple : « Pic prévu de 183 kW à 19 h -> recharge de VE-H03 non démarrée (7,00 kW reportés, départ à 7 h) ».

Conséquence pour BAT-H01 : en prédictif, elle ne décharge que 2 × 2,5 kW ce jour-là (SoC minimal 0,40) contre 3 × 2,5 kW en réactif (SoC minimal 0,15).

### 9.3 Statistiques de déclenchement sur 45 jours

| Scénario | Heures déclenchées | Heures en déficit réel | Bonnes alertes | Fausses alertes | Déficits non anticipés |
|---|---:|---:|---:|---:|---:|
| normal | 133 | 110 | 105 | 28 | 5 |
| nuageux | 128 | 101 | 96 | 32 | 5 |
| canicule | 176 | 162 | 158 | 18 | 4 |

Les 24 premières heures n'ont pas de prévision (il manque l'historique de 24 h).

**Attention** : sur les jours 1 à 30 (entraînement), le modèle prévoit des heures qu'il a déjà vues pendant son apprentissage. Ces chiffres sont donc optimistes. L'évaluation honnête est celle de la période de test (section 10.6).

### 9.4 Ce que le prédictif change, sur 45 jours (scénario normal)

| | Réactif | Prédictif |
|---|---:|---:|
| Décharge des batteries | 1 702,7 kWh (721 actions) | 792,4 kWh (346 actions) |
| Report VE pour déficit | 1 117,4 kWh | 228,4 kWh |
| Report VE anticipé | — | 4 493,0 kWh (671 actions) |
| Recharge des batteries | 1 923,0 kWh | 908,4 kWh |
| `stress_score` final par batterie | 242,2 à 244,1 kWh | 112,2 à 114,2 kWh |

Le prédictif **divise par deux l'usure des batteries** et réduit les pertes de rendement. En contrepartie, il reporte beaucoup plus de recharges de VE, dont une partie inutilement (fausses alertes).

---

## 10. Le modèle de Machine Learning

Fichier : [backend/forecasting_ml.py](../backend/forecasting_ml.py).

### 10.1 Ce qu'on prévoit

À l'heure t, on prévoit pour l'heure **T = t + 1**, au niveau du quartier :

- la **charge totale** (base + HVAC + VE sans pilotage) ;
- la **production PV** ;
- et on en déduit la **demande nette prévue** = max(charge prévue − PV prévu, 0).

Un modèle par cible : `modele_charge.joblib` et `modele_pv.joblib`.

### 10.2 Les données d'apprentissage

On part des sommes horaires du quartier pour chaque scénario météo (normal, nuageux, canicule) : 45 jours × 24 h = 1 080 heures par scénario. Le scénario `coupure_steg` est exclu, car c'est une copie de `normal`. La première journée est retirée, faute de valeurs de la veille. Il reste 3 × 1 056 = **3 168 lignes**.

### 10.3 Les 11 variables, avec un exemple réel

Exemple : prévision de **19h le vendredi 9 octobre (normal)**, faite à 18h.

| Variable | Valeur | Ce que c'est | Connue à 18h ? |
|---|---:|---|:-:|
| `heure_sin`, `heure_cos` | −0,9659 / 0,2588 | heure 19 encodée sur un cercle (23h est proche de 0h) | oui |
| `day_of_week` | 4 | vendredi | oui |
| `is_weekend` | 0 | jour ouvré | oui |
| `temperature_prevue_c` | 27,97 | température réelle de 19h (27,10) + erreur de prévision météo simulée | oui (prévision) |
| `irradiance_prevue_wm2` | 0,0 | soleil couché (la nuit, la prévision reste 0) | oui (prévision) |
| `charge_lag_1h` | 150,58 | charge à 18h | oui |
| `charge_lag_24h` | 196,19 | charge la veille à 19h | oui |
| `pv_lag_1h` | 6,79 | PV à 18h | oui |
| `pv_lag_24h` | 0,0 | PV la veille à 19h | oui |
| `charge_moy_3h` | 109,94 | moyenne de 16h, 17h, 18h : (63,00 + 116,24 + 150,58) / 3 | oui |

Résultats pour cette heure :

| Modèle | Charge prévue (kW) | Réel (kW) | Erreur (kW) |
|---|---:|---:|---:|
| ML (forêt aléatoire) | 183,20 | 198,92 | −15,72 |
| Baseline (moyenne des 19h précédentes) | 180,54 | 198,92 | −18,39 |
| Persistance (la veille à 19h) | 196,19 | 198,92 | −2,73 |

Ici, la persistance gagne, mais c'est un seul cas. Sur l'ensemble du test, le ML est deux fois plus précis (section 10.6). La pointe reste l'heure la plus difficile à prévoir : les arrivées des VE sont aléatoires et ne figurent dans aucune variable.

### 10.4 Pas de fuite de données

Une variable ne doit jamais utiliser une information postérieure à t. Tous les décalages (`shift`) sont faits vers le passé. La moyenne sur 3 h porte sur t, t−1 et t−2. La baseline n'utilise que les jours strictement antérieurs.

Seule la météo de T est utilisée, et c'est une **prévision** : valeur réelle + bruit gaussien (σ = 1 °C et 50 W/m²), comme le ferait un service météo.

Le test `test_pas_de_fuite_ml` multiplie par 10 toutes les données à partir d'une heure k. Il vérifie que toutes les variables des heures ≤ k restent identiques.

### 10.5 Découpage chronologique (jamais de mélange)

| Split | Jours | Dates | Lignes | Rôle |
|---|---|---|---:|---|
| train | 1 à 30 (30 jours) | 29/08 au 27/09 | 2 160 | apprentissage |
| val | 31 à 36 (6 jours) | 28/09 au 03/10 | 432 | choix des hyperparamètres |
| test | 37 à 44 (8 jours) | 04/10 au 11/10 | 576 | évaluation finale |

Les trois scénarios sont mélangés dans chaque split (mêmes dates), et c'est la météo qui porte l'information du scénario.

### 10.6 Les modèles comparés et le choix des hyperparamètres

1. **Persistance** : la même heure la veille.
2. **Baseline** : la moyenne de la même heure sur tous les jours précédents du même scénario. C'est la version « quartier » de l'ancienne prévision du projet.
3. **ML** : `RandomForestRegressor` (200 arbres, `random_state = 42`). Ce choix est motivé par trois raisons : le modèle est robuste, il a peu de réglages, et il fournit directement l'importance des variables.

Choix des hyperparamètres sur val (MAE en kW) :

| `max_depth` | `min_samples_leaf` | MAE val charge | MAE val PV |
|---:|---:|---:|---:|
| 6 | 1 | 3,877 | 0,358 |
| 6 | 4 | 3,833 | 0,359 |
| 9 | 1 | 2,777 | 0,276 |
| 9 | 4 | 2,855 | 0,296 |
| **12** | **1** | **2,655** | **0,265** |
| 12 | 4 | 2,774 | 0,292 |

Retenu pour les deux cibles : profondeur 12, feuille minimale 1. Chaque arbre de charge a en moyenne 769 feuilles.

### 10.7 Les métriques

- **MAE** : erreur absolue moyenne, en kW.
- **RMSE** : racine de l'erreur quadratique moyenne, en kW ; elle pénalise davantage les grosses erreurs.
- **MAPE** : erreur relative en %, calculée seulement quand la valeur réelle dépasse 5 kW, pour ne pas diviser par un PV nul la nuit.
- **MAE 17h-22h** : la MAE limitée aux heures de pointe.
- **Détection du déficit** : on prévoit un déficit si la demande nette prévue dépasse 150 kW, puis on compare au réel.

**Sur le test (576 heures, jamais vues pendant l'apprentissage) :**

| Modèle | Cible | MAE | RMSE | MAPE (%) | MAE 17h-22h | Précision | Rappel | VP | FP | FN |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ML | charge | **3,316** | 6,194 | 3,36 | 9,155 | | | | | |
| ML | PV | **0,260** | 0,495 | 3,15 | 0,092 | | | | | |
| ML | demande nette | **3,379** | 6,240 | 4,13 | 9,188 | 0,795 | 0,921 | 58 | 15 | 5 |
| Baseline | charge | 6,776 | 9,291 | 8,23 | 10,198 | | | | | |
| Baseline | PV | 0,572 | 1,103 | 7,16 | 0,187 | | | | | |
| Baseline | demande nette | 6,834 | 9,457 | 11,67 | 10,217 | 0,750 | 0,952 | 60 | 20 | 3 |
| Persistance | charge | 7,093 | 11,798 | 7,88 | 14,735 | | | | | |
| Persistance | PV | 0,688 | 1,333 | 9,23 | 0,221 | | | | | |
| Persistance | demande nette | 7,199 | 11,783 | 10,45 | 14,758 | 0,797 | 0,810 | 51 | 13 | 12 |

Lecture :

- **Le ML divise l'erreur par deux** par rapport à la baseline (3,3 contre 6,8 kW sur la charge).
- **En pointe, l'avantage est faible** : 9,2 contre 10,2 kW. C'est là que l'aléa des VE domine.
- **Détection du déficit** : sur 63 heures réellement en déficit, le ML en prévoit 58. Il en manque 5 et donne 15 fausses alertes. La baseline en manque moins (3) mais donne plus de fausses alertes (20). La persistance en manque 12.

**Comparaison train / val / test (ML, charge)** : MAE de 1,06 kW sur train, 2,66 sur val, 3,32 sur test. L'écart avec le train montre un **sur-apprentissage modéré** : des arbres profonds apprennent en partie les données par cœur. C'est pour cela qu'on évalue sur le test.

### 10.8 Ce sur quoi le modèle s'appuie (importances)

- **Charge** :
  - `charge_lag_24h` : 0,943 ;
  - `charge_lag_1h` : 0,022 ;
  - `heure_cos` : 0,009 ;
  - `temperature_prevue_c` : 0,006 ;
  - `charge_moy_3h` : 0,005 ;
  - les autres variables sont sous 0,005.
- **PV** :
  - `irradiance_prevue_wm2` : 0,729 ;
  - `pv_lag_24h` : 0,259 ;
  - les autres variables sont sous 0,006.

Le modèle de charge s'appuie surtout sur « la veille à la même heure », qu'il corrige avec l'heure courante et la température. Le modèle PV s'appuie surtout sur la prévision d'ensoleillement.

### 10.9 Honnêteté méthodologique

Les données sont synthétiques et générées avec des profils réguliers : le modèle **apprend en partie le générateur**. Une MAPE de 3 à 4 % serait difficile à atteindre sur un vrai quartier. Ces performances **ne sont pas transférables** à des données réelles.

---

## 11. Les KPI, avec un calcul complet

Fichier : [backend/kpi.py](../backend/kpi.py). Chaque ligne du bilan vaut 1 h : une puissance en kW pendant 1 h donne une énergie en kWh.

### 11.1 Formules

| KPI | Formule | Unité |
|---|---|---|
| `pic_steg_avant_kw` | max sur les heures de `steg_import` (sans orchestration) | kW |
| `pic_steg_apres_kw` | max sur les heures de `steg_import` (mode évalué) | kW |
| `reduction_pic_pct` | (avant − après) / avant × 100 | % |
| `energie_deplacee_kwh` | Σ `contribution_der` | kWh |
| `energie_steg_*_kwh` | Σ `steg_import` | kWh |
| `consommation_kwh` | Σ (charge totale − recharge des batteries − VE reportés − HVAC réduit − non desservi) | kWh |
| `taux_autonomie_pct` | (1 − énergie STEG / consommation) × 100 | % |
| `facture_steg_*_tnd` | Σ `steg_import` × tarif de l'heure | TND |
| `economie_tnd` | facture avant − facture après | TND |
| `co2_evite_kg` | (énergie STEG avant − après) × 0,45 | kg |
| `energie_non_desservie_kwh` | Σ `energie_non_desservie` | kWh |
| `depassement_steg_kwh` | Σ max(`steg_import` − 150, 0) | kWh |

### 11.2 Calcul complet : vendredi 9 octobre, scénario normal

Énergie STEG et facture par période tarifaire :

| Mode | Creux (23h-6h) | Plein | Pointe (18h-21h) | **Total** |
|---|---|---|---|---|
| Sans orchestration | 212,22 kWh × 0,15 = 31,83 TND | 606,78 kWh × 0,25 = 151,70 TND | 673,96 kWh × 0,35 = 235,88 TND | **1 492,96 kWh / 419,41 TND** |
| Réactif | 261,49 kWh → 39,22 TND | 630,06 kWh → 157,52 TND | 593,79 kWh → 207,83 TND | **1 485,34 kWh / 404,57 TND** |
| Prédictif | 276,82 kWh → 41,52 TND | 643,29 kWh → 160,82 TND | 581,68 kWh → 203,59 TND | **1 501,79 kWh / 405,93 TND** |

On voit le mécanisme : l'orchestration retire environ 80 kWh de la pointe (0,35 TND/kWh) et en rajoute en heures creuses (0,15) et pleines (0,25).

| KPI | Réactif | Prédictif |
|---|---:|---:|
| Pic STEG avant → après | 198,92 → **150,00 kW** | 198,92 → **150,00 kW** |
| Réduction du pic | 24,59 % | 24,59 % |
| Énergie déplacée | 107,91 kWh | 136,94 kWh |
| Économie | 419,41 − 404,57 = **14,85 TND** | 419,41 − 405,93 = **13,48 TND** |
| CO2 évité | (1 492,96 − 1 485,34) × 0,45 = **+3,43 kg** | (1 492,96 − 1 501,79) × 0,45 = **−3,97 kg** |
| Taux d'autonomie | 14,95 % (sans orch. : 14,52 %) | 14,38 % |
| Énergie non desservie | 0 | 0 |
| Dépassement STEG supprimé | 80,16 kWh → 0 | 80,16 kWh → 0 |

### 11.3 Pourquoi le CO2 évité peut être négatif

L'orchestration ne produit pas d'énergie : elle **déplace** des achats.

- Chaque kWh stocké en batterie coûte 1/0,9 = 1,11 kWh acheté à STEG : c'est la perte de rendement.
- L'énergie VE reportée est rachetée plus tard, parfois le jour suivant, ce qui déplace aussi l'énergie d'un jour à l'autre dans les KPI journaliers.

Sur 45 jours, le CO2 évité est donc négatif dans tous les scénarios. Il est moins négatif en prédictif, qui sollicite moins les batteries. Le signe n'est jamais forcé.

---

## 12. Le scénario de coupure STEG

Le vendredi 9 octobre, STEG est coupé de 20h à 23h (heures 20, 21 et 22).

### 12.1 Les règles pendant la coupure

- STEG disponible = 0 kW, donc toute la demande nette devient un déficit.
- Ordre de délestage : **batteries → climatisation (jusqu'à 100 %) → VE (report complet) → charge de base** (énergie non desservie).
- Le plafond d'équité à 50 % est levé.
- Hypothèse : le quartier fonctionne en îlot et le PV continuerait de produire (mais à 20h il n'y a plus de soleil).

### 12.2 Heure par heure (kW)

| Heure | Mode | Demande nette | STEG dispo | STEG | Batteries | VE reportés | HVAC délesté | **Non desservi** |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 19 | réactif | 198,9 | 150 | 150,0 | 17,5 | 31,4 | 0 | 0 |
| 20 | sans orch. | 175,0 | 0 | 0 | 0 | 0 | 0 | **175,0** |
| 20 | réactif | 190,3 | 0 | 0 | 35,0 | 45,4 | 15,0 | **94,9** |
| 20 | prédictif | 193,8 | 0 | 0 | 35,0 | 48,9 | 15,0 | **94,9** |
| 21 | sans orch. | 156,3 | 0 | 0 | 0 | 0 | 0 | **156,3** |
| 21 | réactif | 176,1 | 0 | 0 | 3,5 | 45,4 | 13,3 | **113,9** |
| 21 | prédictif | 179,6 | 0 | 0 | 11,5 | 48,9 | 13,3 | **105,9** |
| 22 | sans orch. | 96,5 | 0 | 0 | 0 | 0 | 0 | **96,5** |
| 22 | réactif | 141,3 | 0 | 0 | 0 | 45,4 | 9,6 | **86,3** |
| 22 | prédictif | 144,8 | 0 | 0 | 0 | 48,9 | 9,6 | **86,3** |
| 23 | réactif | 137,3 | 150 | 137,3 | 0 | 0 | 0 | 0 (STEG revenu, les VE rechargent) |

À 20h en réactif, les 7 batteries donnent chacune 5,00 kW (plafond levé), les 20 climatisations sont délestées (entre 0,63 et 0,90 kW chacune) et les 8 VE sont reportés.

### 12.3 Pourquoi on ne couvre pas tout

- **Les batteries ont déjà écrêté la pointe de 19h.** Elles commencent la coupure à 65 % de SoC. L'énergie disponible est 7 × (0,65 − 0,10) × 10 kWh = **38,5 kWh**, alors que la demande des 3 heures atteint 427,7 kWh (sans orchestration).
- **La demande pendant la coupure est plus élevée en mode orchestré** (190 kW contre 175 kW à 20h), à cause des VE reportés à 19h. Mais ces VE sont eux-mêmes délestés, donc cela ne crée pas de non-desservi supplémentaire.
- **La prévision ne connaît pas les coupures** : le mode prédictif ne peut pas garder de réserve.

KPI du jour de coupure :

| Mode | Énergie non desservie | Durée d'alimentation complète |
|---|---:|---:|
| Sans orchestration | 427,73 kWh | 0 h |
| Réactif | 295,10 kWh | 0 h |
| Prédictif | 287,12 kWh | 0 h |

---

## 13. La validation par optimisation linéaire (LP)

Fichier : [backend/optimizer_lp.py](../backend/optimizer_lp.py). Ce module **ne pilote rien**. Il rejoue le mode réactif du scénario normal et, à chacune des 123 heures de déficit, résout un problème d'optimisation sur le **même état** des ressources :

```text
minimiser   1 × (kW batteries) + 2 × (kW VE reportés) + 3 × (kW HVAC réduits) + 1000 × (kW non couverts)
sous        somme des puissances = déficit
            chaque ressource ≤ sa flexibilité disponible
```

**Exemple, vendredi 9 octobre à 19h (déficit de 48,92 kW)** :

- **Règles** : 17,5 kW de batteries × 1 + 31,42 kW de VE × 2 = **80,34**.
- **LP** : 35 kW de batteries × 1 (7 × 5 kW, sans plafond) + 13,92 kW de VE × 2 = **62,84**.

**Sur les 123 heures** : coût total de 3 937,45 avec les règles contre 3 122,23 avec le LP (+26 %). Les règles coûtent plus cher sur 78 heures. Sur les 45 autres, elles sont optimales. Ces 45 heures ont toutes un déficit d'au plus 16,94 kW, sous les 17,5 kW que peuvent fournir les batteries plafonnées. L'inverse n'est pas vrai : un déficit de seulement 6,21 kW coûte parfois plus cher, quand des batteries presque vides ne peuvent plus fournir leurs 2,5 kW et que les VE prennent le relais.

Conclusion : l'écart vient **entièrement** du plafond d'équité à 50 % (section 8.2). C'est le prix de la répartition de l'usure, que le LP ignore.

---

## 14. Résultats globaux

### 14.1 Sur 45 jours

| Scénario | Mode | Pic STEG (kW) | Réduction moy. (%) | Énergie STEG (kWh) | Facture (TND) | Économie (TND) | CO2 évité (kg) | Autonomie (%) | Non desservi (kWh) | Dépassement (kWh) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| normal | sans orch. | 203,98 | 0 | 66 263,00 | 18 458,92 | 0 | 0 | 15,84 | 0 | 2 321,57 |
| normal | réactif | 150,00 | 16,62 | 66 483,30 | 18 116,90 | 342,02 | −99,13 | 15,56 | 0 | 0 |
| normal | prédictif | 150,00 | 16,68 | 66 382,16 | 18 103,27 | 355,66 | −53,62 | 15,69 | 0 | 0 |
| nuageux | sans orch. | 199,57 | 0 | 71 052,96 | 19 600,34 | 0 | 0 | 7,31 | 0 | 1 956,55 |
| nuageux | réactif | 150,00 | 14,69 | 71 253,06 | 19 307,75 | 292,59 | −90,05 | 7,05 | 0 | 0 |
| nuageux | prédictif | 150,00 | 14,80 | 71 161,82 | 19 310,19 | 290,15 | −48,99 | 7,17 | 0 | 0 |
| canicule | sans orch. | 229,96 | 0 | 78 749,81 | 21 782,65 | 0 | 0 | 14,32 | 0 | 5 292,22 |
| canicule | réactif | 150,00 | 25,45 | 78 781,03 | 20 859,96 | 922,69 | −14,05 | 14,05 | 0,65 | 0 |
| canicule | prédictif | 150,00 | 25,45 | 78 767,39 | 20 848,32 | 934,33 | −7,91 | 14,07 | 0,65 | 0 |
| coupure_steg | sans orch. | 203,98 | 0 | 65 835,28 | 18 318,87 | 0 | 0 | 15,92 | 427,73 | 2 290,33 |
| coupure_steg | réactif | 150,00 | 16,62 | 66 150,74 | 17 995,04 | 323,82 | −141,96 | 15,62 | 295,10 | 0 |
| coupure_steg | prédictif | 150,00 | 16,68 | 66 062,31 | 17 986,33 | 332,54 | −102,16 | 15,74 | 287,12 | 0 |

### 14.2 Les messages à retenir

1. **La capacité STEG est toujours respectée** en mode orchestré. Hors coupure, la seule énergie non desservie est de 0,65 kWh, sur une heure de canicule (jour 34, 19h).
2. **L'économie vient du déplacement des achats** de la pointe (0,35 TND/kWh) vers les heures creuses (0,15) : environ 7,6 TND par jour en normal et 20,5 en canicule.
3. **L'orchestration ne réduit pas l'énergie achetée**, à cause des pertes des batteries. Le CO2 évité est donc négatif, et l'autonomie (fournie par le PV seul) baisse légèrement.
4. **Le prédictif sert surtout à ménager les batteries** (usure divisée par deux). Son gain en TND est faible et pas systématique : −2,06 TND en canicule sur la période de test.
5. **Pendant une coupure en pleine pointe**, les DER limitent les dégâts (−31 % d'énergie non desservie) sans pouvoir remplacer STEG.

---

## 15. Où retrouver chaque élément dans le tableau de bord

`streamlit run app.py`, puis choisir dans la barre latérale le scénario, le jour (le 2026-10-09 correspond au jour 42), le mode et la capacité STEG.

| Élément du document | Endroit dans le tableau de bord | Source |
|---|---|---|
| KPI du jour (11.2) | cartes en haut de page | `kpi_results` |
| Bilan heure par heure (8.3, 9.2, 12.2) | onglet « Bilan énergétique » : barres empilées + ligne de capacité + tableau horaire | `bilan_horaire` |
| SoC des batteries (8.5) | onglet « Bilan énergétique », second graphique | `etat_batteries` |
| Justifications (8.3, 9.2) | onglet « Actions de l'orchestrateur », filtrable par déclencheur | `orchestrator_actions` |
| Prévu contre réel, métriques, importances (10) | onglet « Prévision ML » | `forecasts`, `model_metrics`, `feature_importances` |
| Comparaison réactif / prédictif (14) | onglet « Réactif vs Prédictif » (période de test) | `kpi_results` |
| Sessions VE, PV, HVAC (3) | onglet « Parc de ressources » | `ev_sessions`, `measurements` |
| Autre capacité STEG | curseur de la barre latérale : la simulation est relancée en mémoire, rien n'est enregistré | `simulation.simuler_scenario` |

---

## 16. Tests automatiques

`python -m pytest -q` donne **28 passed**. Les tests du pipeline tournent sur une base temporaire de 20 jours et ne modifient jamais `ider.db`.

| Test | Ce qu'il prouve |
|---|---|
| `test_bilan_energetique` | STEG + DER + PV utilisé + non desservi = charge totale, à 1e-6 près, pour chaque heure des 3 modes |
| `test_steg_capacite` | STEG ≤ 150 kW en mode orchestré ; la référence dépasse bien 150 kW |
| `test_soc_bornes` | SoC toujours dans [0,10 ; 1,0] |
| `test_stress_score_monotone_et_continuite` | le score ne baisse jamais ; le SoC de début d'heure = le SoC de fin de l'heure précédente (minuit compris) ; pas de remise à 0,50 chaque jour |
| `test_predictif_filet_securite` | avec une prévision forcée à 0, le prédictif n'a pas plus de non-desservi que le réactif |
| `test_coupure_steg` | STEG = 0 pendant la coupure, et les autres scénarios ne sont pas modifiés |
| `test_recharge_ve_non_pilotee_identique_au_dataset` | la référence reproduit la recharge VE du jeu de données, et aucune voiture ne part incomplète |
| `test_dataset_reproductible` | même graine → mêmes données ; autre graine → autres données |
| `test_variabilite_journaliere` | les pics varient d'un jour à l'autre ; la canicule est plus forte |
| `test_dates_dynamiques` | la dernière date est aujourd'hui (± 1 jour) |
| `test_courbe_hors_pointe` | hors 17h-22h, la demande reste sous 150 kW ; en pointe, elle dépasse |
| `test_nuageux_moins_de_pv_en_fin_de_journee` | PV de 17h-18h réduit de plus de 40 % en nuageux |
| `test_coupure_ne_change_que_la_disponibilite` | `coupure_steg` = `normal` sauf `steg_available` |
| `test_kpi_agregation` | pic = max des sommes horaires (100 kW sur un cas jouet), et non le max d'une maison (12 kW) |
| `test_economie_unites` | 10 kWh déplacés de 19h à 2h → économie = 10 × (0,35 − 0,15) = 2 TND |
| `test_kpi_uniques_et_coherents` | pas de doublon, et pics cohérents avec le bilan |
| `test_pas_de_fuite_ml` | variables inchangées si l'on falsifie le futur ; split chronologique |
| `test_ml_metriques` | modèles sauvegardés et rechargeables ; métriques comparées sur le même test |
| `test_predict_next_hour_coherent_avec_le_lot` | la fonction de prévision unitaire donne le même résultat que le calcul par lot |
| `test_lp_*` | le LP ne coûte jamais plus que les règles ; l'écart vient du plafond d'équité |
| `test_orchestrator.py` (7 tests) | ordre de mérite, SoC minimal, report VE borné, équité, plafond levé en coupure, déficit non couvert signalé |

---

## 17. Limites

- **Données synthétiques** : aucune mesure réelle, et le ML apprend en partie le générateur.
- **Tarifs, heures tarifaires et facteur CO2 illustratifs**, à remplacer par des valeurs officielles et sourcées.
- **Pas de physique du réseau** : ni tension, ni fréquence, ni pertes en ligne. Le quartier est un seul nœud.
- **Coupure** : le quartier est supposé capable de fonctionner en îlot.
- **HVAC** : réduction sans effet rebond ni modèle thermique du bâtiment.
- **VE** : pas de temps horaire, une session par jour et par voiture, mêmes habitudes tous les jours (à l'aléa près).
- **Plafond d'équité** : il s'applique en pratique à toutes les batteries (section 8.2), ce qui sous-utilise leur puissance.
- **`stress_score`** : cumul de kWh déchargés, pas un modèle de vieillissement chimique.
- **Prédictif** : il reporte tous les VE non démarrés quand une alerte est donnée, même au-delà du besoin (20h le 9 octobre). Il ne connaît pas les coupures, et sur les jours d'entraînement il utilise des prévisions faites sur des données déjà vues (KPI optimistes hors période de test).
- **Batteries de la référence** : elles restent à SoC 0,50, et l'écart d'énergie stockée en fin de période n'est pas corrigé dans les KPI.
- **Dates dynamiques** : les jours de week-end, donc certains chiffres, changent selon la date d'exécution.

---

## 18. Questions probables et réponses

**Pourquoi STEG est-il plafonné à 150 kW ?**
C'est l'hypothèse de capacité du raccordement du quartier (le poste qui l'alimente). Au-delà, il y aurait surcharge. Dans le mode de référence, cette surcharge vaut 2 321,57 kWh sur 45 jours (scénario normal).

**D'où viennent les données ?**
D'un générateur synthétique reproductible (section 3). Les paramètres sont des hypothèses de conception (section 2), pas des mesures STEG.

**Comment savez-vous que le bilan est juste ?**
L'identité STEG + DER + PV + non desservi = charge est vérifiée à 1e-6 près à chacune des 12 960 heures × modes (test `test_bilan_energetique`).

**Pourquoi les batteries ne donnent-elles que 2,5 kW ?**
À cause de la règle d'équité, qui plafonne en pratique toutes les batteries (section 8.2). Sans elle, le coût de mobilisation baisserait de 26 % (section 13), mais l'usure serait moins bien répartie.

**Le ML est-il utile ?**
Comme prévision, oui : son erreur est deux fois plus faible que celle de la baseline sur des jours jamais vus (3,3 contre 6,8 kW). Comme levier de pilotage, son apport principal est de diviser par deux l'usure des batteries. Le gain financier est faible.

**Comment évitez-vous la fuite de données ?**
Toutes les variables sont décalées vers le passé, la météo future est une prévision bruitée, le découpage est chronologique, et un test le vérifie (section 10.4).

**Pourquoi le CO2 évité est-il négatif ?**
Parce que stocker de l'énergie coûte 10 % de pertes. L'orchestration réduit le pic et la facture, pas la quantité d'énergie achetée (section 11.3).

**Que se passe-t-il si la prévision se trompe ?**
La couverture réactive reste active comme filet de sécurité. Exemple : à 21h le 9 octobre, la prévision était de 130,5 kW pour un réel de 156,3 kW, et le pic a quand même été tenu à 150 kW.

**Les DER peuvent-ils remplacer STEG pendant une coupure ?**
Non, pas pendant la pointe du soir. Les 7 batteries n'ont que 38,5 kWh disponibles face à 427,7 kWh demandés. Les DER réduisent l'énergie non desservie de 31 %.

**Pourquoi le scénario nuageux a-t-il un pic plus bas que le normal ?**
À 19h, le soleil est couché (le PV ne compte plus), et il fait 2 °C de moins, donc il y a moins de climatisation. En revanche, la demande en journée est plus élevée (+13 à +15 kW à 10h-13h).

---

## 19. Glossaire

| Terme | Définition |
|---|---|
| **STEG** | Société tunisienne de l'électricité et du gaz ; ici, la source d'énergie de base du quartier |
| **DER** | *Distributed Energy Resources* : ressources locales (PV, batteries, VE, HVAC) |
| **Demande nette** | consommation du quartier moins la production PV consommée sur place (kW) |
| **Déficit** | partie de la demande nette au-delà de la capacité STEG (kW) |
| **Contribution DER** | décharge des batteries + recharge VE reportée + réduction HVAC (kW) |
| **Énergie non desservie** | demande qu'aucune source n'a pu servir (délestage) |
| **Dépassement STEG** | surcharge au-delà de 150 kW dans le mode de référence |
| **SoC** | *State of Charge* : niveau de charge d'une batterie, de 0 à 1 |
| **`stress_score`** | énergie déchargée cumulée par une batterie (kWh), qui sert à répartir l'usure |
| **Ordre de mérite** | ordre dans lequel les ressources sont sollicitées : batteries, VE, HVAC |
| **Effet rebond** | la recharge VE reportée revient plus tard et augmente la charge à ce moment-là |
| **Heures creuses / pleines / pointe** | périodes tarifaires (23h-6h / reste / 18h-21h), illustratives |
| **Persistance** | prévision naïve : la valeur de la veille à la même heure |
| **Baseline** | prévision simple : la moyenne de la même heure sur les jours précédents |
| **Fuite de données** | utilisation, pour prévoir, d'une information qui ne serait pas encore connue |
| **MAE / RMSE / MAPE** | erreur absolue moyenne (kW) / erreur quadratique moyenne (kW) / erreur relative moyenne (%) |
| **Précision / rappel** | part des alertes de déficit justes / part des déficits réels détectés |
| **LP** | programmation linéaire : optimisation exacte utilisée ici comme référence de coût |
| **Split train / val / test** | découpage chronologique pour apprendre, régler, puis évaluer le modèle |
