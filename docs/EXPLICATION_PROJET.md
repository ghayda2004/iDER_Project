

> Ce guide décrit le code et la base `ider.db` présents au moment de sa rédaction. Les chiffres ci-dessous proviennent de requêtes SQLite exécutées sur cette base; les renvois donnent les fichiers et lignes du code qui produisent ou utilisent ces valeurs. Les limites de modèle sont signalées au lieu d'être présentées comme des fonctions déjà réalisées.

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Dataset](#2-dataset-en-détail)
3. [Base et visualisation](#3-base-de-données-et-visualisation)
4. [Modèles de ressources](#4-modèles-de-ressources)
5. [Orchestrateur](#5-lorchestrateur-pas-à-pas)
6. [KPI](#6-kpi)
7. [Sandbox](#7-mode-sandbox)
8. [Dashboard](#8-dashboard-onglet-par-onglet)
9. [Démonstration orale](#9-guide-de-démonstration-de-8-à-10-minutes)
10. [Questions de l'enseignante](#10-préparation-aux-questions)
11. [Glossaire](#11-glossaire)
12. [Vérification et fragilités](#12-vérification-finale)

## 1. Vue d'ensemble

### En dix lignes

iDER est un proof-of-concept académique associé au cours « Digital Grid and Business Value ».
Il représente un quartier de 20 maisons avec PV, batteries, véhicules électriques et charges HVAC.
Il crée des profils synthétiques horaires pour trois scénarios : normal, nuageux et canicule.
Il stocke les mesures, actions et indicateurs dans le fichier local SQLite `ider.db`.
Le simulateur additionne les puissances des maisons heure par heure et compare le total à 150 kW.
L'orchestrateur essaie d'abord les batteries, puis le report de charge des VE, puis le HVAC.
Le dashboard Streamlit lit la base et propose un calcul Sandbox « what-if » en mémoire.
Les tests vérifient six comportements ciblés des classes et du dispatch.
Le projet ne reçoit pas de télémétrie réelle et ne commande aucun équipement électrique.
Les chiffres et économies affichés sont des résultats de simulation, pas des mesures terrain ni une facture.

Les paramètres de parc et la limite sont définis dans [backend/config.py](../backend/config.py#L3-L20) : `NB_MAISONS = 20`, `NB_JOURS = 7`, `GRID_LIMIT_KW = 150`, 13 maisons PV, 7 batteries, 8 VE et `SCENARIOS = ["normal", "nuageux", "canicule"]`.

### Parcours d'une donnée

1. **Génération — [backend/generate_dataset.py](../backend/generate_dataset.py#L53-L111).** Le script construit une ligne par scénario, jour, maison et heure. Exemple réel : normal, jour 0, 19 h, maison H01 a `base_load_kw=6.781725...`, `pv_kw=0` et `hvac_kw=1.559153...`; le résultat enregistré est `grid_import_kw=8.3409`.
2. **Calibration — [backend/calibration.py](../backend/calibration.py#L5-L29).** Le pic brut du scénario normal est mesuré après agrégation horaire, puis un facteur commun ajuste `base_load_kw` et `hvac_kw`. La dernière génération mesurée a donné un facteur `1.4849`; PV n'est pas multiplié par cette calibration.
3. **Persistance — [backend/database.py](../backend/database.py#L17-L50) et [backend/database.py](../backend/database.py#L53-L79).** `init_db()` crée les tables et `save_measurement()` insère les mesures dans `ider.db`. Les trois scénarios contiennent chacun 3 360 lignes.
4. **Simulation — [backend/simulation.py](../backend/simulation.py#L60-L116).** Elle lit un scénario/jour, construit sept batteries, huit VE et vingt HVAC, agrège les mesures chaque heure, prévoit la demande, appelle un dispatch et écrit actions et KPI.
5. **Orchestration — [backend/orchestrator.py](../backend/orchestrator.py#L8-L97).** Pour le cas normal, jour 0, 19 h, les neuf actions persistées totalisent 28,96 kW affichés face à un déficit calculé de 28,9594 kW.
6. **Affichage — [app.py](../app.py#L83-L107), [app.py](../app.py#L307-L350) et [app.py](../app.py#L430-L550).** Streamlit relit SQLite, additionne les maisons pour tracer le quartier et affiche les mesures, les actions et les KPI. Le Sandbox appelle directement `dispatch()` en mémoire; il n'enregistre pas ses actions.

## 2. Dataset en détail

### Origine, génération et temps simulé

Les données sont synthétiques : le générateur contient des règles et des tirages NumPy, mais aucune lecture de compteur, fichier météo externe ou API de données réelles. Les niveaux de base viennent des constantes de [backend/config.py](../backend/config.py#L14-L20) : nuit 1,0 kW, matin 3,0 kW, journée 2,0 kW et soir 4,5 kW. `house_profile()` ajoute une sinusoïde et un décalage déterministe selon le numéro de maison ([backend/generate_dataset.py](../backend/generate_dataset.py#L38-L50)).

La graine `np.random.seed(42)` est appelée une fois au niveau du module avant la fonction de génération ([backend/generate_dataset.py](../backend/generate_dataset.py#L35)). La demande a en outre un multiplicateur aléatoire par jour/maison, tiré selon une loi normale de moyenne 1,0 et écart-type 0,03 puis borné entre 0,9 et 1,1 ([backend/generate_dataset.py](../backend/generate_dataset.py#L60-L64)). Le même multiplicateur jour/maison est partagé par les trois scénarios : cela fait varier les jours, mais permet de comparer les facteurs météo à charge de base identique.

D'autres tirages produisent le PV de chaque maison, le SOC initial batterie, le SOC initial VE et des heures d'arrivée/départ ([backend/generate_dataset.py](../backend/generate_dataset.py#L74-L87)). La variable `jour` va de 0 à 6; la table ne contient pas de date civile. `DATE_DEBUT = datetime.now() - timedelta(days=NB_JOURS)` existe dans `config.py` ([backend/config.py](../backend/config.py#L3-L6)), mais le générateur ne l'utilise pas et aucune colonne date n'est enregistrée. Il serait donc incorrect de présenter les sept index comme des dates calendaires précises.

Une autre simplification observable : `arrival` et `departure` sont calculés mais ne sont pas conservés dans `measurements`; le tirage `departure` utilise par erreur `EV_ARRIVEE_MOYENNE_H` (18) avant d'être borné entre 6 et 11, au lieu d'utiliser `EV_DEPART_MOYEN_H`. `ev_connected` teste ensuite deux valeurs déjà bornées dans des plages valides; il vaut donc 1 pour les huit maisons équipées. Le départ affiché ensuite est la constante configurée 7 h, non le départ tiré pour cette ligne.

### Structure de `measurements`

SQLite déclare `id INTEGER PRIMARY KEY AUTOINCREMENT`, les dimensions catégorielles/horaires et les puissances/SOC comme colonnes numériques ([backend/database.py](../backend/database.py#L20-L31)). Toutes les colonnes de cette table contiennent zéro valeur NULL dans la base auditée. Les plages ci-dessous sont des min/max réellement interrogés sur les 10 080 lignes actuelles; le nombre de décimales affiché est arrondi pour la lecture.

| Colonne | Type SQLite | Unité | Sens | Plage réellement observée | Production de la valeur |
|---|---|---|---|---|---|
| `id` | INTEGER | sans unité | Clé technique d'une ligne. | 39 899 à 49 978 | `AUTOINCREMENT`. Les identifiants ont des trous car des générations précédentes ont purgé les lignes sans réinitialiser la séquence. |
| `scenario` | TEXT | catégorie | Scénario météo. | `canicule`, `normal`, `nuageux` | Boucle sur `SCENARIOS` dans le générateur. |
| `jour` | INTEGER | index de jour | Position dans la semaine simulée. | 0 à 6 | `range(NB_JOURS)`. Ce n'est pas une date calendrier. |
| `heure` | INTEGER | heure | Heure du profil. | 0 à 23 | `range(24)`. |
| `house_id` | TEXT | identifiant | Maison simulée. | H01 à H20 | `f"H{maison_idx + 1:02d}"`. |
| `base_load_kw` | REAL | kW | Charge de base synthétique de la maison avant PV/HVAC. | 0,9096549 à 8,3160809 | Profil nuit/matin/jour/soir + sinusoïde + effet maison + facteur aléatoire jour/maison, puis calibration globale. |
| `pv_kw` | REAL | kW | Production PV affectée à la maison cette heure. | 0 à 3,3125 | Tirage normal pour les maisons PV; non nul uniquement de 7 h à 18 h; facteurs météo ensuite. |
| `battery_soc` | REAL | % | État de charge simulé de la batterie; zéro désigne une maison sans batterie. | 0 à 93,46 | SOC initial aléatoire, puis +0,15 point par heure, borné par la configuration du générateur. Ce n'est pas l'état après dispatch. |
| `ev_soc` | REAL | % | État de charge simulé du VE; zéro désigne une maison sans VE. | 0 à 50,71 | SOC initial aléatoire; hausse de 0,2 point à partir de 20 h, bornée à `EV_TARGET_SOC`. Pas de mise à jour issue des actions de simulation. |
| `ev_connected` | INTEGER | booléen 0/1 | Indique si le VE est considéré connecté. | 0 à 1 | Test des heures tirées/bornées; la connexion est ensuite répétée sur les 24 mesures du jour. |
| `hvac_kw` | REAL | kW | Charge HVAC pilotable synthétique. | 0,9651904 à 3,2074021 | 0,65 + supplément 0,40 entre 18 h et 22 h + effet maison; facteurs canicule et calibration. |
| `grid_import_kw` | REAL | kW | Import réseau net de cette maison avant dispatch. | 1,696 à 11,337 | `max(0, base_load_kw + hvac_kw - pv_kw)`, arrondi à quatre décimales. |

`battery_soc` et `ev_soc` étant zéro pour les maisons sans équipement, les minimums globaux zéro ne signifient pas qu'une batterie équipée fonctionne à 0 %. Dans les maisons avec équipement, l'intervalle observé doit être lu en filtrant la présence correspondante.

### Volumétrie

La base a **10 080** mesures, soit exactement $20 \times 24 \times 7 \times 3 = 10\,080$. La requête donne 3 360 lignes pour chacun de `normal`, `nuageux` et `canicule`; un jour contient 20 maisons × 24 heures = 480 lignes par scénario. Vérification actuelle : `COUNT(DISTINCT house_id)=20`, `COUNT(DISTINCT jour)=7`, `COUNT(DISTINCT heure)=24`.

### Dix lignes réelles : normal, jour 0, 19 h

Les dix lignes ci-dessous sont les dix premières maisons de la requête SQLite, triées par `house_id`. Les puissances sont en kW, les SOC en %, et `ev_connected` en 0/1. À 19 h, le PV est nul pour toutes les lignes car la règle de génération s'arrête à 18 h.

| Maison | `base_load_kw` | `pv_kw` | `battery_soc` | `ev_soc` | `ev_connected` | `hvac_kw` | `grid_import_kw` |
|---|---:|---:|---:|---:|---:|---:|---:|
| H01 | 6,7817251 | 0 | 83,59 | 27,26 | 1 | 1,5591538 | 8,3409 |
| H02 | 6,9205640 | 0 | 79,78 | 30,48 | 1 | 1,7818901 | 8,7025 |
| H03 | 7,3568301 | 0 | 85,84 | 22,52 | 1 | 2,0046263 | 9,3615 |
| H04 | 7,8259126 | 0 | 73,10 | 24,82 | 1 | 1,5591538 | 9,3851 |
| H05 | 7,6967256 | 0 | 87,24 | 27,12 | 1 | 1,7818901 | 9,4786 |
| H06 | 6,6351646 | 0 | 85,99 | 45,48 | 1 | 2,0046263 | 8,6398 |
| H07 | 7,2785754 | 0 | 78,30 | 27,32 | 1 | 1,5591538 | 8,8377 |
| H08 | 7,3828160 | 0 | 0 | 46,76 | 1 | 1,7818901 | 9,1647 |
| H09 | 7,3785097 | 0 | 0 | 0 | 0 | 2,0046263 | 9,3831 |
| H10 | 7,8774390 | 0 | 0 | 0 | 0 | 1,5591538 | 9,4366 |

Comment lire chaque ligne : H01 consomme 6,7817251 kW de charge de base et 1,5591538 kW de HVAC; son PV vaut zéro à 19 h, donc `grid_import_kw` est leur somme arrondie, 8,3409 kW. H01–H07 ont une batterie; H08 n'en a pas, d'où SOC batterie 0. H01–H08 ont un VE connecté; H09 et H10 n'ont ni VE (`ev_soc=0`) ni connexion (`ev_connected=0`). H02 à H10 suivent la même relation de puissance : base + HVAC - PV, plafonnée à zéro puis arrondie.

Sur l'ensemble des 20 maisons à 19 h, la somme est **178,9594 kW** et la moyenne est **8,94797 kW**. La somme représente la puissance du quartier raccordé au feeder; la moyenne n'est que la consommation moyenne d'une maison et ne doit pas être comparée directement à une limite feeder de 150 kW.

### Interprétation de `grid_import_kw`

Dans le code, la formule applique `max(0, base + HVAC - PV)` ([backend/generate_dataset.py](../backend/generate_dataset.py#L108-L111)). Une valeur positive signifie import net. Zéro signifierait que la production locale couvre au moins la charge modélisée; une valeur négative représenterait normalement un export, mais **le générateur la coupe à zéro**, donc aucune valeur négative/export n'est conservée. Dans la base actuelle le minimum est 1,696 kW, donc même zéro ne se produit pas.

Pour le quartier, on somme `grid_import_kw` des 20 maisons à la même heure. Pour normal/jour 0, 19 h, la somme 178,9594 kW est la demande avant dispatch. Le code du graphique fait la même somme dans [app.py](../app.py#L107-L113), et la simulation aussi ([backend/simulation.py](../backend/simulation.py#L69-L78)). Une moyenne masquerait le fait que le feeder doit fournir l'addition des appels de puissance simultanés.

### Scénarios observés

| Scénario | Paramètres appliqués | Pic max mesuré | Heure du pic | Heures >150 kW sur 7 jours |
|---|---|---:|---:|---:|
| Normal | PV ×1,0; HVAC ×1,0 | 180,0000 kW | 19 h, chaque jour | 42 (6 par jour) |
| Nuageux | PV ×0,4; HVAC ×1,0 | 180,0000 kW | 19 h, chaque jour | 49 (7 par jour) |
| Canicule | PV ×1,1; HVAC ×1,6 | 201,2490 kW | 19 h, chaque jour | 49 (7 par jour) |

Les maxima normaux et nuageux sont identiques jour par jour car le maximum arrive à 19 h, où la génération PV est nulle. Leur profil ensoleillé n'est pas identique : à 18 h du jour 0, normal vaut 158,8901 kW avec 22,7457 kW de PV; nuageux vaut 172,6998 kW avec 8,93612 kW de PV. Nuageux sollicite donc le dispatch à 17 h (prévision), 18 h et 19 h, quand normal n'a pas l'événement de 17 h. La charge journalière commune par maison est volontairement partagée entre scénarios; le facteur PV explique leur différence à 18 h.

### Calibration

`calibrer_dataset()` vise 180 kW pour le maximum agrégé brut normal ([backend/calibration.py](../backend/calibration.py#L5-L29)). Sur la génération courante, le pic de référence brut est 121,22 kW et le facteur est 1,4849. Le facteur est commun à toutes les lignes : il multiplie `base_load_kw` et `hvac_kw`, pas `pv_kw`. `generate_dataset.py` applique ensuite les facteurs PV/HVAC météo ([backend/generate_dataset.py](../backend/generate_dataset.py#L116-L129)).

C'est une calibration de démonstration : elle rend un pic de l'ordre de 180 kW comparable à une limite de 150 kW dans un dataset de 20 maisons. Ce n'est pas une calibration statistique sur une année de compteurs ni une validation physique du feeder. Il faut l'assumer comme un choix de mise en scène académique.

## 3. Base de données et visualisation

### Fichier et tables

`ider.db` est un fichier SQLite lu par `sqlite3.connect()` ([backend/database.py](../backend/database.py#L11-L15)). SQLite est embarqué : aucun serveur de base de données séparé n'est nécessaire. La base auditée contient trois tables applicatives et la table technique SQLite `sqlite_sequence` utilisée par `AUTOINCREMENT`.

| Table | Lignes actuelles | Colonnes et rôle |
|---|---:|---|
| `measurements` | 10 080 | `id` entier; `scenario` texte; `jour`, `heure` entiers; `house_id` texte; charges, PV, SOC et import (`REAL`, sauf connexion entière). Une ligne par maison/heure/scénario. |
| `orchestrator_actions` | 908 | `id`; `scenario`; `jour`; `heure`; `device_id`; `device_type`; `action_type`; `power_kw`; `justification`. Journal des actions du mode règles courant. Cette base ne contient que `battery/DISCHARGE` et `ev/DELAY`, pas de HVAC. |
| `kpi_results` | 21 | `scenario`, `jour`, `pic_avant_kw`, `pic_apres_kw`, `energie_deplacee_kwh`, `economie_estimee_eur`, `co2_evite_kg`. Une ligne par scénario et jour de cette génération. |
| `sqlite_sequence` | 2 séquences | Table interne SQLite conservant les derniers numéros d'identifiant pour les tables `AUTOINCREMENT`; ce n'est pas une table métier. |

Exemple réel : la première ligne `measurements` actuellement sélectionnée est `(39899, 'normal', 0, 0, 'H01', 0.99756145, 0.0, 80.74, 27.26, 1, 0.96519045, 1.9628)`. La première action est `(6415, 'normal', 0, 18, 'B001', 'battery', 'DISCHARGE', 5.0, 'Batterie B001 choisie (score équité 5.0 kWh cumulés) : -5.0 kW')`. Le KPI normal/jour 0 est `(normal, 0, 178.9594, 150.0048, 117.69, 5.79092, 47.076)`.

### Ouvrir la base sous Windows

**DB Browser for SQLite (gratuit)**

1. Télécharger DB Browser for SQLite depuis le site du projet `sqlitebrowser.org` et installer la version Windows.
2. Ouvrir l'application, choisir **Open Database…**, puis sélectionner le fichier `ider.db` à la racine du projet.
3. Dans **Browse Data / Parcourir les données**, choisir `measurements`, `orchestrator_actions` ou `kpi_results` dans la liste des tables.
4. Pour les requêtes ci-dessous, ouvrir **Execute SQL / Exécuter le SQL**, coller une requête, puis cliquer **Execute**. La sortie affichée est un résultat de lecture; ne pas cliquer sur Write Changes après une requête de modification.

**VS Code avec une extension SQLite**

1. Ouvrir **Extensions** (`Ctrl+Shift+X`) et rechercher une extension de visualisation SQLite, par exemple **SQLite Viewer**, ou **SQLite** avec support de commandes SQL.
2. Installer l'extension choisie depuis le Marketplace de VS Code.
3. Dans l'explorateur, ouvrir `ider.db` avec la commande **Open Database** ou **Open With SQLite Viewer** fournie par l'extension.
4. Pour exécuter les requêtes, utiliser la commande SQL de l'extension et sélectionner la base `ider.db` comme connexion. Les noms de commandes exacts peuvent varier selon l'extension.

### Huit requêtes SQL vérifiées sur cette base

Les sorties ci-dessous sont celles obtenues sur le `ider.db` actuel. Les requêtes sont en lecture seule.

**1. Nombre de lignes par scénario**

```sql
SELECT scenario, COUNT(*) AS lignes
FROM measurements
GROUP BY scenario
ORDER BY scenario;
```

| Scénario | Lignes |
|---|---:|
| canicule | 3 360 |
| normal | 3 360 |
| nuageux | 3 360 |

**2. Demande du quartier, heure par heure, normal jour 0**

```sql
SELECT heure, ROUND(SUM(grid_import_kw), 4) AS quartier_kw
FROM measurements
WHERE scenario = 'normal' AND jour = 0
GROUP BY heure
ORDER BY heure;
```

| Heure | kW | Heure | kW | Heure | kW |
|---:|---:|---:|---:|---:|---:|
| 0 | 53,6822 | 8 | 102,6922 | 16 | 77,7828 |
| 1 | 53,3298 | 9 | 105,1866 | 17 | 149,5049 |
| 2 | 53,6822 | 10 | 77,7828 | 18 | 158,8901 |
| 3 | 54,7153 | 11 | 79,4259 | 19 | 178,9594 |
| 4 | 56,3586 | 12 | 80,4593 | 20 | 176,2828 |
| 5 | 58,5003 | 13 | 80,8115 | 21 | 173,7888 |
| 6 | 120,0852 | 14 | 80,4593 | 22 | 171,6471 |
| 7 | 100,0163 | 15 | 79,4259 | 23 | 158,1248 |

**3. Pic quotidien par scénario et jour**

```sql
SELECT scenario, jour, ROUND(MAX(total_kw), 4) AS pic_kw
FROM (
    SELECT scenario, jour, heure, SUM(grid_import_kw) AS total_kw
    FROM measurements
    GROUP BY scenario, jour, heure
)
GROUP BY scenario, jour
ORDER BY scenario, jour;
```

| Jour | Normal | Nuageux | Canicule |
|---:|---:|---:|---:|
| 0 | 178,9594 | 178,9594 | 200,2085 |
| 1 | 178,5623 | 178,5623 | 199,8116 |
| 2 | 179,6127 | 179,6127 | 200,8617 |
| 3 | 179,5036 | 179,5036 | 200,7526 |
| 4 | 179,6322 | 179,6322 | 200,8814 |
| 5 | 180,0000 | 180,0000 | 201,2490 |
| 6 | 179,1975 | 179,1975 | 200,4468 |

**4. Heures de dépassement normal jour 0**

```sql
SELECT heure, ROUND(total_kw, 4) AS quartier_kw
FROM (
    SELECT heure, SUM(grid_import_kw) AS total_kw
    FROM measurements
    WHERE scenario = 'normal' AND jour = 0
    GROUP BY heure
)
WHERE total_kw > 150
ORDER BY heure;
```

Résultat : 18 h 158,8901 kW; 19 h 178,9594 kW; 20 h 176,2828 kW; 21 h 173,7888 kW; 22 h 171,6471 kW; 23 h 158,1248 kW. Il y a six heures au-dessus de 150 kW.

**5. Actions à 19 h, normal jour 0**

```sql
SELECT device_id, device_type, action_type, power_kw, justification
FROM orchestrator_actions
WHERE scenario = 'normal' AND jour = 0 AND heure = 19
ORDER BY id;
```

Résultat résumé : B004, B005, B006, B007, B003 et B002 déchargent 2,50 kW chacun; B001 décharge 2,07 kW; E001 reporte 7,00 kW; E002 reporte 4,89 kW. Total des valeurs d'action arrondies : 28,96 kW. Les justifications détaillées figurent à la partie 5.

**6. Puissance d'action cumulée par type**

```sql
SELECT device_type, COUNT(*) AS actions,
       ROUND(SUM(ABS(power_kw)), 2) AS somme_puissances_kw
FROM orchestrator_actions
GROUP BY device_type
ORDER BY device_type;
```

| Type | Actions | Somme des puissances |
|---|---:|---:|
| battery | 472 | 1 029,34 kW-créneaux |
| ev | 436 | 2 561,60 kW-créneaux |

Le code interprète un dispatch comme un créneau d'une heure; sous cette hypothèse seulement, ces sommes correspondent à 1 029,34 kWh et 2 561,60 kWh. `power_kw` reste la colonne stockée.

**7. Classement des batteries, stress reconstitué pour normal jour 0**

`stress_score` n'est pas une colonne de base. Cette requête reconstitue la somme des actions de batterie sur le jour sélectionné :

```sql
SELECT device_id, ROUND(SUM(ABS(power_kw)), 2) AS stress_score_kwh,
       COUNT(*) AS actions
FROM orchestrator_actions
WHERE scenario = 'normal' AND jour = 0 AND device_type = 'battery'
GROUP BY device_id
ORDER BY stress_score_kwh DESC, device_id;
```

| Batterie | Somme journalière des décharges (kW-créneaux) | Actions |
|---|---:|---:|
| B005 | 7,44 | 3 |
| B006 | 7,31 | 3 |
| B003 | 7,30 | 4 |
| B001 | 7,07 | 2 |
| B002 | 6,69 | 3 |
| B007 | 6,55 | 3 |
| B004 | 6,02 | 3 |

**8. KPI complets pour normal**

```sql
SELECT scenario, jour, pic_avant_kw, pic_apres_kw,
       energie_deplacee_kwh, economie_estimee_eur, co2_evite_kg
FROM kpi_results
WHERE scenario = 'normal'
ORDER BY jour;
```

| Jour | Pic avant (kW) | Pic après (kW) | Énergie déplacée (kWh) | Économie (€) | CO2 évité (kg) |
|---:|---:|---:|---:|---:|---:|
| 0 | 178,9594 | 150,0048 | 117,69 | 5,79092 | 47,076 |
| 1 | 178,5623 | 150,0030 | 113,91 | 5,71186 | 45,564 |
| 2 | 179,6127 | 150,0091 | 119,11 | 5,92072 | 47,644 |
| 3 | 179,5036 | 150,0036 | 118,81 | 5,90000 | 47,524 |
| 4 | 179,6322 | 150,0031 | 119,56 | 5,92582 | 47,824 |
| 5 | 180,0000 | 150,0017 | 120,38 | 5,99966 | 48,152 |
| 6 | 179,1975 | 150,0075 | 117,00 | 5,83800 | 46,800 |

## 4. Modèles de ressources (`backend/models.py`)

### PV

`PV` possède `id` et `capacity_kw`; `flexibilite_disponible()` retourne toujours 0 ([backend/models.py](../backend/models.py#L19-L27)). Le PV n'est donc pas un levier de dispatch. La simulation n'instancie pas `PV`; elle lit plutôt `pv_kw` dans les mesures et le soustrait de la demande. Exemple mesuré : H01 normal jour 0 à midi produit 1,7092 kW; c'est une valeur de mesure, pas une action. `PV.flexibilite_disponible()` donnerait 0 kW. Il n'y a aucune action PV dans `orchestrator_actions`.

### Battery

Attributs : `id`, `capacity_kwh`, `soc` en %, `max_power_kw`, `stress_score` initialisé à 0 et `dispatch_count` initialisé à 0 ([backend/models.py](../backend/models.py#L30-L45)). `flexibilite_disponible()` refuse le dispatch si SOC ≤10 %, puis limite la flexibilité par énergie au-dessus de ce seuil et par puissance max de 5 kW ([backend/models.py](../backend/models.py#L47-L51)). La génération initialise entre 70 et 90 % et borne les mesures à 95 % ([backend/config.py](../backend/config.py#L22-L26)); `decharger()` calcule la baisse de SOC, augmente le stress, mais son plancher d'état est 0 plutôt que 10 % ([backend/models.py](../backend/models.py#L53-L61)). Normalement la flexibilité évite de franchir 10 %; le plancher 0 est donc une protection moins stricte que la règle d'admissibilité.

Exemple reproduit avec les objets construits par la simulation : B004 commence la journée à SOC 70,25 %; avant l'action de 19 h il est encore à 70,25 % avec stress 0 (pas sollicité à 18 h); l'action à 19 h est 2,50 kW; après, son SOC interne devient 45,25 %, et son stress 2,50 kWh. La mesure de base ne devient pas 45,25 %, car ces objets et leurs états ne sont pas persistés.

### EV

Attributs : `id`, capacité 60 kWh, puissance max de charge 7 kW, `connected`, heure d'arrivée, heure de départ, SOC ([backend/models.py](../backend/models.py#L64-L78), paramètres dans [backend/config.py](../backend/config.py#L28-L33)). La flexibilité est nulle si déconnecté; sinon elle dépend de l'énergie restante pour atteindre 90 % et de `max(1, depart-arrivee)`. Un fallback existe quand le SOC atteint 90 % de la cible ([backend/models.py](../backend/models.py#L80-L93)). Dans le chemin simulation, arrivée 18 h et départ 7 h sont codés; comme départ-arrivée est négatif, `remaining_hours` devient 1. Cette simplification ne constitue pas une vraie fenêtre de charge chronologique.

Exemple réel reconstitué : E001 a 27,26 % dans la mesure de départ et reçoit une action `DELAY` de 7,00 kW à 19 h. La méthode `retarder()` augmente pourtant le SOC interne de 27,26 % à 38,9267 % (`7/60*100`), alors qu'une action appelée « report de charge » ne devrait pas physiquement charger le véhicule à cet instant. C'est une incohérence pédagogique du modèle qu'il faut reconnaître.

### HVAC

Attributs : `id`, `current_kw`, `min_kw` et `max_kw`. La flexibilité vaut `max(0, current-min)`; `reduire()` diminue `current_kw` sans passer sous `min_kw` ([backend/models.py](../backend/models.py#L103-L120)). La base courante ne contient **aucune action HVAC** (`device_type` agrégé : seulement battery et ev). Il n'existe donc pas d'exemple HVAC réellement appliqué et persisté. Exemple de méthode, explicitement hypothétique mais construit depuis une ligne réelle : H01 normal/jour 0/19 h mesure `hvac_kw=1,5591538`; avec `min_kw=0,5`, la flexibilité calculée vaut 1,0591538 kW. Un appel fictif `reduire(0,5)` la ferait passer à 1,0591538 kW. Ce n'est pas une action trouvée dans la base.

## 5. L'orchestrateur, pas à pas

### Déclencheur et prévision

`run_simulation()` parcourt chaque scénario, chaque jour et les 24 heures. La demande actuelle est une somme des `grid_import_kw` de l'heure. Si cette somme **ou** la prévision dépasse 150 kW, le déficit devient `max(demande, prévision)-150` ([backend/simulation.py](../backend/simulation.py#L77-L82)). Le prévisionneur, défini dans [backend/forecasting.py](../backend/forecasting.py#L4-L30), fait une moyenne. Au jour 0, il prend la moyenne des maisons de l'heure précédente. Aux jours 1–6, sa branche « jours antérieurs » est vide, car `run_simulation()` lui passe déjà un DataFrame limité au scénario et au jour courant; il tombe donc sur le fallback qui moyenne les maisons du jour courant à l'heure cible. Ce n'est pas une moyenne des jours précédents.

Limite importante et mesurée : cette prévision est une moyenne des lignes individuelles, non une somme quartier. Pour normal/jour 0 pendant l'itération 19 h, `prevoir_demande(..., heure_cible=20)` renvoie 8,9480 kW environ, tandis que la demande réelle agrégée à 19 h est 178,9594 kW. L'agrégation actuelle dépasse donc le seuil et déclenche correctement; le signal de prévision n'est pas à l'échelle du feeder. Pour ce dataset, les dépassements réels sont déjà suffisants pour déclencher.

### Pseudo-code

```text
Pour chaque scénario et jour:
    créer une batterie par maison équipée, un VE par maison équipée, un HVAC par maison
    pour heure de 0 à 23:
        demande = somme des imports des 20 maisons à cette heure
        prévision = moyenne calculée par forecasting.py
        si demande > 150 ou prévision > 150:
            déficit = max(demande, prévision) - 150
            parcourir les batteries, triées par stress puis dispatch_count
            puis parcourir les VE
            puis parcourir les HVAC
            à chaque ressource, arrêter sa boucle si déficit couvert
            enregistrer chaque action
        calculer la demande après actions pour le pic journalier
    enregistrer les KPI
```

Le dispatch complet est dans [backend/orchestrator.py](../backend/orchestrator.py#L8-L97); la création d'une ressource par maison équipée à partir de l'heure 0 est dans [backend/simulation.py](../backend/simulation.py#L40-L57). Le mode appelé par défaut en fin de fichier est `rules`.

### Cas mesuré normal, jour 0, 19 h

- Demande agrégée : **178,9594 kW**.
- Limite : **150 kW**.
- Déficit initial : **28,9594 kW**.
- Actions exactes de la base :

| Ordre | Ressource | Type/action | Puissance enregistrée | Justification enregistrée |
|---:|---|---|---:|---|
| 1 | B004 | batterie / DISCHARGE | 2,50 kW | Batterie B004 choisie (score équité 2.5 kWh cumulés) : -2.5 kW |
| 2 | B005 | batterie / DISCHARGE | 2,50 kW | Batterie B005 choisie (score équité 2.5 kWh cumulés) : -2.5 kW |
| 3 | B006 | batterie / DISCHARGE | 2,50 kW | Batterie B006 choisie (score équité 2.5 kWh cumulés) : -2.5 kW |
| 4 | B007 | batterie / DISCHARGE | 2,50 kW | Batterie B007 choisie (score équité 2.5 kWh cumulés) : -2.5 kW |
| 5 | B003 | batterie / DISCHARGE | 2,50 kW | Batterie B003 choisie (score équité 3.9 kWh cumulés) : -2.5 kW |
| 6 | B002 | batterie / DISCHARGE | 2,50 kW | Batterie B002 choisie (score équité 5.0 kWh cumulés) : -2.5 kW |
| 7 | B001 | batterie / DISCHARGE | 2,07 kW | Batterie B001 choisie (score équité 7.1 kWh cumulés) : -2.1 kW |
| 8 | E001 | VE / DELAY | 7,00 kW | Véhicule E001 reporté : +7.0 kW différé avant départ prévu à 7h |
| 9 | E002 | VE / DELAY | 4,89 kW | Véhicule E002 reporté : +4.9 kW différé avant départ prévu à 7h |

Total arrondi stocké : 28,96 kW, contre 28,9594 kW de déficit initial. L'orchestrateur travaille avec la puissance non arrondie puis arrondit chaque ligne d'action à deux décimales; il retourne un déficit restant nul, mais la somme affichée peut différer de quelques dix-millièmes. Les batteries sont prioritaires; les VE ne sont sollicités qu'après les batteries. Aucun HVAC n'est requis dans ce cas.

### Équité et durée de vie du score

`Battery.stress_score` augmente de `usable_kw * duree_h`; durée par défaut : une heure. Le constructeur le met à zéro. `build_resource_objects()` crée de nouveaux objets pour chaque jour et scénario, donc le score repart de zéro au début de chaque simulation scénario/jour. Il n'est pas stocké dans une colonne SQLite; le texte de justification est persisté et le dashboard affiche un cumul reconstruit depuis les actions du jour. Il n'existe pas de score de stress durable entre les jours.

Exemple sur deux heures consécutives : à 18 h, les actions sont B001 5,00 kW (score 5,0), B002 2,50 kW (2,5) et B003 1,39 kW (1,4). À 19 h, l'ordre commence B004–B007 dont le stress vaut encore zéro; B003 puis B002 puis B001 arrivent plus tard. La séquence réelle est visible dans les justifications enregistrées. Le score modifie donc concrètement l'ordre.

Pourquoi beaucoup d'actions valent 2,50 kW alors que `BATTERY_MAX_POWER_KW=5`? Dans [backend/orchestrator.py](../backend/orchestrator.py#L23-L45), si une batterie a un score supérieur à celui de la batterie courante, la puissance de cette dernière est plafonnée à `max_power_kw * 0.5`, soit 2,5 kW. Une batterie peut recevoir 5 kW lorsque la condition ne s'applique pas (ex. B001 à 18 h). C'est une règle d'équité codée, pas une contrainte physique universelle.

### Ressources insuffisantes et mode LP

Quand les batteries, VE et HVAC sont épuisés, `remaining` peut rester positif; `dispatch()` émet alors un avertissement et retourne ce reste ([backend/orchestrator.py](../backend/orchestrator.py#L92-L97)). La simulation n'enregistre pas de ligne « déficit non couvert » dédiée; elle conserve les actions et un KPI de pic après dispatch. Il ne faut donc pas confondre l'absence d'une action d'échec dans la table avec une preuve que tout scénario est couvert.

`optimizer_lp.py` formule un problème PuLP qui minimise des pénalités batterie 1, VE 2, HVAC 3 sous des bornes de flexibilité ([backend/optimizer_lp.py](../backend/optimizer_lp.py#L8-L50)). L'optimiseur est appelable directement, mais le mode LP de la simulation n'est pas utilisable de bout en bout actuellement : `optimize_deficit()` retourne des dictionnaires ne contenant que `power_kw` et `variable` ([backend/optimizer_lp.py](../backend/optimizer_lp.py#L56-L65)); ensuite `run_simulation()` demande `action["device_id"]`, `action["device_type"]`, `action["action_type"]` et `action["justification"]` ([backend/simulation.py](../backend/simulation.py#L86-L99)). Le chemin échouerait donc au premier résultat LP à persister. Le dashboard et son Sandbox appellent exclusivement `orchestrator.dispatch()`.

Comparaison directe du même déficit normal/jour 0 à 19 h (**28,9594 kW**, objets neufs) :

| Méthode | Allocation calculée | Total | Reste retourné | Remarque |
|---|---|---:|---:|---|
| Règles | 7 batteries (17,07 kW) puis E001 (7,00) et E002 (4,89) | 28,96 kW arrondis | 0 kW | Respecte l'ordre batterie → VE, plus équité. |
| LP appelé directement | B001 à B005 : 5,00 kW chacun; B006 : 3,9594 kW | 28,9594 kW | 0 kW | Minimise le coût dans ses pondérations; n'émet pas les champs d'action requis par la simulation. |

La sortie LP directe ne met pas à jour le SOC/stress des objets : l'optimiseur calcule une allocation mais ne rappelle pas `decharger()`, `retarder()` ou `reduire()`.

## 6. KPI

Pour normal/jour 0, la ligne lue dans SQLite est : `pic_avant=178.9594`, `pic_apres=150.0048`, `energie_deplacee=117.69`, `economie=5.79092`, `co2=47.076`. Les formules sont celles de [backend/simulation.py](../backend/simulation.py#L69-L108); la réduction en pourcentage est calculée dans le dashboard, pas stockée dans la table ([app.py](../app.py#L362-L380)).

| KPI | Formule utilisée | Calcul normal/jour 0 | Interprétation |
|---|---|---|---|
| Pic avant | `max(groupby(heure).sum(grid_import_kw))` | max des sommes horaires = **178,9594 kW** | Plus forte demande horaire agrégée avant actions. |
| Pic après | maximum des demandes horaires après retrait de la somme des actions enregistrées | **150,0048 kW** | Pic résiduel estimé par la simulation après dispatch arrondi. |
| Réduction (%) | `(pic_avant - pic_apres) / pic_avant * 100` (calcul `app.py`) | `(178,9594 - 150,0048) / 178,9594 × 100 = 16,1794 %`, affiché 16,2 % | Part du pic initial retranchée selon les KPI. |
| Énergie déplacée | `sum(abs(action["power_kw"]) for action in daily_actions)` | **117,69 kWh** dans la convention d'une heure par action | Somme quotidienne des actions, pas une intégration de courbe de puissance mesurée. |
| Économie estimée | `(daily_peak_before - daily_peak_after) * PRIX_ELECTRICITE_EUR_KWH` | `(178,9594 - 150,0048) × 0,20 =` **5,79092 €** | Estimation monétaire fondée sur une réduction de puissance du pic. |
| CO2 évité | `energie_deplacee * FACTEUR_EMISSION_CO2_KG_KWH` | `117,69 × 0,4 =` **47,076 kg** | Estimation par facteur constant. |

Le prix `0.20 €/kWh` et le facteur CO2 `0.4 kg/kWh` sont définis dans [backend/config.py](../backend/config.py#L35-L36); ce sont des hypothèses pédagogiques, pas des tarifs/émissions issus d'une facture ou d'un fournisseur réel. La formule d'économie est discutable : elle applique un prix par kWh à une différence de pic en kW, sans durée ni tarif de puissance. Elle ne calcule donc pas une facture économisée au sens comptable.

L'énergie de 117,69 est calculée à partir de puissances d'action arrondies et assimilées à des actions d'une heure. Le modèle ne suit pas le report d'une charge VE dans une heure ultérieure et ne calcule pas une courbe énergétique complète de report.

## 7. Mode Sandbox

Le Sandbox est une simulation instantanée « que se passerait-il si je changeais la limite? » à partir des mesures sélectionnées. Ce n'est ni une commande réseau ni une écriture de scénario dans SQLite.

Dans [app.py](../app.py#L139-L207), `run_sandbox()` reçoit le DataFrame chargé pour le scénario/jour, somme `grid_import_kw` par heure, calcule `max(0, demande-limite)`, crée des ressources modèles et appelle la fonction importée `dispatch()`. Les mesures et actions originales ne sont pas écrites; seules les actions et états en mémoire sont modifiés. Le Sandbox de l'application parcourt toute la journée, et garde les SOC batterie/VE de son calcul dans l'objet pendant la boucle des heures.

Voici les sorties du helper réel de l'application pour normal/jour 0, extraites à 19 h. Le reste d'action affiché est arrondi; `dispatch()` peut retourner zéro sur les valeurs non arrondies.

### Limite 130 kW

Demande à 19 h : 178,9594 kW; déficit théorique `178,9594-130 = 48,9594 kW`. Comme les heures précédentes ont déjà consommé des ressources dans le Sandbox plein jour, les actions à 19 h sont : B007 2,04; B002 1,69; B003 2,30; B004 1,02; B005 2,44; B006 2,31; E001–E005 7,00 chacun; E006 2,15 kW. Somme des puissances arrondies : 48,95 kW; reste renvoyé : 0. Le plan complet de la journée a 54 actions et sa somme de puissances affichées est 257,18 kW-créneaux.

### Limite 150 kW

Déficit à 19 h : 28,9594 kW. Actions : B004–B007 2,50 kW chacun; B003 2,50; B002 2,50; B001 2,07; E001 7,00; E002 4,89 kW. Somme affichée 28,96 kW; reste renvoyé 0. Le plan complet du jour a 34 actions et totalise 117,69 kW-créneaux.

### Limite 170 kW

Déficit à 19 h : 8,9594 kW. Actions : B001 5,00; B002 2,50; B003 1,46 kW. Somme affichée 8,96 kW; reste renvoyé 0. Le plan complet du jour a 9 actions et totalise 20,68 kW-créneaux.

Ces résultats montrent la sensibilité du dispatch à la limite configurée et à l'état simulé des objets. Ils ne prouvent ni que les actions sont électriquement réalisables sur un réseau physique, ni qu'elles respectent des contrats clients, ni que la batterie/VE récupère correctement son énergie ultérieurement. La somme sur plusieurs heures n'est pas une puissance instantanée à un seul moment.

## 8. Dashboard, onglet par onglet

Les filtres scénario/jour se trouvent dans la sidebar. La base contient les trois scénarios et les sept index journaliers.

### Vue d'ensemble

Affiche le nombre nommé « DER modélisées », l'estimation PV, capacité batterie, VE, demande au pic, réduction et économie. Les valeurs sont alimentées par `measurements`, `kpi_results` et les constantes de config ([app.py](../app.py#L350-L383)). Pour normal/jour 0, la demande agrégée affichée est 178,9594 kW, capacité batterie totale affichée 70 kWh, 8 VE; le KPI donne une réduction de 16,2 % et 5,79 €.

Précision à dire : la métrique DER est calculée comme `13 + 7 + 8 + 20 = 48`; elle additionne les ressources et les maisons, donc ce n'est pas le nombre de DER distinctes au sens strict. La « puissance PV max observée » est une somme de maxima observés par maison, pas une puissance nominale certifiée.

**À l'oral :** « Je sélectionne le scénario et le jour à gauche; ces chiffres viennent de SQLite. La demande est la somme des maisons à l'heure de pointe; l'économie affichée est un indicateur pédagogique calculé par la formule du code, pas une facture. »

### Parc de ressources

Quatre sous-onglets PV, Batteries, VE, HVAC. Les PV viennent des maxima observés par maison; les batteries affichent SOC de fin de journée et une somme des actions enregistrées pour reconstituer un stress; les VE affichent SOC/connexion et l'heure de départ configurée; HVAC affiche le dernier `hvac_kw` du jour ([app.py](../app.py#L390-L428)). Les tables/agrégats viennent de `measurements` et `orchestrator_actions`.

**À l'oral :** « Ce parc est construit à partir des colonnes mesurées; les zéros de SOC identifient les maisons sans batterie ou sans VE. Le SOC dessiné est celui des mesures synthétiques, tandis que le stress vient du journal d'actions et non d'une colonne persistante de stress. »

### Suivi réseau

Affiche la somme horaire des imports des maisons et la limite pointillée de 150 kW; une zone corail signale les dépassements. Le DataFrame est agrégé par `hourly_demand()` et le graphe par `build_grid_figure()` ([app.py](../app.py#L107-L113), [app.py](../app.py#L232-L288)). Normal/jour 0 culmine à 178,9594 kW à 19 h; six heures du jour dépassent 150 kW.

**À l'oral :** « Chaque point est la somme des 20 maisons à l'heure concernée, et non leur moyenne. La zone au-dessus de la limite montre les heures qui déclenchent un besoin de flexibilité. »

### Orchestrateur

Le haut de l'onglet est le Sandbox : slider de limite, résumé et nouveau plan. Le journal en dessous lit les actions persistées filtrées par scénario/jour, avec heure, type, ressource et justification ([app.py](../app.py#L430-L480)). Normal/jour 0 a 34 lignes d'action en base réparties de 18 h à 23 h.

**À l'oral :** « Le journal est le résultat enregistré de la simulation. Le slider lance un recalcul séparé en mémoire; il ne remplace ni les mesures ni le journal sauvegardé. »

### Résultats

Les cartes pic avant/après/réduction lisent `kpi_results`; le graphique interroge les mesures et calcule le maximum horaire agrégé de chaque scénario; le tableau final relit les KPI sélectionnés ([app.py](../app.py#L480-L550)). Le graphe scénario est une agrégation sur tous les jours, tandis que la carte est liée au jour sélectionné.

**À l'oral :** « Je compare le pic brut avec le pic estimé après actions, puis les maxima des scénarios. Je rappelle que les KPI sont des indicateurs synthétiques et que l'économie est calculée à partir du pic, pas d'une facture. »

## 9. Guide de démonstration de 8 à 10 minutes

| Temps | Action dans l'interface | Valeurs réelles à montrer | Phrase clé |
|---|---|---|---|
| 0:00–0:45 | Présenter le titre et le contexte. | 20 maisons, trois scénarios, limite 150 kW dans config. | « C'est un démonstrateur logiciel académique, aucune installation réelle n'est pilotée. » |
| 0:45–1:30 | Montrer la sidebar et sélectionner normal, jour 0. | 178,9594 kW au pic; 70 kWh batterie configurée; 8 VE. | « Les filtres pilotent toutes les vues et les mesures viennent de SQLite. » |
| 1:30–2:30 | Vue d'ensemble. | 16,2 % de réduction KPI, économie estimée 5,79092 €. | « L'économie est une formule pédagogique basée sur la variation du pic. » |
| 2:30–3:30 | Parc, sous-onglets batteries et VE. | H01 jour 0 à 19 h: battery SOC 83,59 %, EV SOC 27,26 %, connecté=1. | « Les SOC sont des valeurs synthétiques enregistrées, pas des lectures télémétriques. » |
| 3:30–4:30 | Suivi réseau. | Somme 19 h = 178,9594 kW; limite 150; six heures au-dessus du seuil. | « Le feeder voit la somme des 20 appels simultanés. » |
| 4:30–6:00 | Journal Orchestrateur normal/jour 0, 19 h. | 7 batteries et 2 VE; actions affichées totalisent 28,96 kW. | « Les règles respectent l'ordre batterie, puis VE, et la justification expose le score. » |
| 6:00–7:30 | Sandbox; essayer 130, 150, 170 kW. | À 19 h, déficit 48,9594 / 28,9594 / 8,9594 kW; plans respectifs 12 / 9 / 3 actions dans l'état séquentiel plein jour. | « Le calcul est what-if et isolé; le plan dépend de la limite et des états accumulés dans la journée. » |
| 7:30–8:30 | Résultats et scénarios. | Pics max: normal 180,0000; nuageux 180,0000; canicule 201,2490 kW. | « Nuageux réduit bien la production PV à 18 h, mais le maximum commun arrive à 19 h sans PV. » |
| 8:30–9:30 | Conclure sur les limites. | Données synthétiques, limites du LP et unités de prévision. | « Le résultat démontre un prototype de dispatch; il reste à valider le modèle et à corriger plusieurs simplifications avant un usage réel. » |

Le nombre d'actions à 19 h indiqué pour la limite 130 est 12 dans le Sandbox complet : six batteries et six VE. À 150 il y en a neuf et à 170 trois. Les puissances affichées restent arrondies.

## 10. Préparation aux questions

1. **Pourquoi des données synthétiques et pas réelles?** Le dépôt ne charge aucune donnée externe; le générateur crée les profils à partir de paramètres codés. Cela permet un exemple reproductible mais ne valide pas le comportement d'un vrai quartier.
2. **Comment savez-vous que votre algorithme est bon?** Les six tests couvrent des comportements unitaires (priorité, équité, déficit non couvert). Ils ne prouvent pas l'optimalité, la robustesse météo ou la validité réseau.
3. **En quoi le score d'équité apporte-t-il quelque chose?** Il trie les batteries par stress et peut plafonner leur puissance à la moitié quand une autre est plus sollicitée; à 19 h, les scores des justifications diffèrent. Il ne modélise pas la dégradation réelle et repart à zéro par scénario/jour.
4. **Pourquoi calibrer vers 180 kW, n'est-ce pas de la triche?** C'est une mise à l'échelle explicite pour illustrer une pointe proche de la limite 150 kW; le facteur 1,4849 est calculé dans `calibration.py`. Ce n'est pas un résultat de mesure réelle et il faut l'annoncer.
5. **Que se passe-t-il si les ressources ne suffisent pas?** `dispatch()` laisse `remaining > 0`, écrit un warning puis le retourne. Il n'y a pas de ligne dédiée « déficit non couvert » dans la base de la simulation.
6. **Qu'est-ce qui distingue le projet d'un simple script?** Il a un générateur, une base SQLite à trois tables métier, des modèles de ressources, deux algorithmes d'allocation (dont le LP est actuellement incompatible avec la persistance), un dashboard Streamlit et des tests. Cela reste un prototype local monoprocessus, sans API ni matériel.
7. **Pourquoi le pic nuageux est-il identique au normal?** Les deux culminent à 19 h quand `pv_kw=0`; à 18 h, nuageux est plus élevé (172,6998 contre 158,8901 kW) et produit moins de PV (8,9361 contre 22,7457 kW).
8. **Pourquoi le forecast à 19 h vaut-il environ 8,95 kW alors que la demande est 178,96 kW?** `prevoir_demande()` prend une moyenne par ligne/maison, non la somme quartier. C'est une différence d'échelle connue; le dispatch est tout de même déclenché par la demande réelle agrégée.
9. **Les batteries respectent-elles toujours un SOC minimum de 10 %?** `flexibilite_disponible()` refuse les batteries ≤10 % et calcule l'énergie au-dessus de 10; `decharger()` borne cependant son SOC à 0 %. En fonctionnement ordinaire le calcul de flexibilité protège le seuil, mais la borne dans la méthode n'est pas homogène.
10. **Une action VE `DELAY` retarde-t-elle vraiment la charge?** Pas fidèlement : `retarder()` augmente le SOC comme si l'énergie avait été reçue. C'est une simplification incohérente avec le nom de l'action.
11. **Où se trouve l'heure réelle d'arrivée et de départ de chaque VE?** Le générateur calcule ces variables, mais ne les stocke pas. La simulation et le dashboard utilisent des heures codées/configurées (18 h et 7 h).
12. **Pourquoi les KPI pic après restent-ils légèrement au-dessus de 150 kW?** Les actions sont arrondies à deux décimales avant leur persistance; la somme retranchée du total horaire peut donc laisser un résidu de quelques millièmes.
13. **L'économie de 5,79 € correspond-elle à une facture?** Non. Elle est la différence de pics en kW multipliée par 0,20 €/kWh, sans intégrer une durée ou un tarif de puissance. C'est un indicateur pédagogique, dimensionnellement discutable.
14. **Peut-on utiliser le mode LP aujourd'hui?** `optimize_deficit()` fonctionne en appel direct et alloue 28,9594 kW pour le cas mesuré. Mais `run_simulation(mode="lp")` devrait échouer à la persistance, car le dictionnaire LP manque `device_id`, `device_type`, `action_type` et `justification`.
15. **Que représentent les émissions CO2 évitées?** Le code multiplie l'énergie déplacée par 0,4 kg/kWh. C'est une hypothèse constante, pas une analyse de cycle de vie ni un facteur local mesuré.

## 11. Glossaire

- **DER** : ressource énergétique distribuée, par exemple PV, batterie ou charge pilotable, située près des consommateurs.
- **iDER** : nom du projet de démonstration d'orchestration de DER; le dépôt n'implémente pas un standard industriel portant cette abréviation.
- **DERMS** : système logiciel de gestion et coordination de ressources distribuées; ce projet en est seulement une maquette académique locale.
- **VPP** : centrale électrique virtuelle qui agrège des ressources distribuées; le prototype n'est pas raccordé à un marché ni à un réseau réel.
- **BTM** : « behind the meter », ressources et consommations du côté client du compteur.
- **SOC** : état de charge d'une batterie ou d'un VE, exprimé ici en pourcentage.
- **kW** : puissance instantanée; **kWh** : énergie, puissance intégrée sur une durée.
- **Dispatch** : choix d'actions sur les ressources pour réduire un déficit calculé.
- **Déficit** : différence positive entre la demande retenue par le simulateur et la limite réseau.
- **Pic** : maximum des demandes horaires agrégées sur une journée ou une période précisée.
- **Flexibilité** : puissance que le modèle autorise à décharger, reporter ou réduire sous ses contraintes.
- **Demand response** : adaptation de la consommation en réponse à une contrainte ou un signal réseau; ici elle est seulement simulée.
- **`stress_score`** : somme interne des décharges batterie exprimées en puissance × durée; état en mémoire du modèle.
- **Mode what-if** : simulation hypothétique avec paramètres changés, sans effet enregistré sur la base.
- **Calibration** : mise à l'échelle des charges par un facteur calculé pour atteindre un niveau cible de démonstration.

## 12. Vérification finale

Les valeurs citées ont été lues depuis `ider.db` ou recalculées à partir des requêtes indiquées; les paramètres et règles sont cités depuis les fichiers Python correspondants. La volumétrie vérifiée est de 10 080 mesures, 908 actions et 21 KPI, avec 3 360 mesures par scénario. La base ne contient aucune valeur NULL dans les colonnes de mesures.

Points non vérifiables ou fragiles à défendre explicitement :

- `DATE_DEBUT` existe, mais n'est pas utilisée; les jours sont des index, pas des dates civiles.
- L'arrivée/départ VE générés ne sont ni persistés ni utilisés de façon dynamique; dans `EV`, le report de charge augmente le SOC.
- Le prévisionneur moyenne des lignes maisons, alors que la limite 150 kW s'applique à une somme de quartier.
- `stress_score` est volatil et non persistant; le dashboard le reconstruit par somme d'actions, ce qui n'est pas le même état interne exact.
- Le score batterie ne perdure pas entre jours/scénarios, et les SOC modifiés par la simulation ne sont pas réécrits dans `measurements`.
- La table action courante ne comporte aucune action HVAC; l'exemple HVAC de la partie 4 est une démonstration de méthode, pas un événement réel enregistré.
- Le mode LP direct calcule une allocation, mais son format de sortie n'est pas compatible avec l'enregistrement par `run_simulation()` et ses ressources ne sont pas mutées.
- Les KPI d'économie et de CO2 reposent sur des facteurs fixes pédagogiques; l'économie pic × €/kWh n'est pas une facture calculée physiquement.
- La calibration 180 kW est un réglage de démonstration commun aux scénarios et ne constitue pas une validation statistique.
- Le dashboard compte 48 « DER modélisées » en additionnant maisons et nombres de ressources; cette métrique n'est pas un décompte de ressources distinctes.
