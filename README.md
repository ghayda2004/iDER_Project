# iDER — Orchestration énergétique distribuée

## Table des matières

- [1. Résumé et positionnement](#1-résumé-et-positionnement)
- [2. Architecture technique](#2-architecture-technique)
- [3. Structure du dépôt](#3-structure-du-dépôt)
- [4. Fonctionnement de l'orchestrateur](#4-fonctionnement-de-lorchestrateur)
- [5. Installation](#5-installation)
- [6. Reproduire le travail depuis zéro](#6-reproduire-le-travail-depuis-zéro)
- [7. Exécuter les tests](#7-exécuter-les-tests)
- [8. Scénarios et résultats mesurés](#8-scénarios-et-résultats-mesurés)
- [9. KPI et méthodologie](#9-kpi-et-méthodologie)
- [10. Limites connues](#10-limites-connues)
- [11. Historique des changements majeurs](#11-historique-des-changements-majeurs)
- [12. Équipe et répartition des rôles](#12-équipe-et-répartition-des-rôles)

## 1. Résumé et positionnement

iDER simule un quartier résidentiel de 20 maisons et l'orchestration de ressources énergétiques distribuées (DER) : photovoltaïque, batteries, véhicules électriques et charges HVAC pilotables. Les profils sont synthétiques et enregistrés dans SQLite; la simulation calcule des actions pour répondre aux pointes de demande face à une limite réseau configurée à 150 kW.

En termes simples, chaque maison reçoit une charge de base et une production PV éventuelle. Le programme calcule son import réseau net; il additionne ensuite les 20 maisons pour connaître la demande du quartier à chaque heure. Si le total dépasse la limite, le moteur tente de réduire le déficit en sollicitant des ressources flexibles. Streamlit permet de consulter les données et d'essayer une autre limite sans enregistrer ce scénario hypothétique.

Ce projet est un proof-of-concept académique réalisé dans le contexte du cours « Digital Grid and Business Value ». Il ne pilote aucun matériel physique réel, n'est raccordé à aucun réseau réel et ne doit pas être utilisé comme système de contrôle industriel.

## 2. Architecture technique

L'application Streamlit lit directement SQLite et importe les modèles et la fonction d'orchestration Python. La génération et la simulation s'exécutent par scripts. Il n'y a pas d'API REST, pas de service de base de données séparé et pas de Docker. Par rapport au prototype HTML/JavaScript, cette architecture supprime la couche d'export et de relecture d'un fichier JSON intermédiaire.

```text
python backend/generate_dataset.py
                |
                v
        SQLite: measurements <----- app.py (Streamlit)
                |                         |      |
                v                         |      +--> models.py
python backend/simulation.py              +--------> database.py
        |                                  +--------> orchestrator.py (Sandbox)
        +--> forecasting.py               +--------> Plotly charts
        +--> orchestrator.py
        +--> optimizer_lp.py (mode LP)
        |
        +--> SQLite: orchestrator_actions + kpi_results
```

| Dépendance (`requirements.txt`) | Rôle réel dans le dépôt | Justification |
|---|---|---|
| `pandas` | Tableaux de mesures, filtrage et agrégations horaires | Les données et les calculs de séries temporelles sont manipulés sous forme de DataFrame. |
| `numpy` | Calculs numériques dans le générateur et la calibration | Sert notamment aux valeurs synthétiques, bornes et opérations vectorisées. |
| `pulp` | Optimisation linéaire optionnelle | `optimizer_lp.py` expose une alternative au dispatch par règles. |
| `pytest` | Tests de l'orchestrateur | Exécute les tests automatisés de la logique de ressources et du dispatch. |
| `streamlit` | Interface interactive | Rend le dashboard Python et ses contrôles de scénario, jour et Sandbox. |
| `plotly` | Graphiques interactifs | Produit le suivi horaire de la demande et la comparaison des pics par scénario. |

Le thème Streamlit est défini dans `.streamlit/config.toml`. La persistance est locale dans `ider.db`; l'interface ne génère aucun export JSON.

### Parcours d'une mesure

```text
config.py + tirages aléatoires
              |
              v
generate_dataset.py -> calibration.py -> table measurements (SQLite)
                                                    |
                                                    v
simulation.py -> forecasting.py -> orchestrator.py -> actions + KPI (SQLite)
        |                                      ^
        +---------------- models.py ----------+
                                                    |
                                                    v
                                      app.py (Streamlit) -> navigateur
                                      lit la base; n'exporte pas de JSON
```

Concrètement, une ligne comme `normal, 0, 19, H01` représente la mesure de la maison H01 à 19 h du jour index 0 dans le scénario normal. `generate_dataset.py` calcule les champs de cette ligne, `database.py` l'écrit, `simulation.py` lit les 20 lignes de la même heure pour calculer le total du quartier, puis `app.py` les agrège et les affiche.

## 3. Structure du dépôt

Arborescence du projet relevée dans le workspace (les environnements virtuels, métadonnées Git et caches Python/test sont omis) :

```text
.
├── .streamlit/
│   └── config.toml                 # couleurs et thème Streamlit
├── .vscode/
│   └── settings.json               # réglages locaux de l'éditeur
├── app.py                          # dashboard, lectures SQLite, graphiques et Sandbox
├── backend/
│   ├── __init__.py                 # marque le package Python backend
│   ├── calibration.py              # calibre la charge sur un scénario de référence
│   ├── config.py                   # constantes du quartier, ressources et scénarios
│   ├── database.py                 # schéma SQLite et opérations de lecture/écriture
│   ├── forecasting.py              # estimation de demande à l'heure cible
│   ├── generate_dataset.py         # génération des profils et mesures des 3 scénarios
│   ├── models.py                   # modèles PV, batterie, VE et HVAC
│   ├── optimizer_lp.py             # optimisation linéaire optionnelle du déficit
│   ├── orchestrator.py             # dispatch batterie, VE puis HVAC avec équité
│   └── simulation.py               # boucle jour/heure, actions et KPI persistés
├── docs/
│   ├── ai_usage_log.md              # journal des changements assistés par IA
│   └── architecture.md              # flux d'architecture courant
├── tests/
│   └── test_orchestrator.py         # six tests du dispatch et des ressources
├── ider.db                          # données locales générées par le pipeline
├── README.md                        # documentation du projet
├── requirements.txt                 # dépendances Python
└── temp_check.py                    # script local de vérification SQLite
```

### Fichiers Python : responsabilité observée

| Fichier | Rôle observé |
|---|---|
| `backend/config.py` | Définit les tailles de parc, limites, profils de charge, facteurs météo, paramètres DER, prix et facteur CO2. |
| `backend/database.py` | Crée les tables `measurements`, `orchestrator_actions` et `kpi_results`; fournit les fonctions SQLite de lecture, insertion et purge des mesures. |
| `backend/models.py` | Implémente les capacités de flexibilité, décharge batterie, report VE et réduction HVAC. |
| `backend/generate_dataset.py` | Construit les profils synthétiques, les calibre, applique les facteurs météo et enregistre 10 080 mesures. |
| `backend/forecasting.py` | Calcule une prévision à partir de l'historique fourni. |
| `backend/orchestrator.py` | Mobilise successivement batteries, VE puis HVAC jusqu'à couverture du déficit ou épuisement des ressources. |
| `backend/optimizer_lp.py` | Résout une variante d'optimisation linéaire via PuLP. |
| `backend/calibration.py` | Calcule un facteur global d'échelle depuis le scénario de référence et l'applique aux colonnes de charge. |
| `backend/simulation.py` | Charge les mesures scénario/jour, construit un objet par ressource et persiste actions et KPI de simulation. |
| `app.py` | Affiche les vues Streamlit, interroge SQLite, construit les graphiques et appelle `orchestrator.dispatch()` pour le Sandbox. |
| `temp_check.py` | Script temporaire présent à la racine pour inspecter quelques valeurs et lignes SQLite. |

### Types de données à connaître

Il y a trois sortes de données principales dans le moteur :

- **Catégories** : `scenario` (`normal`, `nuageux`, `canicule`), `house_id` (`H01`…`H20`), `device_type` (`battery`, `ev`, `hvac`) et `action_type` (`DISCHARGE`, `DELAY`, `REDUCE`). Elles identifient le contexte ou le type de ressource.
- **Indices temporels entiers** : `jour` va de 0 à 6 et `heure` de 0 à 23. Ce sont des index de simulation, pas des dates calendaires. La configuration déclare `DATE_DEBUT`, mais aucune date n'est écrite dans les mesures.
- **Mesures numériques** : les champs suffixés `_kw` sont des puissances en kW; les champs `_soc` sont des pourcentages de charge; `power_kw` est la puissance associée à une action. `ev_connected` est un entier 0/1 utilisé comme booléen. Les colonnes KPI nomment explicitement les valeurs calculées.

La table centrale est `measurements` : elle contient une ligne par scénario, jour, heure et maison. Ses colonnes sont `id` (clé SQLite), `scenario`, `jour`, `heure`, `house_id`, `base_load_kw`, `pv_kw`, `battery_soc`, `ev_soc`, `ev_connected`, `hvac_kw` et `grid_import_kw`. Par exemple, la ligne actuelle de H01, normal/jour 0/19 h, porte `base_load_kw=6.7817`, `pv_kw=0`, `hvac_kw=1.5592` et `grid_import_kw=8.3409` kW. Elle signifie que cette maison importe 8,3409 kW à cet instant dans le modèle.

Les mesures observées vont de 0,9097 à 8,3161 kW pour `base_load_kw`, de 0 à 3,3125 kW pour `pv_kw`, de 0 à 93,46 % pour `battery_soc`, de 0 à 50,71 % pour `ev_soc`, de 0 à 1 pour `ev_connected`, de 0,9652 à 3,2074 kW pour `hvac_kw` et de 1,696 à 11,337 kW pour `grid_import_kw`. Les zéros de SOC indiquent souvent qu'une maison n'a pas cette ressource. Ces plages sont celles de la base locale auditée et changeront si le dataset est régénéré avec d'autres paramètres ou un autre seed.

La relation de demande, telle qu'implémentée, est :

```text
grid_import_kw = max(0, base_load_kw + hvac_kw - pv_kw)
```

Ainsi, le PV réduit l'import, mais le code empêche une valeur négative : l'export d'un éventuel surplus vers le réseau n'est pas modélisé. Au niveau quartier, on **somme** les 20 imports de la même heure. Par exemple, normal/jour 0/19 h vaut 178,9594 kW au total; la moyenne des 20 maisons est 8,94797 kW, qui ne représente pas le courant total appelé au feeder.

Les deux autres tables métier utilisent ces types de champs :

| Table / champ | Type SQLite | Sens |
|---|---|---|
| `orchestrator_actions.id` | INTEGER | Clé technique de la ligne. |
| `orchestrator_actions.scenario`, `device_id`, `device_type`, `action_type`, `justification` | TEXT | Scénario, ressource concernée, catégorie et nom de l'action, explication textuelle. |
| `orchestrator_actions.jour`, `heure` | INTEGER | Index du jour et heure à laquelle le moteur a déclenché l'action. |
| `orchestrator_actions.power_kw` | REAL | Puissance de l'action en kW; les règles arrondissent les valeurs enregistrées à deux décimales. |
| `kpi_results.scenario` | TEXT | Scénario auquel la journée appartient. |
| `kpi_results.jour` | INTEGER | Index du jour simulé, 0 à 6. |
| `kpi_results.pic_avant_kw`, `pic_apres_kw` | REAL | Demande maximale agrégée sur une heure de la journée, avant et après dispatch, en kW. |
| `kpi_results.energie_deplacee_kwh` | REAL | Somme des puissances d'action interprétée comme énergie sur des créneaux d'une heure. |
| `kpi_results.economie_estimee_eur` | REAL | Indicateur monétaire calculé, en euros. |
| `kpi_results.co2_evite_kg` | REAL | Estimation par le facteur d'émission fixe, en kg. |

Les valeurs d'état des objets en mémoire (`stress_score`, nombre d'appels au dispatch, SOC modifié par une action) ne sont pas toutes des colonnes SQLite. En particulier, `stress_score` peut être reconstruit approximativement depuis les actions, mais il n'est pas stocké comme une mesure d'état dédiée.

## 4. Fonctionnement de l'orchestrateur

### De la mesure à la décision

Le moteur de simulation suit ce cycle pour chaque scénario, jour et heure :

1. Charger les 480 lignes du scénario/jour (20 maisons × 24 heures).
2. Additionner `grid_import_kw` pour les 20 maisons de l'heure traitée. Cette somme, et non la moyenne, est la demande réelle du quartier.
3. Appeler `prevoir_demande()` pour obtenir une valeur de prévision.
4. Si la demande réelle **ou** la prévision dépasse `GRID_LIMIT_KW = 150`, calculer un déficit : `max(demande, prévision) - 150`.
5. Appeler le dispatch en mode règles (comportement par défaut) ou le solveur LP si le mode vaut `lp`.
6. Enregistrer les actions et calculer les KPI de fin de journée.

Cette séquence se trouve dans `run_simulation()` dans [backend/simulation.py](backend/simulation.py#L60-L116). Attention à la prévision actuelle : le simulateur lui passe déjà les mesures d'un seul jour. Au jour 0, le code prend une moyenne des maisons à l'heure précédente; aux jours suivants, la recherche des jours antérieurs est vide et la fonction retombe sur une moyenne de maisons du jour courant. Ce n'est donc pas une véritable prévision apprise à partir d'une série de jours précédents, et sa moyenne par maison n'est pas à l'échelle du feeder (150 kW quartier).

### Ordre de mérite

Le dispatch par règles suit cet ordre de mérite :

1. Batteries : décharge dans l'ordre du score de stress puis du nombre de dispatchs; lorsqu'un score plus élevé existe, la décharge de la batterie courante peut être plafonnée à la moitié de sa puissance maximale.
2. Véhicules électriques : report de charge selon la connexion et la flexibilité déclarée par l'objet VE.
3. HVAC : réduction de consommation jusqu'à la flexibilité calculée pour chaque objet HVAC.

Dans `orchestrator.dispatch()`, chaque catégorie est une boucle sur la liste fournie. Une boucle ne s'arrête que si le déficit restant est nul ou négatif, ou quand sa liste est épuisée; aucun plafond « un équipement par catégorie » n'est présent. La simulation construit 7 batteries, 8 VE et 20 HVAC à partir de la première heure du jour, une ressource par maison équipée.

Le score d'équité de chaque batterie correspond au cumul de puissance déchargée en kW sur des créneaux d'une heure, interprété ici comme une énergie cumulée en kWh. Les justifications enregistrées contiennent ce score au moment de l'action.

Le Sandbox de l'onglet Orchestrateur rappelle la même fonction `dispatch()` avec une limite choisie par l'utilisateur. C'est un calcul what-if en mémoire; il n'écrit pas ses actions dans SQLite.

**Exemple mesuré — normal, jour 0, 19 h :** la demande agrégée est **178,9594 kW** et la limite est **150 kW**; le déficit avant dispatch est donc 28,9594 kW. Le journal de la base contient neuf actions : sept batteries pour 17,07 kW au total, puis deux VE pour 11,89 kW. Les valeurs stockées, arrondies à deux décimales, totalisent **28,96 kW**. Cette séquence illustre les priorités, mais le SOC des objets de simulation n'est pas réécrit dans la table des mesures.

### Pourquoi plusieurs batteries donnent 2,5 kW

Chaque batterie a une puissance maximale configurée de 5 kW. Toutefois, si une autre batterie a un `stress_score` plus élevé que celle que l'on examine, `dispatch()` limite la puissance de la batterie courante à `max_power_kw * 0.5`, soit 2,5 kW. C'est une règle de partage codée pour l'équité, pas une limite matérielle générale. Quand cette condition ne s'applique pas, une batterie peut fournir jusqu'à 5 kW, dans les limites de son SOC et du déficit.

### Quand les ressources ne suffisent pas

Le dispatch parcourt les batteries, les VE puis le HVAC. Si les listes sont épuisées alors que le déficit reste positif, il émet un message `Déficit réseau non couvert` et retourne le résidu. La table des actions ne contient pas de ligne particulière pour ce résidu; il faut examiner l'avertissement ou le résultat retourné, et ne pas conclure que toutes les pointes sont nécessairement couvertes.

### Variante LP : différence et état réel

`optimizer_lp.py` construit un problème linéaire PuLP : il donne un coût unitaire de 1 aux batteries, 2 aux VE et 3 au HVAC, puis cherche des allocations qui couvrent le déficit sous les limites de flexibilité. C'est une méthode de calcul différente du dispatch glouton par ordre de mérite.

Le solveur est appelable directement, mais son intégration complète à `run_simulation(mode="lp")` n'est pas terminée : il retourne des actions avec `power_kw` et `variable`, tandis que la persistance de simulation attend `device_id`, `device_type`, `action_type` et `justification`. Le dashboard et le Sandbox utilisent actuellement les règles, pas le LP. Cette variante doit donc être présentée comme un module expérimental testable isolément, non comme un mode de dashboard prêt à l'emploi.

Sur le même déficit normal/jour 0/19 h de 28,9594 kW, le dispatch règles stocke environ 28,96 kW répartis entre sept batteries et deux VE. Un appel LP direct avec objets neufs alloue 5 kW à cinq batteries puis 3,9594 kW à une sixième, soit 28,9594 kW et aucun VE. Les deux résultats respectent leurs contraintes de puissance dans ce cas, mais les sorties ne sont pas directement équivalentes : le LP ne mute pas les SOC/stress des objets et ne produit pas les champs de persistance attendus.

## 5. Installation

Environnement vérifié : Python 3.11.9 sous Windows, confirmé par `python --version`. Créer et activer un environnement virtuel depuis la racine :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Contenu exact de `requirements.txt` au moment de l'audit :

```text
pandas
numpy
pulp
pytest
streamlit
plotly
```

## 6. Reproduire le travail depuis zéro

Les commandes validées sont exécutées depuis la racine du projet. Le générateur purge les lignes de mesures existantes avant de les regénérer; la simulation lit ces mesures et écrit actions/KPI. Enfin, Streamlit lit directement la base :

```powershell
python backend/generate_dataset.py
python backend/simulation.py
streamlit run app.py
```

Le serveur Streamlit affiche l'URL locale dans le terminal. L'exécution auditée a utilisé `http://localhost:8503` parce que les ports précédents étaient déjà occupés; le port par défaut est 8501 lorsqu'il est libre.

Pour exécuter seulement les tests :

```powershell
python -m pytest tests/ -v
```

## 7. Exécuter les tests

Validation exécutée après les corrections KPI et inventaire : `6 passed`. Les tests individuels vérifient :

| Test | Vérification |
|---|---|
| `test_pas_de_pic_pas_action` | Aucun dispatch n'est produit lorsque la liste de ressources est vide; le déficit reste signalé. |
| `test_batterie_disponible_utilisee_en_priorite` | Une batterie disponible est choisie avant les autres catégories. |
| `test_batterie_soc_faible_non_utilisee` | Une batterie au SOC minimal ne propose pas de flexibilité. |
| `test_ev_proche_depart_non_retarde_excessivement` | Un VE connecté près de son départ conserve une flexibilité positive bornée. |
| `test_equite_alterne_les_batteries` | Le score de stress permet de prioriser ensuite la batterie la moins sollicitée. |
| `test_deficit_non_couvert_est_signale` | Un déficit impossible à couvrir reste positif et est signalé. |

## 8. Scénarios et résultats mesurés

Les nombres ci-dessous viennent d'une interrogation directe de `kpi_results` après une génération et une simulation propres, avec le calcul de pic corrigé. Chaque cellule contient `pic_avant_kw` en kW pour le scénario et le jour indiqués.

| Jour | Normal (kW) | Nuageux (kW) | Canicule (kW) |
|---:|---:|---:|---:|
| 0 | 178.9594 | 178.9594 | 200.2085 |
| 1 | 178.5623 | 178.5623 | 199.8116 |
| 2 | 179.6127 | 179.6127 | 200.8617 |
| 3 | 179.5036 | 179.5036 | 200.7526 |
| 4 | 179.6322 | 179.6322 | 200.8814 |
| 5 | 180.0000 | 180.0000 | 201.2490 |
| 6 | 179.1975 | 179.1975 | 200.4468 |

Le maximum journalier de nuageux n'est pas supérieur à celui de normal dans ce dataset : le pic commun intervient à 19 h, lorsque la production PV mesurée est nulle dans les deux scénarios. Les profils ne sont toutefois pas identiques pendant la production solaire : à 18 h du jour 0, normal mesure 158,8901 kW avec 22,7457 kW de PV, alors que nuageux mesure 172,6998 kW avec 8,9361 kW de PV. Le facteur PV nuageux réduit bien la production; il ne change simplement pas l'heure du maximum quotidien dans les données courantes.

Le générateur appelle `np.random.seed(42)` une seule fois au niveau module, avant la fonction de génération. Les profils de charge ont une variation aléatoire par jour et par maison, bornée entre 0,9 et 1,1; le tirage est partagé entre les scénarios météo afin d'isoler la comparaison des facteurs météo. Cela rend les pics journaliers variables tout en conservant les mêmes charges de base entre scénarios.

`calibration.py` ne calcule pas un facteur de charge distinct par météo : il calcule un facteur unique à partir du scénario de référence normal, puis l'applique aux colonnes de charge de toutes les lignes. Ensuite, `generate_dataset.py` applique `FACTEUR_PV["nuageux"] = 0.4` au PV nuageux et `FACTEUR_HVAC["canicule"] = 1.6` au HVAC canicule. La requête commune `load_measurements(scenario, jour)` filtre explicitement le scénario et le jour.

Les mesures hors de la fenêtre 18–20 h ne satisfont pas une limite stricte de 150 kW : le maximum normal du jour 0 hors de cette fenêtre est 173,7888 kW. Cette valeur est issue de l'agrégation par somme des maisons, directement dans SQLite.

## 9. KPI et méthodologie

`pic_avant_kw` est calculé en sommant les puissances de toutes les maisons pour chaque heure puis en prenant le maximum de ces totaux. `pic_apres_kw` est le maximum journalier des demandes horaires après soustraction des actions mobilisées à chaque heure. Ces calculs sont maintenant alignés sur l'agrégation utilisée par le graphique réseau.

Les formules effectivement enregistrées dans `backend/simulation.py` sont :

```python
hourly_demand_before = measurements.groupby("heure")["grid_import_kw"].sum()
daily_peak_before = float(hourly_demand_before.max())

# Après traitement de chaque heure
daily_peak_after = max(daily_peak_after, demand_after)

energie_deplacee = sum(abs(action["power_kw"]) for action in daily_actions)
economie_estimee = (daily_peak_before - daily_peak_after) * PRIX_ELECTRICITE_EUR_KWH
co2_evite_kg = energie_deplacee * FACTEUR_EMISSION_CO2_KG_KWH
```

Le facteur d'émission CO2 (`FACTEUR_EMISSION_CO2_KG_KWH = 0.4`) est une hypothèse pédagogique, pas une valeur réglementaire ou une mesure d'émissions réelles. L'énergie déplacée est la somme des valeurs absolues des actions enregistrées sur la journée, en kWh sous l'hypothèse d'un créneau d'une heure par action.

**Correction mesurée du KPI, normal/jour 0 :** avant le correctif, `kpi_results.pic_avant_kw` valait 9,9042 kW (maximum d'une ligne maison); après le correctif, il vaut 178,9594 kW (maximum des sommes horaires). La demande maximale après dispatch enregistrée est 150,0048 kW. L'arrondi des puissances d'action explique le petit dépassement résiduel.

## 10. Limites connues

- Les mesures sont synthétiques et ne décrivent pas un réseau électrique réel.
- La simulation et le modèle de confort HVAC sont simplifiés; aucune contrainte électrique détaillée de tension ou fréquence n'est simulée.
- Le dispatch par règles n'est pas démontré optimal; PuLP existe comme alternative, mais l'interface Sandbox utilise la fonction à règles `dispatch()`.
- Le pic normal agrégé hors 18–20 h est 173,7888 kW au jour 0, supérieur à la limite configurée de 150 kW; le profil courant ne satisfait donc pas cette exigence horaire.
- Les actions sont arrondies à deux décimales; le pic après dispatch peut ainsi être supérieur à 150 kW de quelques millièmes de kW.
- Le score « stress » est une approximation cumulative de dispatch; il ne modélise pas la dégradation électrochimique réelle.
- Le dépôt local n'enregistre pas encore un commit distinct décrivant la bascule du prototype frontend à Streamlit; le journal Git disponible ne permet pas d'attribuer cette migration à un commit autonome.

## 11. Historique des changements majeurs

Le `git log --oneline -20` observé contient `4769a81 initial commit` puis `26eb611 Fix Streamlit EV departure constant`. Aucun commit distinct ne décrit une interface frontend HTML/JavaScript ni sa migration vers Streamlit; l'historique local audité commence avec le projet déjà structuré autour de Streamlit. Le changement de KPI et la correction de l'inventaire par maison décrits dans ce README sont présents dans le workspace courant et ne sont pas attribués à un commit publié.

## 12. Équipe et répartition des rôles

À compléter manuellement par l'équipe :

- Responsable backend / simulation :
- Responsable dashboard Streamlit :
- Responsable validation / tests :
- Responsable documentation et revue :
