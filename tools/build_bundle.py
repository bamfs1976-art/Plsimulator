"""Assemble model.json — the single machine-readable model bundle.

The standalone simulator, Gameweek Edge and the PL Bookings Desk all consume
this one file, so the fitted ratings, official fixtures, recent form and
season state never drift between the products. Written to the repo root and
served by Netlify at https://plsimulation.netlify.app/model.json (with a
permissive CORS header, see netlify.toml). Refreshed weekly by
tools/weekly_update.py.

    python3 tools/build_bundle.py

Beyond the ratings/fixtures/form core, the bundle carries:

- ``fixture_dates``: matchday number -> ISO date of the matchday's first
  fixture (official calendar only).
- ``stakes``: per-club season-outcome probabilities (title, top-4, top-6,
  relegation, mean position, mean points) from a seeded Monte Carlo run,
  conditioned on the results so far, so consumers can weight late-season
  fixtures by what is riding on them without running their own simulations.
- ``referees``: the week's match-official assignments when
  data/referees.json is present (see tools/build_refs.py).
"""

import datetime
import json
import os
import sys

sys.path.insert(0, ".")

from plsim import models, simulate  # noqa: E402
from plsim.fixtures import load_real_fixtures  # noqa: E402
from tools import build_form  # noqa: E402

# Model constants exactly as the deployed simulator uses them, so any consumer
# reproduces identical numbers. DC_RHO here is only a fallback: the fitted
# Dixon-Coles rho from teams_calibrated.json's _meta overrides it in build().
CONSTANTS = {"BASE_H": 1.62, "BASE_A": 1.32, "DC_RHO": -0.074,
             "ELO_HOME": 60, "ELO_SCALE": 0.45}

# The season whose fixture list (and played results) the bundle carries.
FIXTURE_SEASON = "2026-27"

# Seeded so the published stakes are reproducible run to run; enough sims
# that every probability is stable to well under a percentage point.
STAKES_SIMS = 20_000
STAKES_SEED = 20262027


def season_stakes(ratings, meta, fixtures, results=None):
    """Per-club title/top-4/top-6/relegation odds from a seeded Monte Carlo,
    conditioned on the results played so far (so it matches the live site)."""
    if not fixtures:
        return None
    names = list(ratings)
    model = models.PoissonModel(ratings)
    rho = meta.get("rho", CONSTANTS["DC_RHO"])
    agg = simulate.monte_carlo(model, fixtures, names, STAKES_SIMS,
                               seed=STAKES_SEED, dixon_coles=True, rho=rho,
                               results=results)
    clubs = {
        t: {
            "title": round(agg.prob_champion(t), 4),
            "top4": round(agg.prob_top4(t), 4),
            "top6": round(agg.prob_position_range(t, 1, 6), 4),
            "rel": round(agg.prob_relegated(t), 4),
            "pos": round(agg.mean_position(t), 2),
            "pts": round(agg.mean_points(t), 1),
        }
        for t in names
    }
    return {"sims": STAKES_SIMS, "seed": STAKES_SEED, "model": "poisson",
            "dixon_coles": True, "rho": rho,
            "conditioned_on": len(results or []), "clubs": clubs}


def load_referees(names):
    """Validated referee assignments from data/referees.json, or None.

    Entries whose clubs aren't in the current 20 are dropped rather than
    failing the whole bundle — a stale file must not break the weekly build.
    """
    path = "data/referees.json"
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    known = set(names)
    matches = [m for m in data.get("matches", [])
               if m.get("home") in known and m.get("away") in known
               and m.get("ref")]
    if not matches:
        return None
    return {"updated": data.get("updated"), "matches": matches}


def build():
    with open("teams_calibrated.json", encoding="utf-8") as fh:
        ratings = json.load(fh)
    meta = ratings.pop("_meta", {})
    constants = dict(CONSTANTS)
    rho = meta.get("rho")
    if isinstance(rho, (int, float)) and not isinstance(rho, bool):
        constants["DC_RHO"] = rho
    names = list(ratings)
    real = load_real_fixtures(names, season=FIXTURE_SEASON)
    fixtures = real[0] if real else None
    fixture_dates = ({str(md): d.isoformat() for md, d in real[1].items()}
                     if real else None)
    form, state = build_form.build()
    results = played_results(names)
    odds = None
    if os.path.exists("data/history.json"):
        with open("data/history.json", encoding="utf-8") as fh:
            odds = json.load(fh)
    ledger = None
    if os.path.exists("data/ledger.json"):
        with open("data/ledger.json", encoding="utf-8") as fh:
            ledger = json.load(fh)
    calibration = None
    if os.path.exists("data/calibration.json"):
        with open("data/calibration.json", encoding="utf-8") as fh:
            calibration = json.load(fh)
    return {
        "version": datetime.date.today().isoformat(),
        "constants": constants,
        "teams": ratings,
        "fixtures": fixtures,
        "fixture_dates": fixture_dates,
        "form": form,
        "season_state": state,
        "stakes": season_stakes(ratings, meta, fixtures, results),
        "referees": load_referees(names),
        "odds_history": odds,
        "results": results,
        "ledger": ledger,
        "calibration": calibration,
        "meta": meta,
    }


def played_results(names):
    """Played FIXTURE_SEASON matches with scores, for conditioning the MC.

    Returns a list of {md, home, away, hg, ag} (empty pre-season), so
    consumers can pin the real results into the season simulation and
    only simulate what is still to play.
    """
    known = set(names)
    return [
        {"md": m["md"], "home": m["home"], "away": m["away"],
         "hg": m["hg"], "ag": m["ag"]}
        for m in build_form.played_matches(FIXTURE_SEASON)
        if m["home"] in known and m["away"] in known
    ]


if __name__ == "__main__":
    bundle = build()
    with open("model.json", "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, separators=(",", ":"))
    print(f"model.json: {len(bundle['teams'])} teams, "
          f"{'official fixtures' if bundle['fixtures'] else 'no fixtures'}, "
          f"form {bundle['season_state'].get('label') or 'n/a'}, "
          f"{os.path.getsize('model.json')} bytes")
