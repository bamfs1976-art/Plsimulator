"""Compute recent team form from real results and embed it into index.html.

For every current Premier League club it summarises the last 5, 10 and 20
matches — overall, at home and away (W-D-L, goals, points, points-per-game)
— from the newest season that has been played. It also records the season
state (label, matchdays played, whether it is live) so the web app can show
"next N fixtures" projections and, once the season is under way, a live
table.

Between seasons this uses the most recently completed season; the moment
2026/27 results start landing (via the Monday recalibration job) it rolls
onto the new season automatically. Run from the repo root:

    python3 tools/build_form.py
"""

import datetime
import json
import os
import re
import sys

sys.path.insert(0, ".")

from plsim import calibrate as cal  # noqa: E402

WINDOWS = (5, 10, 20)


def season_string(year):
    return f"{year}-{str(year + 1)[-2:]}"


def current_seasons(today=None):
    today = today or datetime.date.today()
    start = today.year if today.month >= 7 else today.year - 1
    return [season_string(y) for y in (start - 2, start - 1, start)]


def played_matches(season, cache_dir="data"):
    """Played top-flight matches for a season, canonical names, ordered."""
    try:
        text = cal.fetch_file(season, 1, cache_dir=cache_dir, download=False)
    except Exception:
        return []
    out = []
    for md, date, home, away, hg, ag in cal.parse_matches(text, season):
        out.append({"md": md, "date": date,
                    "home": cal._canon(home), "away": cal._canon(away),
                    "hg": hg, "ag": ag})
    out.sort(key=lambda m: (m["md"], m["date"] or datetime.date.min))
    return out


def result_for(team, m):
    home = m["home"] == team
    gf, ga = (m["hg"], m["ag"]) if home else (m["ag"], m["hg"])
    res = "W" if gf > ga else "L" if gf < ga else "D"
    return {"venue": "H" if home else "A", "gf": gf, "ga": ga,
            "res": res, "pts": 3 if res == "W" else 1 if res == "D" else 0}


def agg(rows):
    n = len(rows)
    w = sum(1 for r in rows if r["res"] == "W")
    d = sum(1 for r in rows if r["res"] == "D")
    return {"p": n, "w": w, "d": d, "l": n - w - d,
            "gf": sum(r["gf"] for r in rows), "ga": sum(r["ga"] for r in rows),
            "pts": sum(r["pts"] for r in rows),
            "ppg": round(sum(r["pts"] for r in rows) / n, 2) if n else 0}


def windows(rows):
    return {str(k): agg(rows[-k:]) for k in WINDOWS}


def build(cache_dir="data"):
    with open("teams_calibrated.json", encoding="utf-8") as fh:
        teams = [t for t in json.load(fh) if t != "_meta"]
    seasons = current_seasons()
    season, matches = None, []
    for s in reversed(seasons):
        m = played_matches(s, cache_dir)
        if m:
            season, matches = s, m
            break
    form = {}
    max_md = max((m["md"] for m in matches), default=0)
    for team in teams:
        rows = [result_for(team, m) for m in matches if team in (m["home"], m["away"])]
        home = [r for r in rows if r["venue"] == "H"]
        away = [r for r in rows if r["venue"] == "A"]
        form[team] = {
            "played": len(rows),
            "season": agg(rows),
            "overall": windows(rows), "home": windows(home), "away": windows(away),
            "recent": [r["res"] for r in rows[-5:]],
        }
    label = ""
    if season:
        a, b = season.split("-")
        label = f"{a}/{b}"
    live = bool(season) and season == seasons[-1] and 0 < max_md < 38
    state = {"season": season or "", "label": label, "played_md": max_md,
             "teams": len(teams), "live": live,
             "updated": datetime.date.today().isoformat()}
    return form, state


def embed(form, state, path="index.html"):
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    block = ('<script id="form-data">\n'
             "/* Recent form + season state (tools/build_form.py) */\n"
             f"TEAM_FORM = {json.dumps(form)};\n"
             f"SEASON_STATE = {json.dumps(state)};\n</script>")
    html, n = re.subn(r'<script id="form-data">.*?</script>', block, html, flags=re.S)
    if n != 1:
        raise SystemExit("form-data block not found in index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)


if __name__ == "__main__":
    form, state = build()
    embed(form, state)
    played = sum(1 for f in form.values() if f["played"])
    print(f"form from {state['label'] or 'no'} season "
          f"({'live' if state['live'] else 'completed'}), "
          f"{played}/{len(form)} clubs with matches, "
          f"{state['played_md']} matchdays played")
