"""Weekly self-update: refresh results, refit ratings, re-embed the web app.

Run from the repo root (the scheduled GitHub Action does):

    python3 tools/weekly_update.py

Behaviour:
- Works out the three most relevant seasons from today's date (a season
  is YYYY-YY starting in July). If the newest season's openfootball
  files don't exist yet (pre-season), it falls back to the previous
  triple, so the job never breaks across the season rollover.
- Deletes the newest season's cached files so fresh results download.
- Runs the calibration and rewrites teams_calibrated.json.
- Re-embeds the ratings into index.html (the deployed web app).

Exits 0 whether or not anything changed; the workflow's git step
commits only when there is a diff.
"""

import datetime
import os
import subprocess
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plsim import calibrate as cal  # noqa: E402


def season_string(year):
    return f"{year}-{str(year + 1)[-2:]}"


def current_seasons(today=None):
    """The three seasons ending with the one in progress (or just done)."""
    today = today or datetime.date.today()
    start = today.year if today.month >= 7 else today.year - 1
    return [season_string(y) for y in (start - 2, start - 1, start)]


def refresh_newest(seasons, cache_dir="data"):
    """Drop the newest season's cache so new results are re-downloaded."""
    for division, fname in cal.DIVISION_FILES.items():
        path = os.path.join(cache_dir, f"{seasons[-1]}-{fname}")
        if os.path.exists(path):
            os.remove(path)
            print(f"refreshing {path}")


def main():
    seasons = current_seasons()
    refresh_newest(seasons)
    try:
        cal.fetch_file(seasons[-1], 1)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        # Newest season not published yet (pre-season): use the last
        # three completed seasons instead.
        print(f"{seasons[-1]} not available yet ({exc}); falling back")
        seasons = [season_string(int(s.split('-')[0]) - 1) for s in seasons]

    # Refresh team-xG files (best effort - a vaastav outage must not
    # break the weekly refit; the fit falls back to goals-only).
    try:
        subprocess.run([sys.executable, "tools/build_xg.py", *seasons[-2:]],
                       check=True, timeout=600)
    except Exception as exc:  # noqa: BLE001
        print(f"xG refresh skipped: {exc}")

    print(f"calibrating on: {', '.join(seasons)}")
    ratings, info = cal.calibrate(seasons=seasons)
    cal.write_ratings(ratings, "teams_calibrated.json", info)
    print(f"fitted {info['matches']} matches, rho {info['rho']:+.3f}")

    subprocess.run([sys.executable, "tools/snapshot_history.py"], check=True)
    subprocess.run([sys.executable, "tools/embed_calibrated.py"], check=True)
    print("done")


if __name__ == "__main__":
    main()
