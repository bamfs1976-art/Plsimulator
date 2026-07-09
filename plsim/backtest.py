"""Walk-forward backtesting: score the model on a held-out season.

Protocol: for every matchday of the target season (the most recent one
by default), fit each model variant on strictly earlier matches only —
both divisions, all seasons, cut off by real match date — then predict
that matchday's Premier League fixtures and score the predictions
against what actually happened. This is exactly the situation the
simulator faces in live use, so the numbers are an honest estimate of
real-world accuracy.

Metrics (all lower-is-better):

- **RPS** (ranked probability score) — the standard for ordered
  win/draw/loss forecasts; punishes calling the wrong *side* harder
  than hedging toward a draw.
- **log-loss** and **Brier** over the three outcomes.
- **CS Brier** — Brier score of the clean-sheet probabilities (both
  teams per match), the quantity FPL defender/keeper picks hinge on.

Variants build on each other, so adjacent rows isolate one change:

1. ``season-step``   — the original fit: per-season weight steps
                       (1.0/0.5/0.25), plain Poisson, no correction.
2. ``+dixon-coles``  — adds the fixed rho = -0.12 low-score correction.
3. ``+date-decay``   — replaces season steps with exponential decay on
                       the match date (see DECAY_HALF_LIFE_DAYS).
4. ``+fitted-rho``   — fits rho by maximum likelihood instead of fixing it.
5. ``+home-adv``     — adds per-club home-advantage multipliers.
6. ``+xg-blend``     — fit target becomes 0.4*xG + 0.6*goals where team
                       xG is available (see tools/build_xg.py).

Plus reference points: ``uniform`` (1/3 each), ``home-rates`` (the
training set's overall H/D/A frequencies for every match), and ``elo``
(the Elo-driven model).
"""

import datetime
import math

from . import calibrate as cal
from . import models

BT_ITERATIONS = 40
SEASON_STEP = 0.5  # the original per-season weight step


# ---------------------------------------------------------------- metrics

def rps(probs, outcome):
    """Ranked probability score for ordered (home, draw, away)."""
    cum_p = cum_o = err = 0.0
    for k in range(2):
        cum_p += probs[k]
        cum_o += 1.0 if outcome == k else 0.0
        err += (cum_p - cum_o) ** 2
    return err / 2.0


def brier(probs, outcome):
    return sum((p - (1.0 if outcome == k else 0.0)) ** 2
               for k, p in enumerate(probs))


def log_loss(probs, outcome):
    return -math.log(max(probs[outcome], 1e-12))


class Scores:
    """Accumulates per-match metrics for one variant."""

    def __init__(self, name):
        self.name = name
        self.n = 0
        self.rps = self.brier = self.logloss = 0.0
        self.cs_n = 0
        self.cs_brier = 0.0
        self.cs_bins = [[0.0, 0, 0] for _ in range(10)]  # sum_p, hits, count

    def add(self, probs, outcome, cs_pairs=()):
        self.n += 1
        self.rps += rps(probs, outcome)
        self.brier += brier(probs, outcome)
        self.logloss += log_loss(probs, outcome)
        for p_cs, kept in cs_pairs:
            self.cs_n += 1
            self.cs_brier += (p_cs - (1.0 if kept else 0.0)) ** 2
            b = min(int(p_cs * 10), 9)
            self.cs_bins[b][0] += p_cs
            self.cs_bins[b][1] += 1 if kept else 0
            self.cs_bins[b][2] += 1

    def summary(self):
        n = max(self.n, 1)
        return {
            "variant": self.name, "matches": self.n,
            "rps": self.rps / n, "logloss": self.logloss / n,
            "brier": self.brier / n,
            "cs_brier": self.cs_brier / max(self.cs_n, 1),
        }


# ---------------------------------------------------------------- variants

def _season_step_weights(matches, n_seasons):
    return [SEASON_STEP ** (n_seasons - 1 - m["season_idx"]) for m in matches]


VARIANTS = ("season-step", "+dixon-coles", "+date-decay", "+fitted-rho",
            "+home-adv", "+xg-blend")


def _fit_variant(variant, train, n_seasons, cutoff):
    """Fit one variant -> dict with lambdas function and rho (None = no DC)."""
    if variant in ("season-step", "+dixon-coles"):
        weights = _season_step_weights(train, n_seasons)
    else:
        weights = cal.decay_weights(train, reference_date=cutoff)
    home_adv = variant in ("+home-adv", "+xg-blend")
    xg_alpha = cal.XG_ALPHA if variant == "+xg-blend" else 0.0
    att, dfn, hom, base_h, base_a = cal.fit_poisson(
        train, weights, iterations=BT_ITERATIONS, home_adv=home_adv,
        xg_alpha=xg_alpha)
    if variant in ("+fitted-rho", "+home-adv", "+xg-blend"):
        rho = cal.fit_rho(train, weights, att, dfn, hom, base_h, base_a)
    elif variant == "season-step":
        rho = None
    else:
        rho = models.DC_RHO

    def lambdas(home, away):
        return (base_h * att[home] * dfn[away] * hom[home],
                base_a * att[away] * dfn[home])

    return {"lambdas": lambdas, "rho": rho}


def _probs_from(lam_h, lam_a, rho):
    grid = models.score_grid(lam_h, lam_a, rho is not None,
                             rho if rho is not None else models.DC_RHO)
    p_h, p_d, p_a = models.outcome_probs(grid)
    G = models.GRID
    cs_home = sum(grid[h * G] for h in range(G))       # away scores 0
    cs_away = sum(grid[a] for a in range(G))           # home scores 0
    return (p_h, p_d, p_a), cs_home, cs_away


# ---------------------------------------------------------------- protocol

def run(seasons=cal.DEFAULT_SEASONS, target=None, cache_dir="data",
        download=True, every=1, progress=None):
    """Walk-forward backtest -> (list of summary dicts, winner Scores).

    ``every`` > 1 evaluates only every n-th matchday (quick mode).
    """
    matches = cal.load_matches(seasons, cache_dir, download)
    cal.attach_xg(matches, cache_dir)
    target = target or seasons[-1]
    if target not in {m["season"] for m in matches}:
        raise ValueError(f"season {target!r} not in the loaded data")
    n_seasons = len(seasons)

    test = [m for m in matches if m["season"] == target and m["division"] == 1]
    matchdays = sorted({m["matchday"] for m in test})
    matchdays = [md for i, md in enumerate(matchdays) if i % every == 0]

    scores = {v: Scores(v) for v in VARIANTS}
    scores["uniform"] = Scores("uniform")
    scores["home-rates"] = Scores("home-rates")
    scores["elo"] = Scores("elo")

    for done, md in enumerate(matchdays):
        group = [m for m in test if m["matchday"] == md]
        dates = [m["date"] for m in group if m["date"]]
        cutoff = min(dates) if dates else None
        if cutoff:
            train = [m for m in matches
                     if (m["date"] or datetime.date.min) < cutoff]
        else:
            train = [m for m in matches
                     if m["season"] != target or m["matchday"] < md]
        if len(train) < 200:
            continue

        fits = {v: _fit_variant(v, train, n_seasons, cutoff) for v in VARIANTS}

        # Reference points.
        w = _season_step_weights(train, n_seasons)
        tot = sum(w)
        rates = (
            sum(wi for wi, m in zip(w, train) if m["hg"] > m["ag"]) / tot,
            sum(wi for wi, m in zip(w, train) if m["hg"] == m["ag"]) / tot,
            sum(wi for wi, m in zip(w, train) if m["hg"] < m["ag"]) / tot,
        )
        elo = cal.fit_elo(train)
        elo_teams = {t: {"elo": e, "attack": 1.0, "defence": 1.0}
                     for t, e in elo.items()}
        elo_model = models.EloModel(elo_teams)

        for m in group:
            outcome = 0 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 2)
            home_cs = m["ag"] == 0
            away_cs = m["hg"] == 0
            scores["uniform"].add((1 / 3, 1 / 3, 1 / 3), outcome)
            scores["home-rates"].add(rates, outcome)
            lam = elo_model.lambdas(m["home"], m["away"])
            probs, csh, csa = _probs_from(lam[0], lam[1], None)
            scores["elo"].add(probs, outcome,
                              ((csh, home_cs), (csa, away_cs)))
            for v, fit in fits.items():
                lam_h, lam_a = fit["lambdas"](m["home"], m["away"])
                probs, csh, csa = _probs_from(lam_h, lam_a, fit["rho"])
                scores[v].add(probs, outcome,
                              ((csh, home_cs), (csa, away_cs)))
        if progress:
            progress(done + 1, len(matchdays), md)

    order = ["uniform", "home-rates", "elo"] + list(VARIANTS)
    summaries = [scores[k].summary() for k in order]
    winner = min((scores[v] for v in VARIANTS),
                 key=lambda s: s.summary()["rps"])
    return summaries, winner
