"""Streamlit dashboard for the Premier League 2026/27 simulator.

Run with:  streamlit run dashboard.py
Requires:  pip install streamlit  (the CLI itself stays dependency-free)
"""

import json
import os
import random

import altair as alt
import pandas as pd
import streamlit as st

from plsim import models, simulate
from plsim.fixtures import generate_fixtures, matchday_date
from plsim.table import LeagueTable
from plsim.teams import load_teams

BLUE = "#2a78d6"    # primary series (validated palette slot 1)
AQUA = "#1baf7a"    # second sequential context (slot 2)

st.set_page_config(page_title="PL 2026/27 Simulator", page_icon="⚽", layout="wide")
st.title("Premier League 2026/27 Simulator")


# ------------------------------------------------------------- sidebar

st.sidebar.header("Model")
uploaded = st.sidebar.file_uploader("Ratings JSON (optional)", type="json",
                                    help="Override the built-in ratings, e.g. "
                                         "the output of `plsim calibrate`.")
use_calibrated = False
if uploaded is None and os.path.exists("teams_calibrated.json"):
    use_calibrated = st.sidebar.checkbox(
        "Use teams_calibrated.json", value=False,
        help="Ratings fitted from 2023-26 results by `plsim calibrate`.")

model_name = st.sidebar.selectbox("Prediction model", ("poisson", "elo"),
                                  format_func=lambda m: {
                                      "poisson": "Poisson attack/defence",
                                      "elo": "Elo-based"}[m])
dixon_coles = st.sidebar.checkbox("Dixon-Coles low-score correction", value=True)
noise = st.sidebar.slider("Season strength noise (σ)", 0.0, 0.15, 0.0, 0.01,
                          help="Per-season log-normal perturbation of team "
                               "strength. Disables Dixon-Coles when > 0.")
seed = st.sidebar.number_input("Random seed", value=42, step=1)


def get_teams():
    if uploaded is not None:
        data = json.load(uploaded)
        uploaded.seek(0)
        return data
    if use_calibrated:
        return load_teams("teams_calibrated.json")
    return load_teams()


teams = get_teams()
team_names = list(teams)
matchdays = generate_fixtures(team_names)
model = models.make_model(model_name, teams)


@st.cache_data(show_spinner=False)
def run_montecarlo(n_sims, model_name, dixon_coles, noise, seed, teams_key):
    """Monte Carlo -> summary DataFrame + position matrix DataFrame."""
    mc_teams = json.loads(teams_key)
    mc_model = models.make_model(model_name, mc_teams)
    mc_matchdays = generate_fixtures(list(mc_teams))
    agg = simulate.monte_carlo(
        mc_model, mc_matchdays, list(mc_teams), n_sims,
        seed=seed, dixon_coles=dixon_coles, noise=noise,
    )
    rows, pos_rows = [], []
    for t in mc_teams:
        rows.append({
            "Team": t,
            "Title %": 100 * agg.prob_champion(t),
            "Top 4 %": 100 * agg.prob_top4(t),
            "Top 6 %": 100 * agg.prob_position_range(t, 1, 6),
            "Relegation %": 100 * agg.prob_relegated(t),
            "Avg pos": agg.mean_position(t),
            "Avg pts": agg.mean_points(t),
            "± pts": agg.std_points(t),
            "Min pts": agg.points_min[t],
            "Max pts": agg.points_max[t],
        })
        for pos, count in enumerate(agg.pos_counts[t], 1):
            pos_rows.append({"Team": t, "Position": pos,
                             "Probability": 100 * count / agg.n})
    summary = (pd.DataFrame(rows)
               .sort_values(["Title %", "Avg pos"], ascending=[False, True])
               .reset_index(drop=True))
    summary.index += 1
    return summary, pd.DataFrame(pos_rows)


def prob_bar(df, value_col, color, title):
    """Horizontal probability bar chart: one measure, one hue, tooltips."""
    return (
        alt.Chart(df, title=title)
        .mark_bar(color=color, cornerRadiusEnd=4, height={"band": 0.6})
        .encode(
            x=alt.X(value_col, type="quantitative",
                    title="probability (%)",
                    scale=alt.Scale(domainMin=0)),
            y=alt.Y("Team", type="nominal", sort="-x", title=None),
            tooltip=["Team",
                     alt.Tooltip(value_col, type="quantitative", format=".2f")],
        )
        .properties(height=420)
    )


tab_mc, tab_matchday, tab_season, tab_teams = st.tabs(
    ["Monte Carlo", "Matchday", "Full season", "Teams & ratings"])


# ---------------------------------------------------------- Monte Carlo

with tab_mc:
    col_a, col_b = st.columns([1, 3])
    with col_a:
        n_sims = st.select_slider(
            "Seasons to simulate",
            options=[1000, 2000, 5000, 10000, 20000, 50000, 100000,
                     250000, 500000, 1000000],
            value=10000)
        go = st.button("Run Monte Carlo", type="primary")
    if go or "mc_result" in st.session_state:
        params = (n_sims, model_name, dixon_coles, noise, int(seed),
                  json.dumps(teams, sort_keys=True))
        if go or st.session_state.get("mc_params") != params:
            with st.spinner(f"Simulating {n_sims:,} seasons..."):
                st.session_state.mc_result = run_montecarlo(*params)
                st.session_state.mc_params = params
        summary, pos_matrix = st.session_state.mc_result

        st.dataframe(
            summary.style.format({
                "Title %": "{:.2f}", "Top 4 %": "{:.2f}", "Top 6 %": "{:.2f}",
                "Relegation %": "{:.2f}", "Avg pos": "{:.2f}",
                "Avg pts": "{:.1f}", "± pts": "{:.1f}"}),
            use_container_width=True, height=740)

        left, right = st.columns(2)
        with left:
            st.altair_chart(
                prob_bar(summary[summary["Title %"] > 0.005], "Title %",
                         BLUE, "Title probability"),
                use_container_width=True)
        with right:
            st.altair_chart(
                prob_bar(summary[summary["Relegation %"] > 0.005],
                         "Relegation %", AQUA, "Relegation probability"),
                use_container_width=True)

        order = summary["Team"].tolist()
        heat = (
            alt.Chart(pos_matrix, title="Finishing position distribution (%)")
            .mark_rect(stroke="white", strokeWidth=1)
            .encode(
                x=alt.X("Position:O", title="finishing position"),
                y=alt.Y("Team:N", sort=order, title=None),
                color=alt.Color("Probability:Q",
                                scale=alt.Scale(scheme="blues"),
                                legend=alt.Legend(title="%")),
                tooltip=["Team", "Position",
                         alt.Tooltip("Probability:Q", format=".2f")],
            )
            .properties(height=560)
        )
        st.altair_chart(heat, use_container_width=True)
    else:
        st.info("Choose a simulation count and press **Run Monte Carlo**.")


# ------------------------------------------------------------- Matchday

with tab_matchday:
    md = st.slider("Matchday", 1, 38, 1)
    st.caption(f"Nominal date: {matchday_date(md):%A %d %B %Y}")
    rng = random.Random(int(seed) * 1000 + md)
    rows = []
    for home, away in matchdays[md - 1]:
        lam_h, lam_a = model.lambdas(home, away)
        grid = models.score_grid(lam_h, lam_a, dixon_coles)
        p_h, p_d, p_a = models.outcome_probs(grid)
        ml_h, ml_a = models.most_likely_score(grid)
        s_h, s_a = models.sample_score(models.cumulative(grid), rng)
        rows.append({
            "Home": home, "Away": away,
            "Home %": 100 * p_h, "Draw %": 100 * p_d, "Away %": 100 * p_a,
            "xG": f"{lam_h:.2f} - {lam_a:.2f}",
            "Most likely": f"{ml_h}-{ml_a}",
            "Simulated": f"{s_h}-{s_a}",
        })
    st.dataframe(
        pd.DataFrame(rows).style.format(
            {"Home %": "{:.1f}", "Draw %": "{:.1f}", "Away %": "{:.1f}"}),
        use_container_width=True, hide_index=True)
    st.caption("**Simulated** resamples when the seed or matchday changes.")


# ----------------------------------------------------------- Full season

with tab_season:
    if st.button("Simulate one season", type="primary"):
        rng = random.Random(int(seed))
        grids = simulate.fixture_grids(
            simulate.fixture_lambdas(model, matchdays), dixon_coles)
        table, results = simulate.simulate_season(grids, team_names, rng)
        st.session_state.season = (table, results)
    if "season" in st.session_state:
        table, results = st.session_state.season
        standings = table.standings()
        c1, c2, c3 = st.columns(3)
        c1.metric("Champions", standings[0])
        c2.metric("4th (last CL spot)", standings[3])
        c3.metric("Relegated", ", ".join(standings[-3:]))

        rows = []
        for pos, t in enumerate(standings, 1):
            r = table.rows[t]
            rows.append({"Pos": pos, "Team": t, "P": r["P"], "W": r["W"],
                         "D": r["D"], "L": r["L"], "GF": r["GF"],
                         "GA": r["GA"], "GD": r["GF"] - r["GA"],
                         "Pts": r["Pts"]})
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     hide_index=True, height=740)

        with st.expander("Matchday-by-matchday results"):
            show_md = st.slider("Show matchday", 1, 38, 1, key="md_results")
            running = LeagueTable(team_names)
            for m, home, away, hg, ag in results:
                if m <= show_md:
                    running.record(home, away, hg, ag)
            md_rows = [{"Home": h, "Score": f"{hg}-{ag}", "Away": a}
                       for m, h, a, hg, ag in results if m == show_md]
            st.dataframe(pd.DataFrame(md_rows), hide_index=True)
            st.text(running.render(title=f"Table after matchday {show_md}"))
    else:
        st.info("Press **Simulate one season** to play all 380 fixtures.")


# ------------------------------------------------------------------ Teams

with tab_teams:
    rows = [{"Team": t, "Attack": r["attack"], "Defence": r["defence"],
             "Elo": r["elo"]} for t, r in teams.items()]
    st.dataframe(
        pd.DataFrame(rows).sort_values("Elo", ascending=False),
        use_container_width=True, hide_index=True, height=740)
    st.caption(
        "Attack = scoring multiplier vs an average side (higher is better). "
        "Defence = conceding multiplier (lower is better). Elo drives the "
        "Elo model. Fit these from real 2023-26 results with "
        "`python3 -m plsim calibrate`, then tick *Use teams_calibrated.json*.")
