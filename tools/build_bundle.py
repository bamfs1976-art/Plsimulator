"""Assemble model.json — the single machine-readable model bundle.

Both the standalone simulator and Gameweek Edge consume this one file, so the
fitted ratings, official fixtures, recent form and season state never drift
between the two products. Written to the repo root and served by Netlify at
https://plsimulation.netlify.app/model.json (with a permissive CORS header,
see netlify.toml). Refreshed weekly by tools/weekly_update.py.

    python3 tools/build_bundle.py
"""

import datetime
import json
import os
import sys

sys.path.insert(0, ".")

from plsim.fixtures import load_real_fixtures  # noqa: E402
from tools import build_form  # noqa: E402

# Model constants exactly as the deployed simulator uses them, so any consumer
# reproduces identical numbers. The fitted Dixon-Coles rho also travels in meta.
CONSTANTS = {"BASE_H": 1.62, "BASE_A": 1.32, "DC_RHO": -0.074,
             "ELO_HOME": 60, "ELO_SCALE": 0.45}


def build():
    with open("teams_calibrated.json", encoding="utf-8") as fh:
        ratings = json.load(fh)
    meta = ratings.pop("_meta", {})
    names = list(ratings)
    real = load_real_fixtures(names)
    fixtures = real[0] if real else None
    form, state = build_form.build()
    odds = None
    if os.path.exists("data/history.json"):
        with open("data/history.json", encoding="utf-8") as fh:
            odds = json.load(fh)
    return {
        "version": datetime.date.today().isoformat(),
        "constants": dict(CONSTANTS),
        "teams": ratings,
        "fixtures": fixtures,
        "form": form,
        "season_state": state,
        "odds_history": odds,
        "meta": meta,
    }


if __name__ == "__main__":
    bundle = build()
    with open("model.json", "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, separators=(",", ":"))
    print(f"model.json: {len(bundle['teams'])} teams, "
          f"{'official fixtures' if bundle['fixtures'] else 'no fixtures'}, "
          f"form {bundle['season_state'].get('label') or 'n/a'}, "
          f"{os.path.getsize('model.json')} bytes")
