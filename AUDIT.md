# Plsimulator — App Audit & Enhancement Recommendations

*Audit date: 2026-07-12. Read-only audit of the codebase, benchmarked against world-class
prediction platforms (Opta Analyst / "supercomputer" league predictions, FiveThirtyEight-style
club ratings, ClubElo).*

## Verdict

The modelling core is genuinely strong — arguably publication-grade for a hobby project:
walk-forward backtesting with no leakage (`plsim/backtest.py`), honest benchmarking against
de-vigged Pinnacle closing odds (RPS 0.2068 vs market 0.1994), documented *rejected*
experiments, and a fully automated weekly recalibration pipeline (GitHub Actions →
`tools/weekly_update.py` → `model.json`). The gaps are almost all on the **product surface**:
the deployed site doesn't yet do the things a mature prediction product (e.g. Opta's league
predictor) treats as table stakes — conditioning on played results, a projected final table,
and a live self-scoring accuracy ledger.

## Key findings

### Bugs / correctness

1. **Fitted Dixon-Coles rho is silently unused in production.** `teams_calibrated.json._meta.rho`
   is -0.0841 (fitted by ML), but `index.html` hardcodes `DC_RHO = -0.074` and
   `tools/build_bundle.py:24` hardcodes the same stale constant into `model.json` instead of
   reading `meta["rho"]`. `hydrateFromBundle()` loads teams/fixtures/form but never
   `m.constants`. The CLI and dashboard use the fitted value; the deployed site does not.
   This is exactly the drift the shared-bundle design (commit e00d5e8) was meant to prevent.
2. **Season-odds Monte Carlo is not conditioned on played results.** Once 2026/27 kicks off,
   the headline title/relegation odds re-simulate all 38 matchdays from zero. Only the
   Scenario Lab (manual pinning) and `horizonStart()` respect real results. The flagship
   number will be wrong from matchday 1.
3. **Weak validation.** `plsim/teams.py:load_ratings` doesn't check numeric type/sign or the
   `home` key; `hydrateFromBundle` trusts `model.json` shape entirely — a malformed bundle
   fails silently.
4. **Dormant features at launch.** The title-race chart and movers need ≥2–3 weekly snapshots
   but `data/history.json` has one; they render empty with no explanation.
5. **Metadata drift.** Committed `teams_calibrated.json._meta` (seasons/match count from the
   weekly job) doesn't match the README/tests' described default fit — confusing without a note.
6. `requirements.txt` lists only `streamlit` though `dashboard.py` imports `altair`/`pandas`
   directly. Odds files (`tools/build_odds.py`) are built manually — not in the weekly
   pipeline — so the market benchmark goes stale across seasons. No CI on PRs (tests only run
   in the scheduled recalibrate job).

### Comparison vs world-class (Opta Analyst league predictor et al.)

| Capability | Opta-class product | Plsimulator today |
|---|---|---|
| Conditioned on season-to-date results | Yes, core | No (pre-season only) |
| Projected final table (xPts, position bands) | Headline view | Only single random season |
| Live accuracy track record | Published weekly | Static backtest numbers hardcoded in the Accuracy tab |
| Per-match "why" explanation | Ratings/form breakdown | Raw λ / most-likely score only |
| Update cadence | After every round | Weekly (automated — good) |
| Offline / installable | N/A (media sites) | No manifest, no service worker |

## Top 10 recommendations (ranked by impact)

1. **Condition the Monte Carlo on played results.** Pin real 2026/27 scores (already parsed
   for the form tab) into the fixture grids before simulating. This is the single most
   important fix — without it the headline output is wrong all season.
2. **Fix the rho drift.** `build_bundle.py` should emit `meta["rho"]` into `model.json`
   `constants`, and `hydrateFromBundle` should apply `m.constants.DC_RHO`.
3. **Live accuracy ledger.** Log each week's forecasts, score them (RPS/Brier) as results
   land, and render a rolling track record vs the market. Nothing builds credibility for a
   prediction product like a self-updating scoreboard — this is what separates trusted
   forecasters from tipsters.
4. **Projected final-table view** — expected points, most-likely position, and
   title/UCL/relegation bands per club, conditioned on live state.
5. **PWA basics** — manifest, `theme-color`, service worker caching the shell + last
   `model.json`. Cheap, and the check-it-weekly usage pattern wants it.
6. **CI on push/PR** running `python3 -m unittest discover tests`.
7. **Validate inputs** — schema-check `model.json` client-side; tighten `load_ratings`.
8. **Automate `build_odds.py`** into `weekly_update.py` (or document the manual step).
9. **Handle dormant chart states** — show "collecting weekly snapshots (1 of 3)" instead of
   empty charts until history accumulates.
10. **ARIA tabs + shareable URLs** — `role=tablist/tab/aria-selected`; encode
    tab/seed/scenario in the URL so results are deep-linkable (and add OG tags).

## Cross-app opportunity

`model.json` is already consumed by Gameweek Edge. Formalise it: version the schema, include
`constants` (rho, baselines), publish a changelog, and treat this repo as the model service
for the whole suite (Gameweek Edge fixtures/xP, Bookings Desk fixture heat).
