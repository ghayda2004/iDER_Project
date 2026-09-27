from __future__ import annotations

from contextlib import closing

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from backend.config import (
    BATTERY_CAPACITY_KWH,
    BATTERY_MAX_POWER_KW,
    EV_BATTERY_CAPACITY_KWH,
    EV_DEPART_MOYEN_H,
    EV_MAX_CHARGE_KW,
    GRID_LIMIT_KW,
    MAISONS_AVEC_BATTERIE,
    MAISONS_AVEC_EV,
    MAISONS_AVEC_PV,
    NB_MAISONS,
    SCENARIOS,
)
from backend.database import get_connection, init_db, load_measurements
from backend.models import Battery, EV, HVAC
from backend.orchestrator import dispatch

st.set_page_config(page_title="iDER | Pilotage énergétique", page_icon="⚡", layout="wide")
init_db()


@st.cache_data(ttl=10)
def read_query(query: str, params: tuple = ()) -> pd.DataFrame:
    with closing(get_connection()) as connection:
        return pd.read_sql_query(query, connection, params=params)


@st.cache_data(ttl=10)
def read_day(scenario: str, day: int) -> pd.DataFrame:
    return load_measurements(scenario, day)


def latest_kpi(scenario: str, day: int) -> pd.DataFrame:
    return read_query(
        """
        SELECT pic_avant_kw, pic_apres_kw, energie_deplacee_kwh,
               economie_estimee_eur, co2_evite_kg
        FROM kpi_results
        WHERE scenario = ? AND jour = ?
        ORDER BY rowid DESC
        LIMIT 1
        """,
        (scenario, day),
    )


def hourly_demand(measurements: pd.DataFrame) -> pd.DataFrame:
    return (
        measurements.groupby("heure", as_index=False)["grid_import_kw"]
        .sum()
        .rename(columns={"grid_import_kw": "demande_kw"})
        .sort_values("heure")
    )


def build_resource_inventory(measurements: pd.DataFrame, actions: pd.DataFrame):
    houses = measurements.sort_values(["heure", "house_id"]).groupby("house_id", as_index=False).agg(
        pv_kw=("pv_kw", "max"),
        battery_soc=("battery_soc", "last"),
        ev_soc=("ev_soc", "last"),
        ev_connected=("ev_connected", "max"),
        hvac_kw=("hvac_kw", "last"),
    )
    pv_houses = houses[houses["pv_kw"] > 0].copy()
    battery_houses = houses[houses["battery_soc"] > 0].copy()
    ev_houses = houses[houses["ev_soc"] > 0].copy()

    stress_by_id = {}
    if not actions.empty:
        battery_actions = actions[actions["device_type"] == "battery"]
        stress_by_id = battery_actions.groupby("device_id")["power_kw"].apply(lambda values: values.abs().sum()).to_dict()

    battery_houses["device_id"] = [f"B{index:03d}" for index in range(1, len(battery_houses) + 1)]
    battery_houses["stress_score_kwh"] = battery_houses["device_id"].map(stress_by_id).fillna(0.0)
    ev_houses["device_id"] = [f"E{index:03d}" for index in range(1, len(ev_houses) + 1)]
    return pv_houses, battery_houses, ev_houses, houses


def run_sandbox(measurements: pd.DataFrame, limit_kw: float) -> pd.DataFrame:
    first_hour = measurements[measurements["heure"] == measurements["heure"].min()].sort_values("house_id")
    batteries = [
        Battery(f"B{index:03d}", BATTERY_CAPACITY_KWH, float(row.battery_soc), BATTERY_MAX_POWER_KW)
        for index, row in enumerate(first_hour.itertuples(), start=1)
        if row.battery_soc > 0
    ]
    evs = [
        EV(
            f"E{index:03d}",
            EV_BATTERY_CAPACITY_KWH,
            EV_MAX_CHARGE_KW,
            bool(row.ev_connected),
            18,
            EV_DEPART_MOYEN_H,
            float(row.ev_soc),
        )
        for index, row in enumerate(first_hour.itertuples(), start=1)
        if row.ev_soc > 0
    ]

    plan = []
    for hour in range(24):
        hour_rows = measurements[measurements["heure"] == hour].sort_values("house_id")
        if hour_rows.empty:
            continue
        demand = float(hour_rows["grid_import_kw"].sum())
        deficit = max(0.0, demand - limit_kw)
        if deficit <= 0:
            continue

        hvacs = [
            HVAC(str(row.house_id), float(row.hvac_kw), 0.5, float(row.hvac_kw))
            for row in hour_rows.itertuples()
        ]
        actions, remaining = dispatch(deficit, batteries, evs, hvacs)
        for action in actions:
            plan.append(
                {
                    "heure": hour,
                    "demande_avant_kw": round(demand, 2),
                    "limite_kw": limit_kw,
                    "device_id": action["device_id"],
                    "type": action["device_type"],
                    "action": action["action_type"],
                    "puissance_kw": action["power_kw"],
                    "justification": action["justification"],
                    "deficit_residuel_kw": round(remaining, 2),
                }
            )
        if not actions:
            plan.append(
                {
                    "heure": hour,
                    "demande_avant_kw": round(demand, 2),
                    "limite_kw": limit_kw,
                    "device_id": "Aucune ressource disponible",
                    "type": "-",
                    "action": "NON_COUVERT",
                    "puissance_kw": 0.0,
                    "justification": f"Déficit non couvert : {remaining:.2f} kW",
                    "deficit_residuel_kw": round(remaining, 2),
                }
            )
    return pd.DataFrame(plan)


st.title("iDER | Orchestration énergétique")
st.caption("Tableau de pilotage du quartier · données SQLite · simulation, pas de commande matérielle")

available_scenarios = read_query("SELECT DISTINCT scenario FROM measurements ORDER BY scenario")
if available_scenarios.empty:
    st.error("Aucune mesure disponible. Lancez d'abord `python backend/generate_dataset.py` puis `python backend/simulation.py`.")
    st.stop()

scenario_options = [scenario for scenario in SCENARIOS if scenario in available_scenarios["scenario"].tolist()]
selector_columns = st.columns([1, 1, 3])
with selector_columns[0]:
    selected_scenario = st.selectbox("Scénario", scenario_options, format_func=lambda value: value.capitalize())
available_days = read_query(
    "SELECT DISTINCT jour FROM measurements WHERE scenario = ? ORDER BY jour",
    (selected_scenario,),
)
day_options = available_days["jour"].astype(int).tolist()
with selector_columns[1]:
    selected_day = st.selectbox("Jour", day_options, format_func=lambda value: f"Jour {value}")

measurements = read_day(selected_scenario, selected_day)
if measurements.empty:
    st.error("Aucune mesure pour cette sélection.")
    st.stop()

actions = read_query(
    """
    SELECT heure, device_id, device_type, action_type, power_kw, justification
    FROM orchestrator_actions
    WHERE scenario = ? AND jour = ?
    ORDER BY heure, rowid
    """,
    (selected_scenario, selected_day),
)
kpi = latest_kpi(selected_scenario, selected_day)
hourly = hourly_demand(measurements)
peak_row = hourly.loc[hourly["demande_kw"].idxmax()]
measured_peak = float(peak_row["demande_kw"])
peak_hour = int(peak_row["heure"])
pv_houses, battery_houses, ev_houses, house_inventory = build_resource_inventory(measurements, actions)
pv_capacity_estimate = float(pv_houses["pv_kw"].sum()) if not pv_houses.empty else 0.0

overview_tab, resources_tab, grid_tab, orchestrator_tab, results_tab = st.tabs(
    ["Vue d'ensemble", "Parc de ressources", "Suivi réseau", "Orchestrateur", "Résultats"]
)

with overview_tab:
    st.subheader(f"{selected_scenario.capitalize()} · jour {selected_day}")
    left, right = st.columns(2)
    with left:
        st.metric("DER modélisées", f"{MAISONS_AVEC_PV + MAISONS_AVEC_BATTERIE + MAISONS_AVEC_EV + NB_MAISONS}")
        st.metric("Puissance PV max observée", f"{pv_capacity_estimate:.1f} kW")
        st.metric("Capacité batterie totale", f"{MAISONS_AVEC_BATTERIE * BATTERY_CAPACITY_KWH:.0f} kWh")
        st.metric("Véhicules électriques", f"{len(ev_houses)}")
    with right:
        st.metric(
            "Demande réseau au pic du jour",
            f"{measured_peak:.1f} kW",
            f"{measured_peak - GRID_LIMIT_KW:+.1f} kW vs limite {GRID_LIMIT_KW} kW",
            delta_color="inverse",
        )
        if not kpi.empty:
            kpi_row = kpi.iloc[0]
            before = float(kpi_row["pic_avant_kw"])
            after = float(kpi_row["pic_apres_kw"])
            reduction = ((before - after) / before * 100.0) if before else 0.0
            st.metric("Réduction de pic enregistrée", f"{reduction:.1f}%")
            st.metric("Économie estimée enregistrée", f"{float(kpi_row['economie_estimee_eur']):.2f} €")
            if abs(before - measured_peak) > 1.0:
                st.warning(
                    f"Écart dans les données persistées : le pic agrégé des mesures vaut {measured_peak:.2f} kW, "
                    f"mais kpi_results.pic_avant_kw vaut {before:.4f} kW. Les KPI sont affichés tels qu'enregistrés; "
                    "l'application ne modifie pas la logique de simulation."
                )
        else:
            st.warning("Aucun KPI enregistré pour cette sélection. Lancez `python backend/simulation.py`.")
    st.caption("La puissance PV affichée est une estimation issue des maxima observés par maison; le dataset ne stocke pas de puissance nominale constructeur.")

with resources_tab:
    pv_tab, battery_tab, ev_tab, hvac_tab = st.tabs(["PV", "Batteries", "VE", "HVAC"])
    with pv_tab:
        st.metric("Maisons avec PV", len(pv_houses))
        st.dataframe(
            pv_houses[["house_id", "pv_kw"]].rename(columns={"house_id": "Maison", "pv_kw": "Puissance max observée (kW)"}),
            use_container_width=True,
            hide_index=True,
        )
    with battery_tab:
        st.caption("Le SOC est celui de la dernière mesure du jour. Le score est le cumul des décharges enregistrées pour l'identifiant d'orchestration correspondant.")
        for row in battery_houses.itertuples():
            line = st.columns([1, 2, 1])
            line[0].markdown(f"**{row.device_id}** · {row.house_id}")
            line[1].progress(min(100, max(0, int(row.battery_soc))), text=f"SOC {row.battery_soc:.1f}%")
            line[2].metric("Stress (kWh)", f"{row.stress_score_kwh:.2f}")
    with ev_tab:
        ev_display = ev_houses[["device_id", "house_id", "ev_connected", "ev_soc"]].copy()
        ev_display["État"] = ev_display["ev_connected"].map({1: "Connecté", 0: "Déconnecté"})
        ev_display["Départ prévu"] = f"{EV_DEPART_MOYEN_H} h"
        ev_display = ev_display[["device_id", "house_id", "État", "ev_soc", "Départ prévu"]]
        st.dataframe(
            ev_display.rename(columns={"device_id": "VE", "house_id": "Maison", "ev_soc": "SOC (%)"}),
            use_container_width=True,
            hide_index=True,
        )
    with hvac_tab:
        hvac_display = house_inventory[["house_id", "hvac_kw"]].rename(
            columns={"house_id": "Maison", "hvac_kw": "Puissance HVAC (kW)"}
        )
        st.dataframe(hvac_display, use_container_width=True, hide_index=True)

with grid_tab:
    st.subheader("Demande horaire agrégée")
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=hourly["heure"],
            y=hourly["demande_kw"],
            mode="lines+markers",
            name="Demande quartier",
            line={"color": "#23875a", "width": 3},
        )
    )
    figure.add_hline(
        y=GRID_LIMIT_KW,
        line_dash="dash",
        line_color="#d17a32",
        annotation_text=f"Limite réseau {GRID_LIMIT_KW} kW",
        annotation_position="top left",
    )
    figure.update_layout(
        xaxis_title="Heure",
        yaxis_title="Puissance (kW)",
        xaxis={"dtick": 1, "range": [0, 23]},
        height=430,
        margin={"l": 20, "r": 20, "t": 40, "b": 20},
        template="plotly_white",
        legend={"orientation": "h", "y": 1.08},
    )
    st.plotly_chart(figure, use_container_width=True)
    st.caption(f"Pic mesuré : {measured_peak:.2f} kW à {peak_hour:02d} h. Les puissances sont agrégées par somme des maisons, en kW.")

with orchestrator_tab:
    st.subheader("Actions enregistrées")
    if actions.empty:
        st.info("Aucune action enregistrée pour ce scénario et ce jour.")
    else:
        st.dataframe(
            actions.rename(
                columns={
                    "heure": "Heure",
                    "device_id": "Ressource",
                    "device_type": "Type",
                    "action_type": "Action",
                    "power_kw": "Puissance (kW)",
                    "justification": "Justification",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()
    st.subheader("Sandbox · simulation what-if")
    st.caption("Le recalcul appelle directement orchestrator.dispatch() et ne modifie ni les mesures ni les résultats enregistrés en base.")
    sandbox_limit = st.slider("Nouvelle limite réseau (kW)", min_value=100, max_value=200, value=GRID_LIMIT_KW, step=5)
    sandbox_plan = run_sandbox(measurements, float(sandbox_limit))
    if sandbox_plan.empty:
        st.success(f"Aucun dispatch requis : la demande reste sous {sandbox_limit} kW toute la journée.")
    else:
        action_total = float(sandbox_plan["puissance_kw"].sum())
        residual_peak = float(sandbox_plan["deficit_residuel_kw"].max())
        summary_columns = st.columns(3)
        summary_columns[0].metric("Limite simulée", f"{sandbox_limit} kW")
        summary_columns[1].metric("Puissance dispatchée", f"{action_total:.2f} kW")
        summary_columns[2].metric("Déficit résiduel max", f"{residual_peak:.2f} kW")
        st.dataframe(sandbox_plan, use_container_width=True, hide_index=True)

with results_tab:
    st.subheader("Résultats du jour sélectionné")
    if kpi.empty:
        st.warning("Aucun KPI disponible en base pour cette sélection.")
    else:
        kpi_row = kpi.iloc[0]
        before = float(kpi_row["pic_avant_kw"])
        after = float(kpi_row["pic_apres_kw"])
        reduction = ((before - after) / before * 100.0) if before else 0.0
        cards = st.columns(3)
        cards[0].metric("Pic avant enregistré", f"{before:.2f} kW")
        cards[1].metric("Pic après enregistré", f"{after:.2f} kW")
        cards[2].metric("Réduction enregistrée", f"{reduction:.1f}%")

        scenario_peaks = read_query(
            """
            SELECT scenario, MAX(total_kw) AS peak_kw
            FROM (
                SELECT scenario, jour, heure, SUM(grid_import_kw) AS total_kw
                FROM measurements
                GROUP BY scenario, jour, heure
            )
            GROUP BY scenario
            ORDER BY scenario
            """
        )
        bar = go.Figure(
            go.Bar(
                x=scenario_peaks["scenario"],
                y=scenario_peaks["peak_kw"],
                marker_color=["#3cb371", "#79bb91", "#d17a32"],
                text=scenario_peaks["peak_kw"].map(lambda value: f"{value:.1f} kW"),
                textposition="outside",
            )
        )
        bar.add_hline(y=GRID_LIMIT_KW, line_dash="dash", line_color="#6b756f", annotation_text="Limite 150 kW")
        bar.update_layout(
            title="Pic agrégé maximal par scénario",
            yaxis_title="Puissance (kW)",
            height=380,
            template="plotly_white",
            margin={"l": 20, "r": 20, "t": 60, "b": 20},
        )
        st.plotly_chart(bar, use_container_width=True)

        kpi_table = read_query(
            """
            SELECT scenario, jour, pic_avant_kw, pic_apres_kw,
                   energie_deplacee_kwh, economie_estimee_eur, co2_evite_kg
            FROM kpi_results
            WHERE scenario = ? AND jour = ?
            ORDER BY rowid DESC
            LIMIT 1
            """,
            (selected_scenario, selected_day),
        )
        st.markdown("**KPI enregistrés en base**")
        st.dataframe(kpi_table, use_container_width=True, hide_index=True)