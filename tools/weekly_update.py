"""Weekly self-update: refresh results, refit ratings, re-embed the web app.

Run from the repo root (the scheduled GitHub Action does):

    python3 tools/weekly_update.py

Behaviour:
- Works out the three most relevant seasons from today's date (a season
  is YYYY-YY starting in July). If the newest season's openfootball
  files don't exist yet (pre-season), it falls back to the previous
  triple, so the job never breaks across the season rollover.
- Deletes the newest season's cached files so fresh results download.
- Scores last week's forecasts (data/forecasts.json) against any newly
  played results and appends the aggregates to data/ledger.json — the
  live accuracy track record shown in the Accuracy tab.
- Runs the calibration and rewrites teams_calibrated.json.
- Writes fresh forecasts for the next unplayed matchdays.
- Re-embeds the ratings into index.html (the deployed web app).

Exits 0 whether or not anything changed; the workflow's git step
commits only when there is a diff.
"""

import datetime
import json
import os
import subprocess
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plsim import calibrate as cal  # noqa: E402

FORECAST_PATH = os.path.join("data", "forecasts.json")
LEDGER_PATH = os.path.join("data", "ledger.json")
FORECAST_MATCHDAYS = 2  # how many upcoming matchdays each run forecasts


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


# ------------------------------------------------------- accuracy ledger

def score_forecasts(forecasts, played):
    """Score forecast fixtures that now have a real result.

    ``forecasts`` is the dict written by write_forecasts; ``played`` a
    list of {md, home, away, hg, ag}. Returns (n, rps_sum, brier_sum)
    over the matched fixtures (n == 0 when nothing has been played yet).
    """
    from plsim.backtest import brier, rps

    real = {(m["md"], m["home"], m["away"]): (m["hg"], m["ag"])
            for m in played}
    n, rps_sum, brier_sum = 0, 0.0, 0.0
    for f in forecasts.get("fixtures", []):
        score = real.get((f["md"], f["home"], f["away"]))
        if score is None:
            continue
        hg, ag = score
        outcome = 0 if hg > ag else 1 if hg == ag else 2
        probs = (f["ph"], f["pd"], f["pa"])
        rps_sum += rps(probs, outcome)
        brier_sum += brier(probs, outcome)
        n += 1
    return n, rps_sum, brier_sum


def update_ledger(today=None):
    """Score last run's forecasts and append the result to the ledger."""
    if not os.path.exists(FORECAST_PATH):
        print("ledger: no previous forecasts to score")
        return
    from tools import build_form

    with open(FORECAST_PATH, encoding="utf-8") as fh:
        forecasts = json.load(fh)
    season = forecasts.get("season")
    played = build_form.played_matches(season) if season else []
    n, rps_sum, brier_sum = score_forecasts(forecasts, played)
    if not n:
        print("ledger: forecast fixtures not played yet")
        return
    today = today or datetime.date.today().isoformat()
    ledger = []
    if os.path.exists(LEDGER_PATH):
        with open(LEDGER_PATH, encoding="utf-8") as fh:
            ledger = json.load(fh)
    ledger = [e for e in ledger if e["date"] != today]  # idempotent reruns
    total_n = sum(e["matches"] for e in ledger) + n
    total_rps = sum(e["rps"] * e["matches"] for e in ledger) + rps_sum
    total_brier = sum(e["brier"] * e["matches"] for e in ledger) + brier_sum
    ledger.append({
        "date": today, "matches": n,
        "rps": round(rps_sum / n, 4), "brier": round(brier_sum / n, 4),
        "cumulative": {"matches": total_n,
                       "rps": round(total_rps / total_n, 4),
                       "brier": round(total_brier / total_n, 4)},
    })
    with open(LEDGER_PATH, "w", encoding="utf-8") as fh:
        json.dump(ledger, fh, indent=1)
        fh.write("\n")
    print(f"ledger: scored {n} matches (RPS {rps_sum / n:.4f}), "
          f"{total_n} cumulative")


def write_forecasts(ratings, info, today=None):
    """Forecast the next unplayed matchdays with the freshly fitted model."""
    from plsim import models
    from plsim.fixtures import get_fixtures
    from tools import build_form
    from tools.build_bundle import FIXTURE_SEASON

    teams = {k: v for k, v in ratings.items() if k != "_meta"}
    model = models.make_model("poisson", teams)
    matchdays, _dates, _src = get_fixtures(list(teams))
    played = {(m["md"], m["home"], m["away"])
              for m in build_form.played_matches(FIXTURE_SEASON)}
    rho = info.get("rho")
    fixtures, mds_used = [], []
    for md, pairs in enumerate(matchdays, start=1):
        todo = [(h, a) for h, a in pairs if (md, h, a) not in played]
        if not todo:
            continue
        if len(mds_used) >= FORECAST_MATCHDAYS:
            break
        mds_used.append(md)
        for h, a in todo:
            lam_h, lam_a = model.lambdas(h, a)
            grid = models.score_grid(lam_h, lam_a, True, rho)
            p_h, p_d, p_a = models.outcome_probs(grid)
            fixtures.append({"md": md, "home": h, "away": a,
                             "ph": round(p_h, 4), "pd": round(p_d, 4),
                             "pa": round(p_a, 4)})
    data = {"date": today or datetime.date.today().isoformat(),
            "season": FIXTURE_SEASON, "model": "poisson+dc",
            "fixtures": fixtures}
    with open(FORECAST_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
        fh.write("\n")
    print(f"forecasts: {len(fixtures)} fixtures over matchdays {mds_used}")


def refresh_odds(seasons):
    """Refresh the de-vigged closing-odds benchmark files, best effort.

    Requires the premier-league-data package (see tools/build_odds.py);
    when it is missing or the upstream mirror is down the benchmark
    simply stays as committed - never fatal for the weekly refit.
    """
    from tools import build_odds

    for season in seasons[-2:]:
        try:
            build_odds.build(season)
        except Exception as exc:  # noqa: BLE001
            print(f"odds refresh skipped for {season} "
                  f"(market benchmark unchanged): {exc}")


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

    # Refresh the market-odds benchmark files (best effort - a missing
    # package or mirror outage must not break the weekly refit).
    try:
        refresh_odds(seasons)
    except Exception as exc:  # noqa: BLE001
        print(f"odds refresh skipped (market benchmark unchanged): {exc}")

    # Score last week's forecasts against results that have landed since
    # (best effort - the ledger must never break the refit).
    try:
        update_ledger()
    except Exception as exc:  # noqa: BLE001
        print(f"ledger update skipped: {exc}")

    print(f"calibrating on: {', '.join(seasons)}")
    ratings, info = cal.calibrate(seasons=seasons)
    cal.write_ratings(ratings, "teams_calibrated.json", info)
    print(f"fitted {info['matches']} matches, rho {info['rho']:+.3f}")

    # Forecast the next matchdays with the fresh fit; scored next run.
    try:
        write_forecasts(ratings, info)
    except Exception as exc:  # noqa: BLE001
        print(f"forecast write skipped: {exc}")

    # Reliability profile from the walk-forward backtest (best effort - a
    # calibration hiccup must not break the refit). Runs before the bundle
    # so model.json carries the fresh numbers.
    try:
        subprocess.run([sys.executable, "tools/build_calibration.py"], check=True, timeout=600)
    except Exception as exc:  # noqa: BLE001
        print(f"calibration profile skipped: {exc}")

    subprocess.run([sys.executable, "tools/snapshot_history.py"], check=True)
    subprocess.run([sys.executable, "tools/embed_calibrated.py"], check=True)
    subprocess.run([sys.executable, "tools/build_form.py"], check=True)
    subprocess.run([sys.executable, "tools/build_bundle.py"], check=True)

    # Regenerate the SEO surfaces from the fresh bundle: the per-club
    # routes and the sitemap (best effort - a static-page glitch must
    # never break the weekly refit). The Open Graph image needs a
    # headless browser, so it is regenerated out of band, not here.
    for step in (["tools/build_clubs.py"], ["tools/build_sitemap.py"]):
        try:
            subprocess.run([sys.executable, *step], check=True, timeout=600)
        except Exception as exc:  # noqa: BLE001
            print(f"{step[0]} skipped: {exc}")
    print("done")


if __name__ == "__main__":
    main()
