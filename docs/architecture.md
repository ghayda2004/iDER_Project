# Architecture iDER

## Flux applicatif

```text
generate_dataset.py ──> SQLite: measurements
                              │
simulation.py ────────────────┼──> SQLite: orchestrator_actions + kpi_results
                              │
                              v
                         app.py (Streamlit)
                         ├── database.py: lecture directe des tables
                         ├── models.py: ressources DER
                         ├── forecasting.py: prévision utilisée par le moteur
                         └── orchestrator.py: dispatch du Sandbox what-if
```

## Simplification par rapport au prototype

L'interface Streamlit remplace le dashboard HTML/JavaScript et lit la base SQLite directement via les modules Python. La couche d'export JSON et les fichiers de données de démonstration ne font plus partie de l'architecture cible. Il n'y a pas de serveur API séparé. Le Sandbox appelle `orchestrator.dispatch()` en mémoire et n'écrit pas ses résultats dans la base.

## Responsabilités

- `backend/generate_dataset.py` crée les mesures synthétiques.
- `backend/simulation.py` exécute le scénario et persiste les actions et KPI.
- `app.py` filtre et présente les données existantes, sans recopier les algorithmes métier.
- `ider.db` est la source de vérité locale pour les mesures, actions et KPI.
