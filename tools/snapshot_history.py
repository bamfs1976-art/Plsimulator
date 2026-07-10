"""Append this week's headline odds to data/history.json.

Runs a seeded 10,000-season Monte Carlo with the current calibrated
ratings and real fixtures, and appends each club's title and relegation
probability (plus ratings) with today's date. The weekly workflow calls
this after recalibrating, so the site accumulates a season-long record
of how the odds moved — the raw material for the title-race chart.
Keeps at most the last 60 snapshots; replaces same-day entries so
reruns are idempotent.
"""

import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plsim import models, simulate  # noqa: E402
from plsim.fixtures import get_fixtures  # noqa: E402
from plsim.teams import load_ratings  # noqa: E402

PATH = os.path.join("data", "history.json")
SIMS = 10000
SEED = 20262027


def main():
    teams, meta = load_ratings("teams_calibrated.json")
    model = models.make_model("poisson", teams)
    matchdays, _dates, _src = get_fixtures(list(teams))
    agg = simulate.monte_carlo(model, matchdays, list(teams), SIMS,
                               seed=SEED, dixon_coles=True,
                               rho=meta.get("rho"))
    today = datetime.date.today().isoformat()
    entry = {"date": today, "clubs": {}}
    for t in teams:
        entry["clubs"][t] = {
            "title": round(100 * agg.prob_champion(t), 2),
            "top4": round(100 * agg.prob_top4(t), 2),
            "rel": round(100 * agg.prob_relegated(t), 2),
        }
    history = []
    if os.path.exists(PATH):
        with open(PATH, encoding="utf-8") as fh:
            history = json.load(fh)
    history = [h for h in history if h["date"] != today]
    history.append(entry)
    history = history[-60:]
    with open(PATH, "w", encoding="utf-8") as fh:
        json.dump(history, fh, indent=1)
        fh.write("\n")
    print(f"{PATH}: {len(history)} snapshots (latest {today})")


if __name__ == "__main__":
    main()
