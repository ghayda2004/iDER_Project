# iDER | Orchestration énergétique distribuée

## 1. Présentation

iDER simule un quartier de 20 maisons doté de photovoltaïque, de batteries, de véhicules électriques et de charges HVAC pilotables. Le moteur Python produit des données synthétiques, les stocke dans SQLite et simule le dispatch face à une limite réseau de 150 kW. Streamlit fournit le tableau de bord de consultation et un mode what-if; le prototype ne commande aucun équipement réel.

## 2. Architecture technique

La migration vers Streamlit simplifie réellement l'architecture : elle supprime la couche d'export intermédiaire et la double représentation des résultats en JSON. L'interface Python lit directement les tables SQLite et appelle les modèles et fonctions du backend. La génération et la simulation restent des étapes explicites, tandis que l'application sert à explorer les résultats et à tester des hypothèses sans modifier la base.

```text
generate_dataset.py ──> SQLite: measurements
                        │
simulation.py ────────────────┼──> SQLite: actions + KPI
                        │
                        v
                    app.py (Streamlit)
                    ├── database.py
                    ├── models.py
                    ├── forecasting.py
                    └── orchestrator.py (sandbox direct)
```

| Technologie | Rôle |
|---|---|
| Python / pandas / NumPy | Génération synthétique, modèles et simulation |
| SQLite | Stockage local des mesures, actions et KPI |
| Streamlit | Interface interactive, filtres et tableaux de bord |
| Plotly | Graphiques horaires et comparaison des scénarios |
| PuLP | Optimisation LP alternative du dispatch |

Cette simplification retire le fichier JSON généré, son chemin de lecture et le fallback de démonstration. Streamlit est le serveur d'interface; aucun serveur applicatif séparé ni API REST n'est requis.

## 3. Fonctionnement de l'orchestrateur (à détailler pédagogiquement)

L'orchestrateur a une logique simple mais lisible :

1. Il calcule un déficit réseau, c'est-à-dire la quantité de puissance à enlever par rapport à la limite admissible.
2. Il classe les ressources selon un ordre de mérite : batterie, puis VE, puis chauffage.
3. Il décide de réduire ou décaler la consommation en fonction de la flexibilité disponible de chaque ressource.
4. Il met en place une logique d'équité afin de ne pas toujours solliciter la même batterie.

### Ordre de mérite

Le principe est le suivant :

- les batteries sont la première ligne de réponse, car elles sont des stockages rapides et flexibles ;
- les véhicules électriques sont la seconde réponse, via report de charge ;
- les chauffages pilotables servent de dernier levier, avec une réduction limitée et encadrée.

### Score d'équité

L'innovation principale du projet est le score d'équité cumulé dans chaque batterie. À chaque décharge, la batterie augmente son score de stress, exprimé en kWh cumulés. L'orchestrateur trie les batteries selon ce score croissant : les unités le moins sollicitées sont priorisées. Cela évite qu'une seule batterie se fatigue de manière disproportionnée et distribue la charge de façon plus équitable sur le parc.

### Mode Sandbox

Le mode Sandbox correspond à une simulation de flexibilité sur une limite réseau donnée. Exemple : si le pic naturel est de 180 kW et que la limite réseau vaut 150 kW, alors le déficit à combler est de 30 kW. L'orchestrateur va appliquer les actions de la façon suivante :

- Batterie : -5.0 kW sur une batterie disponible (ex. 5 kW pendant 1 h) ;
- VE : report de 7 kW ou légère réduction pour un véhicule dont la charge est décalable ;
- HVAC : réduction de 1 à 3 kW selon la plage de confort.

Exemple chiffré :

- Pic brut : 180 kW
- Limite réseau : 150 kW
- Déficit : 30 kW
- Action 1 : batterie B004 = -5 kW
- Action 2 : VE E003 = -7 kW
- Action 3 : chauffage H014 = -2.5 kW
- Total mobilisé : 14.5 kW ; le reste du déficit est géré au prochain créneau ou signalé comme non couvert.

Le but est de démontrer la logique de gestion de flexibilité, pas de garantir l'optimalité mathématique absolue du scénario en production réelle.

### Mode LP

Le fichier optimizer_lp.py propose une version alternative basée sur PuLP. Elle minimise une pénalité pondérée :

- batterie = 1 ;
- VE = 2 ;
- HVAC = 3.

Cette approche est une alternative de calcul afin de comparer la solution de règles avec une solution mathématique linéaire, tout en gardant le même ensemble de bornes de flexibilité.

## 3. Structure du dépôt

```text
.
├── app.py                       # tableau de bord Streamlit
├── backend/                     # génération, stockage, modèles et orchestration
├── docs/                        # architecture et journal d'usage IA
├── tests/                       # tests métier
├── .streamlit/config.toml       # thème Streamlit
├── ider.db                      # base locale, créée au runtime
├── requirements.txt
└── README.md
```

## 4. Installation et lancement

Prérequis :

- Python 3.10+
- pip
- navigateur web moderne

Étapes :

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate
pip install -r requirements.txt
```

Depuis la racine du projet, activez l'environnement virtuel puis installez les dépendances. Pour générer les mesures, calculer les actions/KPI et lancer le tableau de bord :

```bash
python backend/generate_dataset.py
python backend/simulation.py
streamlit run app.py
```

Streamlit affiche l'URL locale dans le terminal (par défaut `http://localhost:8501`). Les données affichées sont lues directement depuis `ider.db`; il n'y a pas d'export de résultats à lancer.

## 5. Tableau de bord

Les cinq onglets présentent la vue d'ensemble, le parc PV/batteries/VE/HVAC, la demande horaire avec la limite réseau, les actions et le Sandbox, puis les KPI. Les sélecteurs scénario/jour filtrent les vues. Le Sandbox rappelle directement `orchestrator.dispatch()` avec la limite choisie; il est non persistant et ne modifie pas la base.

Les données actuelles peuvent contenir un écart entre le pic agrégé des mesures et `kpi_results.pic_avant_kw`, car le calcul KPI historique de la simulation stocke un maximum par ligne de maison alors que le graphique agrège les maisons par heure. L'application montre les KPI tels qu'ils sont enregistrés et signale cet écart; elle ne duplique ni ne corrige le calcul métier.

## 6. Tests

```bash
pytest tests/ -v
```

## 7. Scénarios disponibles

Le prototype gère trois scénarios météo indépendants et les chiffres ci-dessous sont ceux mesurés lors d'une exécution complète du pipeline sur la base actuelle.

| Scénario | Paramètres | Pic mesuré (kW) | Commentaire |
|---|---|---:|---|
| Normal | production PV standard, chauffage nominal | 180.0001 | validé dans la bande cible 175–185 kW pour les jours de référence |
| Nuageux | facteur PV = 0.4 | 180.0001 | même pic que le scénario normal après calibration du jeu de données |
| Canicule | facteur HVAC = 1.6 | 201.2788 | scénario de stress thermique, plus élevé que le cas normal |

Les pics sont calculés en agrégeant la demande de toutes les maisons par heure, puis en prenant le maximum journalier. Les nombres peuvent varier selon le dataset regénéré.

Important : la contrainte fonctionnelle la plus stricte concernait le scénario normal. Le pic enregistré est bien compris dans la fourchette cible $[175, 185]$ kW, et les heures hors plage 18–20 h restent sous la limite réseau de 150 kW. Le scénario canicule est volontairement plus exigeant en charge thermique et dépasse donc le niveau du cas normal, sans remettre en cause le respect de la cible sur le scénario de référence.

## 8. KPI et méthodologie

Les KPI sont calculés selon les formules exactes suivantes :

- reduction_pic_pct = (pic_avant - pic_apres) / pic_avant * 100
- energie_deplacee_kwh = somme des |power_kw| de toutes les actions de dispatch sur la journée
- economie_estimee_eur = (pic_avant - pic_apres) * PRIX_ELECTRICITE_EUR_KWH
- co2_evite_kg = energie_deplacee_kwh * FACTEUR_EMISSION_CO2_KG_KWH

Le facteur d'émission CO2 est une hypothèse pédagogique documentée dans le code et dans ce README. Il ne doit pas être interprété comme une valeur officialisée par un organisme public ou réglementaire.

## 9. Limites connues

- le dataset est synthétique et n'est pas basé sur des mesures réelles ;
- le modèle de batterie est simplifié et ne tient pas compte de la dégradation ;
- le dispatch par règles n'est pas démontré mathématiquement optimal, sauf en mode LP optionnel ;
- la simulation ne gère pas de multi-utilisateur ni d'authentification ;
- la tension, la fréquence et la physique du réseau ne sont pas modélisées ;
- le projet est un démonstrateur académique, pas un système de contrôle industriel.

## 10. Équipe et répartition des rôles

À compléter par l'équipe :

- Responsable backend / simulation :
- Responsable dashboard Streamlit :
- Responsable validation / tests :
- Responsable documentation et revue :

---

Ce prototype a été construit pour démontrer la faisabilité d'une orchestration locale de ressources énergétiques distribuées, avec un accent spécial sur la transparence du calcul, la pédagogie de l'algorithme d'ordonnancement et la simplicité d'exploitation dans un environnement universitaire.
