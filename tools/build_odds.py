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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plsim import devig  # noqa: E402

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
        ph, pd, pa = devig.proportional([h, d, a])   # margin removed by normalisation
        (sh, sd, sa), _z = devig.shin([h, d, a])     # Shin de-vig (favourite-longshot aware)
        rows.append([r["date"].date().isoformat(),
                     NAME.get(r["home_team"], r["home_team"]),
                     NAME.get(r["away_team"], r["away_team"]),
                     f"{ph:.4f}", f"{pd:.4f}", f"{pa:.4f}",
                     f"{sh:.4f}", f"{sd:.4f}", f"{sa:.4f}",
                     f"{h:.3f}", f"{d:.3f}", f"{a:.3f}"])
    out = os.path.join("data", f"odds-{season}.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        # ph/pd/pa: proportional de-vig (backtest default, backward compatible).
        # sh/sd/sa: Shin de-vig. oh/od/oa: raw Pinnacle closing decimal odds.
        w.writerow(["date", "home", "away", "ph", "pd", "pa",
                    "sh", "sd", "sa", "oh", "od", "oa"])
        w.writerows(rows)
    print(f"{out}: {len(rows)} matches with Pinnacle closing odds (proportional + Shin)")


if __name__ == "__main__":
    for season in sys.argv[1:] or ["2023-24", "2024-25", "2025-26"]:
        build(season)
