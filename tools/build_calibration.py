#!/usr/bin/env python3
"""Compute a reliability (calibration) profile from the walk-forward backtest.

Replays the winning model variant (decay weights + per-club home advantage +
fitted Dixon-Coles rho + xG blend — exactly the deployed model) across the
held-out target season, one matchday at a time, fitting only on strictly
earlier matches. For every prediction it records the three class
probabilities against whether that class actually happened, then bins them
into a reliability curve and computes the Expected Calibration Error (ECE).

The market's de-vigged closing odds are profiled the same way where they
exist, as a reference. Output: data/calibration.json, embedded into the app
by tools/build_bundle.py / embed. This reuses backtest *outputs*; it does not
change the scoring logic.

    python3 tools/build_calibration.py            # target = latest season
    python3 tools/build_calibration.py 2025-26
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plsim import calibrate as cal  # noqa: E402
from plsim import models  # noqa: E402
from plsim.backtest import BT_ITERATIONS, _load_odds  # noqa: E402

N_BINS = 10


def _new_bins():
    # each bin: [sum_predicted, hits, count]
    return [[0.0, 0, 0] for _ in range(N_BINS)]


def _add(bins, p, hit):
    b = min(int(p * N_BINS), N_BINS - 1)
    bins[b][0] += p
    bins[b][1] += 1 if hit else 0
    bins[b][2] += 1


def _profile(bins):
    n = sum(b[2] for b in bins) or 1
    out, ece = [], 0.0
    for b in bins:
        if b[2] == 0:
            out.append({"mean_pred": None, "observed": None, "count": 0})
            continue
        mean_pred = b[0] / b[2]
        observed = b[1] / b[2]
        ece += (b[2] / n) * abs(mean_pred - observed)
        out.append({"mean_pred": round(mean_pred, 4),
                    "observed": round(observed, 4), "count": b[2]})
    return {"bins": out, "ece": round(ece, 4), "n": n}


def build(target=None, cache_dir="data", every=1):
    seasons = cal.DEFAULT_SEASONS
    matches = cal.load_matches(seasons, cache_dir, download=False)
    cal.attach_xg(matches, cache_dir)
    target = target or seasons[-1]
    odds = _load_odds(target, cache_dir)

    test = [m for m in matches if m["season"] == target and m["division"] == 1]
    import datetime
    matchdays = sorted({m["matchday"] for m in test})
    matchdays = [md for i, md in enumerate(matchdays) if i % every == 0]

    model_bins, market_bins = _new_bins(), _new_bins()
    for md in matchdays:
        group = [m for m in test if m["matchday"] == md]
        dates = [m["date"] for m in group if m["date"]]
        cutoff = min(dates) if dates else None
        train = [m for m in matches
                 if (m["date"] or datetime.date.min) < cutoff] if cutoff else []
        if len(train) < 200:
            continue
        weights = cal.decay_weights(train, reference_date=cutoff)
        att, dfn, hom, base_h, base_a = cal.fit_poisson(
            train, weights, iterations=BT_ITERATIONS, home_adv=True, xg_alpha=cal.XG_ALPHA)
        rho = cal.fit_rho(train, weights, att, dfn, hom, base_h, base_a)
        for m in group:
            outcome = 0 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 2)
            lam_h = base_h * att[m["home"]] * dfn[m["away"]] * hom[m["home"]]
            lam_a = base_a * att[m["away"]] * dfn[m["home"]]
            probs = models.outcome_probs(models.score_grid(lam_h, lam_a, True, rho))
            for k in range(3):
                _add(model_bins, probs[k], outcome == k)
            if odds:
                po = odds.get((m["date"], cal._canon(m["home"]), cal._canon(m["away"])))
                if po:
                    for k in range(3):
                        _add(market_bins, po[k], outcome == k)

    result = {
        "target": target,
        "model": _profile(model_bins),
        "market": _profile(market_bins) if any(b[2] for b in market_bins) else None,
        "note": "One-vs-rest reliability of win/draw/away probabilities over the "
                "walk-forward backtest. mean_pred vs observed per decile; ECE is the "
                "count-weighted mean gap. Lower ECE = better calibrated.",
    }
    return result


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    every = int(os.environ.get("CAL_EVERY", "1"))
    print(f"Profiling calibration for {target or 'latest season'} (every={every}) ...", flush=True)
    res = build(target, every=every)
    out = os.path.join("data", "calibration.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    m = res["model"]
    print(f"{out}: model ECE {m['ece']} over {m['n']} predictions"
          + (f", market ECE {res['market']['ece']}" if res["market"] else ""))
