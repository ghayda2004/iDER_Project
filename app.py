from __future__ import annotations

from contextlib import closing
from html import escape

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
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    :root {
        --green-900: #0B3D2E;
        --green-700: #1F6F50;
        --green-500: #3CB371;
        --green-300: #8FD9B6;
        --green-100: #E3F5EC;
        --bg: #F7FAF8;
        --text: #1C2620;
        --alert: #E76F51;
    }
    html, body, [class*="st-"] { font-family: 'Inter', sans-serif; }
    .stApp { background: var(--bg); color: var(--text); }
    section[data-testid="stSidebar"] { background: var(--green-900); }
    section[data-testid="stSidebar"] * { color: var(--green-100); }
    section[data-testid="stSidebar"] [data-baseweb="select"] > div {
        background: var(--green-100);
        border-color: var(--green-300);
    }
    section[data-testid="stSidebar"] [data-baseweb="select"] span,
    section[data-testid="stSidebar"] [data-baseweb="select"] input { color: var(--green-900); }
    .ider-brand { color: var(--green-100); font-size: 1.55rem; font-weight: 700; }
    .ider-brand-note { color: var(--green-300); font-size: 0.82rem; }
    .ider-legend { margin-top: 1.25rem; padding-top: 0.9rem; border-top: 1px solid color-mix(in srgb, var(--green-100) 25%, transparent); }
    .legend-line { margin: 0.3rem 0; font-size: 0.82rem; }
    .legend-dot { display: inline-block; width: 0.58rem; height: 0.58rem; border-radius: 50%; margin-right: 0.45rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 0.35rem; }
    .stTabs [aria-selected="true"] { color: var(--green-700); }
    [data-testid="stMetricLabel"] { color: var(--green-900); font-weight: 600; }
    [data-testid="stMetricValue"] { color: var(--text); }
    .resource-title { color: var(--green-900); font-weight: 600; margin-bottom: 0.25rem; }
    .resource-meta { color: color-mix(in srgb, var(--text) 70%, transparent); font-size: 0.84rem; }
    .soc-track { height: 0.58rem; width: 100%; background: var(--green-100); border-radius: 1rem; overflow: hidden; margin: 0.7rem 0 0.35rem; }
    .soc-fill { height: 100%; border-radius: inherit; }
    .status-badge { display: inline-block; padding: 0.18rem 0.5rem; border-radius: 1rem; background: var(--green-100); color: var(--green-700); font-size: 0.76rem; font-weight: 600; }
    .status-muted { display: inline-block; padding: 0.18rem 0.5rem; border-radius: 1rem; background: color-mix(in srgb, var(--text) 8%, var(--bg)); color: var(--text); font-size: 0.76rem; font-weight: 600; }
    .timeline-entry { border-left: 4px solid var(--green-700); padding: 0.12rem 0 0.12rem 0.85rem; }
    .timeline-ev { border-left-color: var(--green-500); }
    .timeline-hvac { border-left-color: var(--green-300); }
    .timeline-hour { color: var(--green-900); font-weight: 700; }
    .timeline-detail { color: color-mix(in srgb, var(--text) 78%, transparent); margin-top: 0.2rem; }
    .timeline-justification { color: color-mix(in srgb, var(--text) 68%, transparent); font-size: 0.88rem; margin: 0.35rem 0 0; }
    .sandbox-note { border-left: 3px solid var(--green-500); padding-left: 0.75rem; color: var(--text); }
    .peak-warning { color: var(--alert); font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)
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


PLOTLY_COLORS = {
    "green_900": "#0B3D2E",
    "green_700": "#1F6F50",
    "green_500": "#3CB371",
    "green_300": "#8FD9B6",
    "green_100": "#E3F5EC",
    "bg": "#F7FAF8",
    "text": "#1C2620",
    "alert": "#E76F51",
}


def render_metric_grid(metrics: list[dict], columns_per_row: int = 4) -> None:
    for start in range(0, len(metrics), columns_per_row):
        columns = st.columns(columns_per_row)
        for column, item in zip(columns, metrics[start : start + columns_per_row]):
            with column:
                with st.container(border=True):
                    st.metric(
                        item["label"],
                        item["value"],
                        delta=item.get("delta"),
                        delta_color=item.get("delta_color", "normal"),
                    )


def build_grid_figure(hourly: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    upper_exceedance = hourly["demande_kw"].clip(lower=GRID_LIMIT_KW)
    limit_line = [GRID_LIMIT_KW] * len(hourly)
    figure.add_trace(
        go.Scatter(
            x=hourly["heure"],
            y=upper_exceedance,
            mode="lines",
            line={"width": 0, "color": PLOTLY_COLORS["alert"]},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    figure.add_trace(
        go.Scatter(
            x=hourly["heure"],
            y=limit_line,
            mode="lines",
            line={"width": 0, "color": PLOTLY_COLORS["alert"]},
            fill="tonexty",
            fillcolor="rgba(231, 111, 81, 0.18)",
            hoverinfo="skip",
            showlegend=False,
        )
    )
    figure.add_trace(
        go.Scatter(
            x=hourly["heure"],
            y=hourly["demande_kw"],
            mode="lines+markers",
            name="Demande du quartier",
            line={"color": PLOTLY_COLORS["green_700"], "width": 3},
            marker={"color": PLOTLY_COLORS["green_500"], "size": 6},
        )
    )
    figure.add_hline(
        y=GRID_LIMIT_KW,
        line_dash="dash",
        line_color=PLOTLY_COLORS["text"],
        annotation_text="Limite réseau",
        annotation_position="top left",
    )
    figure.update_layout(
        xaxis_title="Heure",
        yaxis_title="Puissance (kW)",
        xaxis={"dtick": 1, "range": [0, 23], "gridcolor": "rgba(11, 61, 46, 0.08)"},
        yaxis={"gridcolor": "rgba(11, 61, 46, 0.08)"},
        height=430,
        margin={"l": 20, "r": 20, "t": 45, "b": 20},
        paper_bgcolor="rgba(0, 0, 0, 0)",
        plot_bgcolor="rgba(0, 0, 0, 0)",
        font={"family": "Inter, sans-serif", "color": PLOTLY_COLORS["text"]},
        legend={"orientation": "h", "y": 1.08},
    )
    return figure


def resource_card(title: str, detail: str, badge: str | None = None) -> None:
    st.markdown(f'<div class="resource-title">{escape(title)}</div>', unsafe_allow_html=True)
    if badge:
        st.markdown(badge, unsafe_allow_html=True)
    st.markdown(f'<div class="resource-meta">{escape(detail)}</div>', unsafe_allow_html=True)


st.title("iDER | Orchestration énergétique")
st.caption("Données de simulation du quartier · lecture directe de SQLite")

available_scenarios = read_query("SELECT DISTINCT scenario FROM measurements ORDER BY scenario")
if available_scenarios.empty:
    st.error("Aucune mesure disponible. Lancez d'abord `python backend/generate_dataset.py` puis `python backend/simulation.py`.")
    st.stop()

scenario_options = [scenario for scenario in SCENARIOS if scenario in available_scenarios["scenario"].tolist()]
with st.sidebar:
    st.markdown('<div class="ider-brand">iDER</div>', unsafe_allow_html=True)
    st.markdown('<div class="ider-brand-note">Orchestration énergétique distribuée</div>', unsafe_allow_html=True)
    st.divider()
    selected_scenario = st.selectbox("Scénario", scenario_options, format_func=lambda value: value.capitalize())
available_days = read_query(
    "SELECT DISTINCT jour FROM measurements WHERE scenario = ? ORDER BY jour",
    (selected_scenario,),
)
day_options = available_days["jour"].astype(int).tolist()
with st.sidebar:
    selected_day = st.selectbox("Jour", day_options, format_func=lambda value: f"Jour {value}")
    st.markdown(
        """
        <div class="ider-legend">
          <div class="legend-line"><span class="legend-dot" style="background:var(--green-500)"></span>Vert : ressources DER</div>
          <div class="legend-line"><span class="legend-dot" style="background:var(--alert)"></span>Corail : dépassement réseau</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

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
    overview_metrics = [
        {"label": "DER modélisées", "value": f"{MAISONS_AVEC_PV + MAISONS_AVEC_BATTERIE + MAISONS_AVEC_EV + NB_MAISONS}"},
        {"label": "Puissance PV max observée", "value": f"{pv_capacity_estimate:.1f} kW"},
        {"label": "Capacité batterie totale", "value": f"{MAISONS_AVEC_BATTERIE * BATTERY_CAPACITY_KWH:.0f} kWh"},
        {"label": "Véhicules électriques", "value": f"{len(ev_houses)}"},
        {
            "label": "Demande au pic du jour",
            "value": f"{measured_peak:.1f} kW",
            "delta": f"{measured_peak - GRID_LIMIT_KW:+.1f} kW vs limite",
            "delta_color": "inverse",
        },
    ]
    if not kpi.empty:
        kpi_row = kpi.iloc[0]
        before = float(kpi_row["pic_avant_kw"])
        after = float(kpi_row["pic_apres_kw"])
        reduction = ((before - after) / before * 100.0) if before else 0.0
        overview_metrics.extend(
            [
                {"label": "Réduction de pic enregistrée", "value": f"{reduction:.1f}%"},
                {"label": "Économie estimée enregistrée", "value": f"{float(kpi_row['economie_estimee_eur']):.2f} €"},
            ]
        )
        if abs(before - measured_peak) > 1.0:
            st.markdown(
                f'<div class="sandbox-note">Écart entre les mesures agrégées ({measured_peak:.2f} kW) et le pic KPI enregistré ({before:.4f} kW).</div>',
                unsafe_allow_html=True,
            )
    else:
        overview_metrics.append({"label": "KPI enregistrés", "value": "Indisponibles"})
    render_metric_grid(overview_metrics)
    st.caption("La puissance PV est estimée depuis les maxima observés; le dataset ne stocke pas la puissance nominale constructeur.")

with resources_tab:
    pv_tab, battery_tab, ev_tab, hvac_tab = st.tabs(["PV", "Batteries", "VE", "HVAC"])
    with pv_tab:
        st.caption(f"{len(pv_houses)} maisons avec production photovoltaïque observée")
        for start in range(0, len(pv_houses), 4):
            columns = st.columns(4)
            for column, row in zip(columns, pv_houses.iloc[start : start + 4].itertuples()):
                with column:
                    with st.container(border=True):
                        resource_card(row.house_id, f"Puissance PV max observée · {row.pv_kw:.2f} kW")
    with battery_tab:
        st.caption("SOC de fin de journée et cumul des décharges enregistrées par batterie.")
        for start in range(0, len(battery_houses), 4):
            columns = st.columns(4)
            for column, row in zip(columns, battery_houses.iloc[start : start + 4].itertuples()):
                soc_color = "var(--green-700)" if row.battery_soc >= 65 else "var(--green-300)"
                with column:
                    with st.container(border=True):
                        resource_card(f"{row.device_id} · {row.house_id}", f"Stress d'équité · {row.stress_score_kwh:.2f} kWh")
                        st.markdown(
                            f'<div class="soc-track" role="progressbar" aria-valuenow="{row.battery_soc:.0f}" aria-valuemin="0" aria-valuemax="100"><div class="soc-fill" style="width:{min(100, max(0, row.battery_soc)):.1f}%;background:{soc_color}"></div></div><div class="resource-meta">SOC · {row.battery_soc:.1f}%</div>',
                            unsafe_allow_html=True,
                        )
    with ev_tab:
        for start in range(0, len(ev_houses), 4):
            columns = st.columns(4)
            for column, row in zip(columns, ev_houses.iloc[start : start + 4].itertuples()):
                badge_class = "status-badge" if row.ev_connected else "status-muted"
                state = "Connecté" if row.ev_connected else "Déconnecté"
                with column:
                    with st.container(border=True):
                        resource_card(
                            f"{row.device_id} · {row.house_id}",
                            f"SOC · {row.ev_soc:.1f}% · départ prévu {EV_DEPART_MOYEN_H} h",
                            f'<span class="{badge_class}">{state}</span>',
                        )
    with hvac_tab:
        for start in range(0, len(house_inventory), 4):
            columns = st.columns(4)
            for column, row in zip(columns, house_inventory.iloc[start : start + 4].itertuples()):
                with column:
                    with st.container(border=True):
                        resource_card(row.house_id, f"Puissance HVAC observée · {row.hvac_kw:.2f} kW")

with grid_tab:
    st.subheader("Demande horaire agrégée")
    figure = build_grid_figure(hourly)
    st.plotly_chart(figure, width="stretch")
    st.caption(f"Pic mesuré : {measured_peak:.2f} kW à {peak_hour:02d} h. Les puissances sont agrégées par somme des maisons, en kW.")

with orchestrator_tab:
    with st.container(border=True):
        st.subheader("Sandbox · simulation what-if")
        st.markdown(
            '<div class="sandbox-note">Le plan est recalculé en direct avec la limite choisie. Cette simulation what-if ne modifie aucune mesure ni aucun résultat enregistré.</div>',
            unsafe_allow_html=True,
        )
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
        st.dataframe(sandbox_plan, width="stretch", hide_index=True)

    st.subheader("Journal des actions enregistrées")
    if actions.empty:
        st.caption("Aucune action enregistrée pour cette sélection.")
    else:
        for action in actions.itertuples():
            resource_class = {
                "battery": "timeline-battery",
                "ev": "timeline-ev",
                "hvac": "timeline-hvac",
            }.get(action.device_type, "timeline-battery")
            justification = escape(str(action.justification))
            detail = escape(f"{action.device_id} · {action.action_type} · {abs(action.power_kw):.2f} kW")
            with st.container(border=True):
                st.markdown(
                    f'<div class="timeline-entry {resource_class}"><div class="timeline-hour">{int(action.heure):02d}:00</div><div class="timeline-detail">{detail}</div><p class="timeline-justification">{justification}</p></div>',
                    unsafe_allow_html=True,
                )

with results_tab:
    st.subheader("Résultats du jour sélectionné")
    if kpi.empty:
        st.caption("Aucun KPI disponible en base pour cette sélection.")
    else:
        kpi_row = kpi.iloc[0]
        before = float(kpi_row["pic_avant_kw"])
        after = float(kpi_row["pic_apres_kw"])
        reduction = ((before - after) / before * 100.0) if before else 0.0
        cards = st.columns(3)
        with cards[0]:
            with st.container(border=True):
                st.metric("Pic avant enregistré", f"{before:.2f} kW")
        with cards[1]:
            with st.container(border=True):
                st.metric("Pic après enregistré", f"{after:.2f} kW", delta=f"{after - before:+.2f} kW", delta_color="inverse")
        with cards[2]:
            with st.container(border=True):
                st.metric("Réduction enregistrée", f"{reduction:.1f}%", delta=f"{reduction:+.1f}%")

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
        scenario_order = {"normal": 0, "nuageux": 1, "canicule": 2}
        scenario_peaks["order"] = scenario_peaks["scenario"].map(scenario_order)
        scenario_peaks = scenario_peaks.sort_values("order")
        scenario_colors = {
            "normal": PLOTLY_COLORS["green_500"],
            "nuageux": PLOTLY_COLORS["green_300"],
            "canicule": PLOTLY_COLORS["green_700"],
        }
        bar = go.Figure(
            go.Bar(
                x=scenario_peaks["scenario"],
                y=scenario_peaks["peak_kw"],
                marker_color=[scenario_colors[scenario] for scenario in scenario_peaks["scenario"]],
                text=scenario_peaks["peak_kw"].map(lambda value: f"{value:.1f} kW"),
                textposition="outside",
            )
        )
        bar.add_hline(y=GRID_LIMIT_KW, line_dash="dash", line_color=PLOTLY_COLORS["text"], annotation_text="Limite 150 kW")
        bar.update_layout(
            title="Pic agrégé maximal par scénario",
            yaxis_title="Puissance (kW)",
            height=380,
            margin={"l": 20, "r": 20, "t": 60, "b": 20},
            paper_bgcolor="rgba(0, 0, 0, 0)",
            plot_bgcolor="rgba(0, 0, 0, 0)",
            font={"family": "Inter, sans-serif", "color": PLOTLY_COLORS["text"]},
            xaxis={"gridcolor": "rgba(11, 61, 46, 0.08)"},
            yaxis={"gridcolor": "rgba(11, 61, 46, 0.08)"},
        )
        st.plotly_chart(bar, width="stretch")

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
        st.dataframe(kpi_table, width="stretch", hide_index=True)