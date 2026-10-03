"""Shrinkage and half-life, tested with a confidence interval.

Walk-forward, the way ``calibrate()`` serves ratings: for every Premier
League matchday of each target season, fit on matches strictly before its
first kickoff using the seasons production uses (two before plus the
target), with date decay, per-club home advantage, the xG blend and a
fitted rho. Then shrink each club towards average by its weighted match
count, renormalise over that season's 20 clubs, fold the fitted scoring
level into attack, and predict through PoissonModel's fixed 1.62 / 1.32
baselines. ``plsim.backtest`` skips the shrink and renormalise steps,
which is why it never tested SHRINK_MATCHES.

Each setting is compared with production on the same matches, and the
difference gets a 95% interval from a paired bootstrap that resamples
whole matchdays (one weekend's surprises move ten matches together, so
matches are not independent). A change counts as "better" only when the
whole interval is below zero. Ported from gameweek-edge's
scripts/confidence.mjs, which took the idea from Prem Predict
(github.com/GiwinEdwin09/FPL-Predictor).

    python3 tools/backtest_shrink.py                    # shrink sweep
    python3 tools/backtest_shrink.py --half-lives 180 250 365 550 --shrinks 5

Pure standard library, offline (reads the committed data/).
"""

import argparse
import datetime
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plsim import backtest as bt  # noqa: E402
from plsim import calibrate as cal  # noqa: E402
from plsim.teams import BASE_HOME_GOALS, BASE_AWAY_GOALS  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def season_str(year):
    return f"{year}-{str(year + 1)[2:]}"


def fit(train, cutoff, half_life, shrink, clubs):
    """Ratings as calibrate() would serve them at ``cutoff``."""
    w = cal.decay_weights(train, reference_date=cutoff, half_life=half_life)
    att, dfn, hom, bh, ba = cal.fit_poisson(
        train, w, iterations=bt.BT_ITERATIONS, home_adv=True,
        xg_alpha=cal.XG_ALPHA)
    rho = cal.fit_rho(train, w, att, dfn, hom, bh, ba)
    if shrink > 0:
        dw = {}
        for wi, m in zip(w, train):
            dw[m["home"]] = dw.get(m["home"], 0.0) + wi
            dw[m["away"]] = dw.get(m["away"], 0.0) + wi
        att = {k: 1 + dw[k] / (dw[k] + shrink) * (v - 1) for k, v in att.items()}
        dfn = {k: 1 + dw[k] / (dw[k] + shrink) * (v - 1) for k, v in dfn.items()}
    ma = sum(att[c] for c in clubs) / len(clubs)
    md = sum(dfn[c] for c in clubs) / len(clubs)
    mh = sum(hom[c] for c in clubs) / len(clubs)
    level = (bh + ba) / (BASE_HOME_GOALS + BASE_AWAY_GOALS)
    A = {c: att[c] / ma * level for c in clubs}
    D = {c: dfn[c] / md for c in clubs}
    H = {c: hom[c] / mh for c in clubs}
    return (lambda h, a: (BASE_HOME_GOALS * A[h] * D[a] * H[h],
                          BASE_AWAY_GOALS * A[a] * D[h])), rho


def paired_interval(rows, a, b, reps=2000, seed=20261003, level=0.95):
    """Mean of b minus a with a matchday-block bootstrap interval.

    Returns (estimate, lo, hi, verdict, blocks); negative is better.
    """
    blocks = {}
    for r in rows:
        s = blocks.setdefault(r["block"], [0, 0.0])
        s[0] += 1
        s[1] += r[b] - r[a]
    bl = list(blocks.values())
    n = len(bl)
    est = sum(s[1] for s in bl) / sum(s[0] for s in bl)
    rnd = random.Random(seed)
    draws = []
    for _ in range(reps):
        smp = [bl[rnd.randrange(n)] for _ in range(n)]
        draws.append(sum(s[1] for s in smp) / sum(s[0] for s in smp))
    draws.sort()
    tail = (1 - level) / 2
    lo = draws[int(tail * (reps - 1))]
    hi = draws[int((1 - tail) * (reps - 1))]
    verdict = "better" if hi < 0 else "worse" if lo > 0 else "unclear"
    return est, lo, hi, verdict, n


def run(targets, half_lives, shrinks, prior_seasons=2, progress=print):
    rows = []
    for target in targets:
        y = int(target[:4])
        seasons = tuple(season_str(y - k) for k in range(prior_seasons, -1, -1))
        matches = cal.load_matches(seasons, DATA, download=False)
        cal.attach_xg(matches, DATA)
        test = [m for m in matches if m["season"] == target and m["division"] == 1]
        clubs = sorted({m["home"] for m in test})
        for md in sorted({m["matchday"] for m in test}):
            group = [m for m in test if m["matchday"] == md]
            cutoff = min(m["date"] for m in group if m["date"])
            train = [m for m in matches if (m["date"] or datetime.date.min) < cutoff]
            fits = {(hl, sh): fit(train, cutoff, hl, sh, clubs)
                    for hl in half_lives for sh in shrinks}
            for m in group:
                out = 0 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 2)
                r = {"target": target, "block": (target, md)}
                for k, (lam, rho) in fits.items():
                    probs, _, _ = bt._probs_from(*lam(m["home"], m["away"]), rho)
                    r[k] = bt.rps(probs, out)
                rows.append(r)
        if progress:
            progress(f"  {target}: {sum(1 for r in rows if r['target'] == target)} matches")
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--targets", nargs="+", default=["2023-24", "2024-25", "2025-26"])
    ap.add_argument("--half-lives", nargs="+", type=int, default=[cal.DECAY_HALF_LIFE_DAYS])
    ap.add_argument("--shrinks", nargs="+", type=float, default=[15.0, 10.0, 5.0, 2.0, 0.0])
    ap.add_argument("--prior-seasons", type=int, default=2)
    args = ap.parse_args()

    base = (cal.DECAY_HALF_LIFE_DAYS, cal.SHRINK_MATCHES)
    shrinks = sorted(set(args.shrinks) | {base[1]}, reverse=True)
    half_lives = sorted(set(args.half_lives) | {base[0]})
    print(f"walk-forward, {args.prior_seasons} prior seasons + target; "
          f"production is half-life {base[0]}d, shrink {base[1]:g}")
    rows = run(args.targets, half_lives, shrinks, args.prior_seasons)
    keys = [(hl, sh) for hl in half_lives for sh in shrinks]
    label = lambda k: f"{k[0]}d / shrink {k[1]:g}"
    print("\nmean RPS (lower is better)")
    for k in keys:
        per = "  ".join(
            f"{t} {sum(r[k] for r in rows if r['target'] == t) / sum(1 for r in rows if r['target'] == t):.4f}"
            for t in args.targets)
        print(f"  {label(k):22s} {per}   all {sum(r[k] for r in rows) / len(rows):.4f}")
    print("\nchange vs production, RPS, 95% interval resampling whole matchdays")
    for k in keys:
        if k == base:
            continue
        e, lo, hi, v, n = paired_interval(rows, base, k)
        print(f"  {label(k):22s} {e:+.4f} [{lo:+.4f}, {hi:+.4f}] {v} ({n} matchdays)")
        for t in args.targets:
            e, lo, hi, v, _ = paired_interval([r for r in rows if r["target"] == t], base, k)
            print(f"      {t} {e:+.4f} [{lo:+.4f}, {hi:+.4f}] {v}")


if __name__ == "__main__":
    main()
