# Architecture iDER

## Flux applicatif

```text
run_pipeline.py
  1. generate_dataset.py ──> SQLite : measurements, ev_sessions
  2. forecasting_ml.py ────> models/*.joblib ; SQLite : forecasts, model_metrics, feature_importances
  3. simulation.py ────────> SQLite : bilan_horaire, etat_batteries, orchestrator_actions, kpi_results
        ├── models.py        Battery / EV / HVAC (état continu sur la période)
        ├── orchestrator.py  dispatch batteries → VE → HVAC
        └── kpi.py           agrégation quartier et KPI

app.py (Streamlit)
  ├── lecture directe de SQLite
  └── sandbox : simulation.simuler_scenario() en mémoire, rien n'est écrit

optimizer_lp.py : validation d'optimalité hors boucle principale (rejoue le mode réactif)
```

## Principes

- STEG est la source de base (capacité `STEG_CAPACITY_KW`). Les DER couvrent le déficit au-delà de cette capacité.
- Toutes les grandeurs du quartier sont des sommes sur les 20 maisons ; le bilan horaire est fermé à 1e-6 près.
- Chaque scénario est simulé comme une chronologie continue : l'état des batteries se propage d'un jour au suivant.
- La simulation est une fonction pure. La persistance est séparée, ce qui permet au tableau de bord et à la validation LP de réutiliser le même moteur.
- Il n'y a ni API REST ni serveur de base de données séparé : `ider.db` est la source de vérité locale, régénérée par le pipeline.
