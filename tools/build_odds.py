"""Write compact de-vigged closing-odds files for the backtest benchmark.

Uses the pip package from github.com/AnishKhetani/premier-league-data
(football-data.co.uk mirror with opening/closing odds). Output:
``data/odds-SEASON.csv`` with columns date,home,away,ph,pd,pa — Pinnacle
closing 1x2 odds converted to fair probabilities (vig removed by
normalisation). Team names are plsim-canonical.

    pip install "git+https://github.com/AnishKhetani/premier-league-data"
    python3 tools/build_odds.py 2023-24 2024-25 2025-26
"""

import csv
import os
import sys

NAME = {"Man City": "Manchester City", "Man United": "Manchester United",
        "Man Utd": "Manchester United", "Newcastle": "Newcastle United",
        "Nott'm Forest": "Nottingham Forest", "Tottenham": "Tottenham Hotspur",
        "Spurs": "Tottenham Hotspur", "Leeds": "Leeds United"}


def build(season):
    import premier_league_data as plodds

    odds = plodds.load_results_with_odds(season)
    rows = []
    for _, r in odds.iterrows():
        h = r.get("pinnacle_1x2_home_close")
        d = r.get("pinnacle_1x2_draw_close")
        a = r.get("pinnacle_1x2_away_close")
        if not h or not d or not a or h != h or d != d or a != a:
            continue
        inv = 1 / h + 1 / d + 1 / a
        rows.append([r["date"].date().isoformat(),
                     NAME.get(r["home_team"], r["home_team"]),
                     NAME.get(r["away_team"], r["away_team"]),
                     f"{1 / h / inv:.4f}", f"{1 / d / inv:.4f}",
                     f"{1 / a / inv:.4f}"])
    out = os.path.join("data", f"odds-{season}.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "home", "away", "ph", "pd", "pa"])
        w.writerows(rows)
    print(f"{out}: {len(rows)} matches with Pinnacle closing odds")


if __name__ == "__main__":
    for season in sys.argv[1:] or ["2023-24", "2024-25", "2025-26"]:
        build(season)
