# Premier League 2026/27 Simulator

A fast, zero-dependency Python simulator for the 2026/27 Premier League
season. Simulate individual matchdays, play out a full season fixture by
fixture, or run large Monte Carlo experiments (100,000+ seasons) to
estimate title, top-four and relegation probabilities.

## The 2026/27 season

The 20 clubs are the 17 survivors of 2025/26 plus the promoted
**Coventry City**, **Ipswich Town** and **Hull City** (replacing the
relegated West Ham, Burnley and Wolves). Team ratings ship as editable
estimates calibrated loosely to the 2025/26 final table (Arsenal champions
on 85 points, ahead of Manchester City, Manchester United and Aston Villa).

Fixtures are generated as a proper double round-robin (38 matchdays,
19 home / 19 away per club) with the Berger circle method — every club
plays every other club home and away, and no club appears twice in a
matchday.

## Requirements

Python 3.8+. The CLI needs nothing else — the standard library only.
The optional web dashboard needs `pip install streamlit`.

## Quick start

```bash
# The 20 teams and their ratings
python3 -m plsim teams

# The generated fixture calendar (or one matchday)
python3 -m plsim fixtures
python3 -m plsim fixtures --matchday 1

# Predict + simulate a single matchday: win/draw/loss %, expected goals,
# most likely score, and one sampled scoreline per fixture
python3 -m plsim matchday 1
python3 -m plsim matchday 1 --dixon-coles --seed 42

# Play one full season, matchday by matchday
python3 -m plsim season                 # every matchday's results + final table
python3 -m plsim season --tables 5      # also print the table every 5 matchdays
python3 -m plsim season --quiet         # final table only

# Monte Carlo: simulate many seasons, report outcome probabilities
python3 -m plsim montecarlo --sims 10000
python3 -m plsim montecarlo --sims 100000 --dixon-coles
python3 -m plsim montecarlo --sims 20000 --positions   # full 20x20 position matrix

# Fit ratings from real 2023-26 results, then simulate with them
python3 -m plsim calibrate
python3 -m plsim montecarlo --sims 50000 --teams teams_calibrated.json

# Score the model honestly: walk-forward backtest on a held-out season
python3 -m plsim backtest
python3 -m plsim backtest --every 4        # quick mode

# Interactive web dashboard (needs: pip install streamlit)
streamlit run dashboard.py
```

All commands accept `--seed N` for reproducible runs and
`--teams my_ratings.json` to override the built-in ratings.

## Prediction models

Pick with `--model {poisson,elo}` (default: `poisson`).

**Poisson attack/defence (`poisson`).** Each club has an attack and a
defence multiplier around a league-average baseline (1.62 home goals,
1.32 away goals per match). A fixture's expected goals are

```
λ_home = 1.62 × attack(home) × defence(away)
λ_away = 1.32 × attack(away) × defence(home)
```

and goals are drawn from independent Poisson distributions. Add
`--dixon-coles` to apply the Dixon & Coles (1997) correction, which fixes
the independent-Poisson bias on 0-0, 1-0, 0-1 and 1-1 scorelines.

**Elo (`elo`).** Converts the Elo gap between the sides (plus a 60-point
home bonus) into an expected result, then skews an average total-goals
budget toward the stronger club. Sharper favourites, useful as a
cross-check on the Poisson model.

**Season-strength noise (`--noise SIGMA`, Monte Carlo only).** Real
uncertainty isn't just match randomness — a club's true strength varies
season to season (transfers, injuries, managerial changes). With e.g.
`--noise 0.08`, every simulated season perturbs each club's attack and
defence rates by a log-normal factor before play begins, widening the
outcome distributions realistically. (Noise mode samples goals directly
from Poisson rates, so `--dixon-coles` is ignored there.)

## How high simulation counts stay fast

For each of the 380 fixtures the full scoreline probability grid
(0–10 goals each way) is computed once and stored as a cumulative
distribution; simulating a match is then a single binary search. Runs of
4,000+ seasons are automatically sharded across worker processes and the
per-worker aggregates merged. On a typical machine that yields **~10,000
seasons per second**, so a million-season run finishes in under two
minutes — no NumPy required. Control parallelism with `--workers N`.

## What the Monte Carlo run reports

Per club: title %, top-4 %, top-6 %, relegation %, mean finishing
position, mean points with standard deviation, and best/worst points
across all simulated seasons. `--positions` adds the full matrix of
P(club finishes in position k) for every position 1–20.

League tables use the Premier League tie-breakers (points, goal
difference, goals scored); head-to-head is approximated alphabetically,
which is statistically neutral across large runs.

## Backtesting: how accurate is it, really?

`python3 -m plsim backtest` answers the question honestly. For every
matchday of a held-out season (2025/26 by default) it refits each model
variant on strictly earlier matches only — cut off by real match date —
then predicts that matchday's fixtures and scores the predictions with
the ranked probability score (RPS), log-loss, Brier, and a clean-sheet
Brier. Walk-forward, exactly like live use; no peeking.

Measured on the 380 matches of 2025/26 (lower is better):

| Variant | RPS | Log-loss | CS Brier |
|---|---|---|---|
| uniform (1/3 each) | 0.2322 | 1.0986 | — |
| league H/D/A rates | 0.2276 | 1.0813 | — |
| Elo model | 0.2194 | 1.0633 | 0.1834 |
| Poisson, season-step weights | 0.2133 | 1.0410 | 0.1811 |
| **+ decay + fitted rho + home adv** | **0.2126** | **1.0377** | **0.1808** |

Blending FPL's official team xG into the fit target (`0.4*xG +
0.6*goals`, swept 0–1 through the harness) improves the full config to
**0.2123** with the best clean-sheet Brier (0.1802); pure xG is *worse*
than pure goals.

**Head to head with the market:** on the 210 matches of 2025/26 with
Pinnacle closing odds (de-vigged; from the football-data.co.uk mirror at
[AnishKhetani/premier-league-data](https://github.com/AnishKhetani/premier-league-data),
compacted by `tools/build_odds.py` into `data/odds-*.csv`), the model
scores RPS **0.2068** vs the market's **0.1994** — about 0.007 behind
the sharpest public forecast in existence, from goals + xG alone.
Blending model probabilities toward the market improves accuracy
monotonically but never beats pure closing odds, so the recommendation
is honest: when closing odds exist (i.e. at kickoff), defer to them;
the model's value is every horizon where odds don't exist yet —
multi-gameweek fixture planning, full scoreline grids (clean sheets,
3+ goals), and season-long Monte Carlo. The `backtest` command reports
this comparison automatically whenever the odds files are present.

**A negative result worth recording:** promoted clubs' first-PL-season
performance is dramatically below what a naive single-season joint fit
implies (attack ×0.59, defence ×1.57 — measured over 28 promoted-club
seasons, 2016–26; `calibrate.promoted_adjust` implements the
correction). But the walk-forward backtest **rejects** applying it here
— overall RPS worsens 0.2123 → 0.2213 and promoted-club matches worsen
0.2088 → 0.2403, with even quarter-strength versions losing. The
multi-season decay-weighted joint fit already prices promotion in;
the adjustment double-counts. It stays in the codebase as an opt-in
research finding for single-season fits, not a default. The backtest
drove three calibration choices now baked in as defaults: exponential
**date decay** with a 250-day half-life (beats longer half-lives, ties
season steps on the holdout, and keeps working mid-season), a
**maximum-likelihood Dixon-Coles rho** (the data says ~-0.07, milder
than the textbook -0.12), and **per-club home advantage** (mean 1.0,
shrunk toward neutral; e.g. Newcastle fit ~1.19 at home vs Forest ~0.79).

## Calibrating ratings from real results

`python3 -m plsim calibrate` fits all three rating columns from actual
match data instead of the hand-set defaults:

- **Source:** the public-domain
  [openfootball/england](https://github.com/openfootball/england) dataset —
  Premier League *and* Championship results for 2023-24, 2024-25 and
  2025-26 (2,796 matches). Files are cached in `data/` (committed here),
  so `--no-download` re-fits fully offline.
- **Attack/defence** come from a weighted iterative Poisson
  maximum-likelihood fit (`goals ~ base × attack(scorer) ×
  defence(conceder) × home(scorer if at home)`, separate home/away
  baselines). Both divisions are fitted **jointly**, so the promoted
  clubs' Championship goals are anchored to Premier League level through
  the clubs that moved between divisions. Matches decay exponentially by
  date (250-day half-life, backtest-validated), and each club's rating
  is shrunk toward league-average in proportion to its weighted match
  count.
- **Home** is each club's fitted home-advantage multiplier, shrunk
  toward 1.0 by 12 pseudo-matches.
- **Rho**, the Dixon-Coles correlation, is fitted by maximum likelihood
  and stored in the file's `_meta` block; every command reads it
  automatically when you pass `--teams`.
- **Elo** comes from a chronological Elo pass (K=24, +60 home) over the
  same matches. Note: a dominant Championship season inflates a promoted
  club's Elo more than its Poisson ratings, because Elo only sees
  win/loss while the joint Poisson fit prices in opponent quality — with
  calibrated ratings, prefer the default `poisson` model.

The output (`teams_calibrated.json`) plugs straight into any command via
`--teams`, and into the dashboard via its sidebar checkbox.

## Web dashboard

`streamlit run dashboard.py` (after `pip install streamlit`) opens an
interactive dashboard with four tabs: a Monte Carlo lab (up to 1,000,000
seasons, with title/relegation probability charts and a finishing-position
heatmap), a matchday explorer, a full-season player with
matchday-by-matchday tables, and the ratings view. The sidebar switches
model, Dixon-Coles, strength noise, seed, and ratings source (defaults,
`teams_calibrated.json`, or an uploaded JSON).

## Customising teams and ratings

Copy the ratings from `plsim/teams.py` into a JSON file, tweak, and pass
`--teams`:

```json
{
  "Arsenal": {"attack": 1.35, "defence": 0.70, "elo": 1900},
  "...": {"attack": 1.0, "defence": 1.0, "elo": 1700}
}
```

`attack` is a scoring multiplier vs an average side (higher = better),
`defence` a conceding multiplier (lower = better), `elo` the overall
rating used by the Elo model. Exactly 20 teams are required.

## Tests

```bash
python3 -m unittest discover tests
```

Covers fixture-list integrity (double round-robin, 19H/19A), probability
normalisation, model sanity, season bookkeeping consistency, and Monte
Carlo reproducibility under a fixed seed.

## Project layout

```
plsim/
  teams.py      # 2026/27 clubs + editable ratings, league baselines
  fixtures.py   # Berger-method double round-robin, 38 matchdays
  models.py     # Poisson & Elo models, Dixon-Coles, score grids
  table.py      # league table + PL tie-breakers
  simulate.py   # season simulation + multiprocess Monte Carlo engine
  calibrate.py  # rating fit: decay-weighted Poisson MLE, home adv, rho
  backtest.py   # walk-forward accuracy evaluation (RPS/log-loss/Brier)
  cli.py        # argparse CLI (teams/fixtures/matchday/season/
                #               montecarlo/calibrate/backtest)
dashboard.py    # Streamlit web dashboard (optional)
data/           # cached openfootball results used by `calibrate`
teams_calibrated.json  # pre-fitted ratings from 2023-26 results
tests/
  test_plsim.py
```
