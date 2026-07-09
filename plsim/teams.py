"""Team data for the 2026/27 Premier League season.

The 20 clubs: the 17 survivors of 2025/26 plus Coventry City, Ipswich Town
and Hull City (promoted), replacing West Ham, Burnley and Wolves (relegated).

Ratings are editable estimates calibrated loosely to the 2025/26 final table
(Arsenal champions on 85 pts, then Man City, Man Utd, Aston Villa):

- ``attack``  : goal-scoring multiplier vs a league-average side (1.0 = average)
- ``defence`` : goal-conceding multiplier (lower is better, 1.0 = average)
- ``elo``     : overall strength rating used by the Elo model

Override any of this by passing ``--teams path/to/teams.json`` to the CLI;
the JSON file must map team name -> {"attack": .., "defence": .., "elo": ..}.
"""

import json

DEFAULT_TEAMS = {
    "Arsenal":            {"attack": 1.35, "defence": 0.70, "elo": 1900},
    "Manchester City":    {"attack": 1.35, "defence": 0.76, "elo": 1875},
    "Liverpool":          {"attack": 1.26, "defence": 0.84, "elo": 1830},
    "Manchester United":  {"attack": 1.16, "defence": 0.85, "elo": 1815},
    "Chelsea":            {"attack": 1.18, "defence": 0.90, "elo": 1800},
    "Aston Villa":        {"attack": 1.12, "defence": 0.88, "elo": 1795},
    "Newcastle United":   {"attack": 1.12, "defence": 0.90, "elo": 1775},
    "Tottenham Hotspur":  {"attack": 1.10, "defence": 0.97, "elo": 1750},
    "Crystal Palace":     {"attack": 1.00, "defence": 0.90, "elo": 1740},
    "Brighton":           {"attack": 1.05, "defence": 0.98, "elo": 1735},
    "Nottingham Forest":  {"attack": 0.98, "defence": 0.95, "elo": 1715},
    "Bournemouth":        {"attack": 1.03, "defence": 1.00, "elo": 1710},
    "Brentford":          {"attack": 1.02, "defence": 1.04, "elo": 1700},
    "Fulham":             {"attack": 0.98, "defence": 1.00, "elo": 1695},
    "Everton":            {"attack": 0.90, "defence": 0.94, "elo": 1685},
    "Sunderland":         {"attack": 0.90, "defence": 1.05, "elo": 1650},
    "Leeds United":       {"attack": 0.92, "defence": 1.08, "elo": 1645},
    "Coventry City":      {"attack": 0.88, "defence": 1.12, "elo": 1600},
    "Ipswich Town":       {"attack": 0.85, "defence": 1.12, "elo": 1585},
    "Hull City":          {"attack": 0.80, "defence": 1.18, "elo": 1560},
}

# League-wide scoring baselines (goals per match for an average team).
BASE_HOME_GOALS = 1.62
BASE_AWAY_GOALS = 1.32


def load_ratings(path=None):
    """Return (teams dict, meta dict) from a ratings JSON file.

    ``meta`` comes from the file's optional ``_meta`` block (fitted
    Dixon-Coles rho, fit settings); it is empty for the built-in
    defaults. Each team may carry an optional ``home`` multiplier
    (per-club home advantage, 1.0 = league average).
    """
    if path is None:
        return {name: dict(r) for name, r in DEFAULT_TEAMS.items()}, {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    meta = data.pop("_meta", {})
    if len(data) != 20:
        raise ValueError(f"expected 20 teams, got {len(data)} in {path}")
    for name, r in data.items():
        for key in ("attack", "defence", "elo"):
            if key not in r:
                raise ValueError(f"team {name!r} in {path} is missing {key!r}")
    return data, meta


def load_teams(path=None):
    """Return the team ratings dict, optionally overridden from a JSON file."""
    return load_ratings(path)[0]
