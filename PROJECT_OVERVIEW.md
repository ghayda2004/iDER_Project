# iDER Project Overview

## Purpose

iDER is an academic proof of concept for orchestrating distributed energy resources in a synthetic 20-house neighborhood. It was developed in the context of the course *Digital Grid and Business Value*. It demonstrates how batteries, electric vehicles, and controllable HVAC loads might respond to neighborhood demand peaks against a configured 150 kW feeder limit.

**This is a simulation only. It does not read real meters, control physical equipment, or validate operation on a real electrical feeder.**

## What the project contains

- A reproducible synthetic dataset generator for 20 houses, 24 hourly intervals, 7 indexed days, and 3 scenarios.
- A local SQLite database (`ider.db`) containing measurements, dispatch actions, and daily KPIs.
- Python resource models for PV, batteries, EVs, and HVAC.
- A rules-based dispatcher that prioritizes batteries, then EV charging deferral, then HVAC reduction.
- A Streamlit dashboard that reads the SQLite database directly and provides a non-persistent what-if Sandbox.
- A PuLP linear optimizer as an alternative allocation function, although its output format is not currently compatible with the simulation's database-persistence path.

## Architecture

```text
backend/generate_dataset.py -> backend/calibration.py -> SQLite measurements
                                                            |
backend/simulation.py -> forecasting + orchestrator/models -+-> SQLite actions and KPIs
                                                            |
                                                            v
                                                  app.py (Streamlit)
```

There is no REST API, separate database server, Docker setup, or JSON export layer. The UI reads the local database through the Python backend modules.

## Verified dataset snapshot

The checked-in workspace database currently contains:

- `measurements`: 10,080 rows (3,360 rows per scenario)
- `orchestrator_actions`: 908 rows
- `kpi_results`: 21 rows

The 10,080 measurement rows equal $20 \times 24 \times 7 \times 3$. The random seed is set once to `42`; per-house, per-day demand variation is shared across weather scenarios to make daily profiles vary while keeping scenario comparisons aligned.

Daily neighborhood peak power, aggregated as the sum of all houses for each hour and then maximized over the day:

| Day | Normal (kW) | Cloudy (kW) | Heatwave (kW) |
|---:|---:|---:|---:|
| 0 | 178.9594 | 178.9594 | 200.2085 |
| 1 | 178.5623 | 178.5623 | 199.8116 |
| 2 | 179.6127 | 179.6127 | 200.8617 |
| 3 | 179.5036 | 179.5036 | 200.7526 |
| 4 | 179.6322 | 179.6322 | 200.8814 |
| 5 | 180.0000 | 180.0000 | 201.2490 |
| 6 | 179.1975 | 179.1975 | 200.4468 |

Normal and cloudy have the same daily peak because the maximum occurs at 19:00, when PV output is zero. Their daytime profiles do differ: on day 0 at 18:00, normal demand is 158.8901 kW with 22.7457 kW of PV; cloudy demand is 172.6998 kW with 8.9361 kW of PV. Across the seven days, measured hours above 150 kW total 42 for normal, 49 for cloudy, and 49 for heatwave.

## Example: normal scenario, day 0

At 19:00, the neighborhood demand is 178.9594 kW, so the initial deficit against 150 kW is 28.9594 kW. The stored rules-based plan contains seven battery discharge actions and two EV deferral actions. Their rounded stored powers sum to 28.96 kW; rounding causes a small difference from the unrounded deficit.

The stored daily KPIs are:

- Peak before dispatch: 178.9594 kW
- Peak after dispatch: 150.0048 kW
- Displaced energy: 117.69 kWh under the code's one-hour-per-action convention
- Estimated savings: EUR 5.79092
- Estimated CO2 avoided: 47.076 kg

The savings and emissions are educational estimates, not bill or emissions measurements. The savings formula multiplies a peak-power difference by an energy price, without a duration or demand tariff, so it should not be presented as an actual bill reduction.

## Run the project

From the project root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python backend/generate_dataset.py
python backend/simulation.py
streamlit run app.py
```

Run the current tests with:

```powershell
python -m pytest tests/ -v
```

## Important limitations

- All input profiles are synthetic and calibrated for demonstration; the calibration scales base load and HVAC using a factor measured from the normal scenario.
- The forecasting function averages per-house rows while the feeder limit applies to an aggregate neighborhood sum; the forecast is therefore not on the same scale as the feeder demand.
- EV arrival/departure draws are not stored. The EV deferral method increases SOC, which does not faithfully model delaying a charge.
- Resource states changed by dispatch are not written back to the measurements table. Battery fairness state is in memory and resets when resource objects are rebuilt for another scenario/day.
- The current persisted action rows contain battery and EV actions, but no HVAC actions.
- The LP function can calculate allocations directly, but its action dictionaries do not include the fields required by the simulation's persistence code.
- The CO2 factor and electricity price are fixed educational assumptions; the prototype has no real tariffs, meter data, or emissions accounting.

For the complete French walkthrough, database queries, exact implementation details, and oral-defense preparation, see [docs/EXPLICATION_PROJET.md](docs/EXPLICATION_PROJET.md).
