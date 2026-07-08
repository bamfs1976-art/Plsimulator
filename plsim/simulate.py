"""Season simulation and the Monte Carlo engine.

The engine precomputes each fixture's cumulative score distribution once,
so a simulated match is a single binary search. Large runs are split
across worker processes and their aggregates merged, which makes very
high simulation counts (100k+) practical without third-party libraries.

With ``rating_noise`` > 0 each simulated season perturbs every team's
attack/defence rates by a log-normal factor, modelling season-to-season
uncertainty about true strength (injuries, transfers, form). Noise mode
samples goals directly from Poisson rates, so the Dixon-Coles correction
does not apply there.
"""

import math
import multiprocessing
import random

from . import models
from .fixtures import all_matches
from .table import LeagueTable

RELEGATION_SPOTS = 3


def fixture_lambdas(model, matchdays):
    """Per-fixture (matchday, home, away, lam_h, lam_a) for the whole season."""
    return [
        (md, home, away, *model.lambdas(home, away))
        for md, home, away in all_matches(matchdays)
    ]


def fixture_grids(lambdas, dixon_coles=False):
    """Cumulative score distributions for every fixture in the season."""
    return [
        (md, home, away, models.cumulative(models.score_grid(lh, la, dixon_coles)))
        for md, home, away, lh, la in lambdas
    ]


def simulate_season(grids, team_names, rng):
    """One full season from precomputed grids -> (LeagueTable, results).

    results is a list of (matchday, home, away, hg, ag).
    """
    table = LeagueTable(team_names)
    results = []
    for md, home, away, cum in grids:
        hg, ag = models.sample_score(cum, rng)
        table.record(home, away, hg, ag)
        results.append((md, home, away, hg, ag))
    return table, results


def _simulate_season_noisy(lambdas, team_names, rng, noise):
    """One season with per-season strength perturbation (direct Poisson)."""
    factor_att = {t: math.exp(rng.gauss(0.0, noise)) for t in team_names}
    factor_def = {t: math.exp(rng.gauss(0.0, noise)) for t in team_names}
    table = LeagueTable(team_names)
    for _md, home, away, lh, la in lambdas:
        hg = models.poisson_sample(lh * factor_att[home] * factor_def[away], rng)
        ag = models.poisson_sample(la * factor_att[away] * factor_def[home], rng)
        table.record(home, away, hg, ag)
    return table


class Aggregate:
    """Accumulated Monte Carlo statistics per team."""

    def __init__(self, team_names):
        self.n = 0
        self.pos_counts = {t: [0] * len(team_names) for t in team_names}
        self.points_sum = {t: 0 for t in team_names}
        self.points_sqsum = {t: 0 for t in team_names}
        self.points_min = {t: None for t in team_names}
        self.points_max = {t: None for t in team_names}

    def add_season(self, table):
        self.n += 1
        for pos, team in enumerate(table.standings()):
            self.pos_counts[team][pos] += 1
            pts = table.rows[team]["Pts"]
            self.points_sum[team] += pts
            self.points_sqsum[team] += pts * pts
            lo, hi = self.points_min[team], self.points_max[team]
            if lo is None or pts < lo:
                self.points_min[team] = pts
            if hi is None or pts > hi:
                self.points_max[team] = pts

    def merge(self, other):
        self.n += other.n
        for t in self.pos_counts:
            counts = self.pos_counts[t]
            for i, c in enumerate(other.pos_counts[t]):
                counts[i] += c
            self.points_sum[t] += other.points_sum[t]
            self.points_sqsum[t] += other.points_sqsum[t]
            for attr, pick in (("points_min", min), ("points_max", max)):
                mine, theirs = getattr(self, attr)[t], getattr(other, attr)[t]
                if theirs is not None:
                    getattr(self, attr)[t] = theirs if mine is None else pick(mine, theirs)

    # -- derived statistics ------------------------------------------------

    def prob_position_range(self, team, first, last):
        return sum(self.pos_counts[team][first - 1 : last]) / self.n

    def prob_champion(self, team):
        return self.prob_position_range(team, 1, 1)

    def prob_top4(self, team):
        return self.prob_position_range(team, 1, 4)

    def prob_relegated(self, team):
        n_teams = len(self.pos_counts)
        return self.prob_position_range(team, n_teams - RELEGATION_SPOTS + 1, n_teams)

    def mean_points(self, team):
        return self.points_sum[team] / self.n

    def std_points(self, team):
        mean = self.mean_points(team)
        var = self.points_sqsum[team] / self.n - mean * mean
        return math.sqrt(max(var, 0.0))

    def mean_position(self, team):
        counts = self.pos_counts[team]
        return sum((i + 1) * c for i, c in enumerate(counts)) / self.n


def _worker(args):
    (n_sims, seed, team_names, lambdas, dixon_coles, noise) = args
    rng = random.Random(seed)
    agg = Aggregate(team_names)
    if noise > 0:
        for _ in range(n_sims):
            agg.add_season(_simulate_season_noisy(lambdas, team_names, rng, noise))
    else:
        grids = fixture_grids(lambdas, dixon_coles)
        for _ in range(n_sims):
            table, _results = simulate_season(grids, team_names, rng)
            agg.add_season(table)
    return agg


def monte_carlo(model, matchdays, team_names, n_sims, seed=None,
                dixon_coles=False, noise=0.0, workers=None, progress=None):
    """Run n_sims full seasons and return the merged Aggregate."""
    lambdas = fixture_lambdas(model, matchdays)
    if seed is None:
        seed = random.randrange(2**63)
    if workers is None:
        workers = min(multiprocessing.cpu_count(), 8) if n_sims >= 4000 else 1

    if workers <= 1:
        return _worker((n_sims, seed, team_names, lambdas, dixon_coles, noise))

    base, extra = divmod(n_sims, workers)
    jobs = [
        (base + (1 if w < extra else 0), seed + w, team_names, lambdas, dixon_coles, noise)
        for w in range(workers)
        if base + (1 if w < extra else 0) > 0
    ]
    total = Aggregate(team_names)
    with multiprocessing.Pool(len(jobs)) as pool:
        for i, agg in enumerate(pool.imap_unordered(_worker, jobs), 1):
            total.merge(agg)
            if progress:
                progress(i, len(jobs))
    return total
