# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

iDER is an academic proof-of-concept (course "Digital Grid and Business Value"). A 20-house neighborhood is supplied by **STEG** (Tunisian grid) as the base source, capped at `STEG_CAPACITY_KW = 150`. DER (PV, batteries, EVs, HVAC) cover the **deficit** above that cap. An ML forecast (T+1 h) drives a `predictif` mode, compared with `reactif` and a `sans_orchestration` reference. Data is synthetic. Identifiers, comments, docs and UI text are in **French**; keep new code consistent. `README.md` is the detailed reference and contains measured results; update its numbers when behavior changes (only real outputs, never invented figures).

## Commands

Run from the repository root (Python 3.11, Windows/PowerShell; `&&` does not work in PowerShell 5.1):

```powershell
python -m pip install -r requirements.txt
python run_pipeline.py                 # dataset -> ML training -> simulation (3 modes) -> KPI report (~30 s)
python run_pipeline.py --validation-lp # + LP vs rules comparison
python -m pytest -q                    # 28 tests, ~15 s
python -m pytest tests/test_bilan.py::test_bilan_energetique -q   # single test
streamlit run app.py
```

`ider.db` and `models/` are generated artifacts (git-ignored). The app shows an error until the pipeline has run.

## Architecture

Pipeline (each stage rewrites its own tables, no appends):

1. `backend/generate_dataset.py`: `construire_dataset()` builds per-house hourly measurements in memory with a single `np.random.default_rng(SEED)`. `generate_dataset()` calls `reinitialiser_schema()` (drops **all** tables) and writes `measurements` + `ev_sessions`. Random draws are shared across weather scenarios; `coupure_steg` is an exact copy of `normal` with `steg_available = 0` on day `N_DAYS-3`, 20h-22h. Dates are dynamic (last day = today), so weekday effects shift with the run date.
2. `backend/forecasting_ml.py`: aggregates per scenario, builds leak-free features (`construire_features`), chronological split by day index (70/15/15), RandomForest per target (`charge`, `pv`) vs baseline and persistence. Writes `forecasts`, `model_metrics`, `feature_importances`, and `models/*.joblib`.
3. `backend/simulation.py`: `simuler_scenario()` runs one scenario × mode as a **continuous timeline** (DER objects created once; SoC/`stress_score` carry across days). Pure function (no DB writes); reused by the dashboard sandbox and the LP validation (`observateur` hook). `run_simulation()` persists `bilan_horaire`, `etat_batteries`, `orchestrator_actions`, `kpi_results`.
4. `app.py` reads SQLite. A STEG capacity other than 150 kW triggers an in-memory re-simulation (`simulation_sandbox`, cached).

Key invariants (enforced by tests):

- Hourly balance: `steg_import + contribution_der + pv_utilise + energie_non_desservie = charge_totale`, where `charge_totale` includes battery recharge and EV demand *before* deferral. Powers are never rounded in the engine. Round only for display.
- Neighborhood quantities are **sums over houses** (`kpi.agreger_quartier`), never per-house maxima. STEG import exists only at neighborhood level (`bilan_horaire`); there is no per-house `grid_import_kw` anymore.
- `sans_orchestration`: STEG uncapped (excess = `depassement_steg_kw`). Orchestrated modes: STEG ≤ available capacity, any shortfall is `energie_non_desservie_kw`.
- SoC values are fractions (0-1). Efficiency applies on charge. EV deferral is bounded so charging always completes before departure (except during an outage, where `delestage=True` allows full shedding and lifts the 50 % battery fairness cap).
- `dispatch()` mutates objects and keeps the merit order battery → EV → HVAC with the 50 % fairness cap (deliberately suboptimal vs LP). Outage order is battery → HVAC → EV.
- Predictive mode needs a forecast array aligned on timeline index `t` (forecast for hour t made at t-1). The reactive dispatch always runs as a safety net.
- `database.DB_PATH` and `config.MODEL_DIR` are read at call time; `tests/conftest.py` monkeypatches them to run the whole pipeline (20 days) in a temp dir. Don't import these values by name where tests need to override them.

Tariffs (TND) and the CO2 factor in `config.py` are illustrative and must be labeled as such wherever they are shown.
