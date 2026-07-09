"""Build compact per-match team-xG files from the vaastav FPL dataset.

Downloads per-gameweek player data (which carries FPL's official
expected_goals per player per match), sums it to team level per fixture,
and writes one small CSV per season to ``data/xg-SEASON.csv``:

    date,home,away,hg,ag,hxg,axg

Team names are normalised to the plsim canonical names so the
calibration can join them to the openfootball match records. Run
whenever the season's data needs refreshing (the weekly workflow does).
"""

import csv
import io
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SEASONS = ("2023-24", "2024-25", "2025-26")
BASE = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"

# FPL bootstrap team names -> plsim canonical names (clubs seen 2023-26)
FPL_NAMES = {
    "Arsenal": "Arsenal", "Aston Villa": "Aston Villa",
    "Bournemouth": "Bournemouth", "Brentford": "Brentford",
    "Brighton": "Brighton", "Chelsea": "Chelsea", "Everton": "Everton",
    "Fulham": "Fulham", "Liverpool": "Liverpool", "Man City": "Manchester City",
    "Man Utd": "Manchester United", "Newcastle": "Newcastle United",
    "Nott'm Forest": "Nottingham Forest", "Spurs": "Tottenham Hotspur",
    "Crystal Palace": "Crystal Palace", "Wolves": "Wolves",
    "West Ham": "West Ham", "Burnley": "Burnley", "Luton": "Luton",
    "Sheffield Utd": "Sheffield United", "Ipswich": "Ipswich Town",
    "Leicester": "Leicester", "Southampton": "Southampton",
    "Leeds": "Leeds United", "Sunderland": "Sunderland",
}


def fetch_csv(url):
    with urllib.request.urlopen(url, timeout=120) as resp:
        return list(csv.DictReader(io.TextIOWrapper(resp, encoding="utf-8")))


def build_season(season):
    teams = {int(r["id"]): FPL_NAMES.get(r["name"], r["name"])
             for r in fetch_csv(f"{BASE}/{season}/teams.csv")}
    fixtures = {}
    for r in fetch_csv(f"{BASE}/{season}/fixtures.csv"):
        if not r.get("finished") or r["finished"].lower() != "true":
            continue
        fixtures[int(r["id"])] = {
            "date": (r.get("kickoff_time") or "")[:10],
            "home": teams[int(r["team_h"])], "away": teams[int(r["team_a"])],
            "hg": int(r["team_h_score"]), "ag": int(r["team_a_score"]),
            "hxg": 0.0, "axg": 0.0,
        }
    rows = fetch_csv(f"{BASE}/{season}/gws/merged_gw.csv")
    for r in rows:
        try:
            fid = int(r["fixture"])
            xg = float(r.get("expected_goals") or 0.0)
        except (KeyError, ValueError):
            continue
        fx = fixtures.get(fid)
        if fx is None:
            continue
        side = "hxg" if r.get("was_home", "").lower() == "true" else "axg"
        fx[side] += xg
    out = os.path.join("data", f"xg-{season}.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "home", "away", "hg", "ag", "hxg", "axg"])
        for fx in sorted(fixtures.values(), key=lambda f: f["date"]):
            w.writerow([fx["date"], fx["home"], fx["away"], fx["hg"], fx["ag"],
                        f"{fx['hxg']:.2f}", f"{fx['axg']:.2f}"])
    print(f"{out}: {len(fixtures)} matches "
          f"(from {len(rows)} player-gameweek rows)")


if __name__ == "__main__":
    for season in sys.argv[1:] or SEASONS:
        build_season(season)
