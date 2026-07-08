"""Match prediction models.

Two models are available, both producing a pair of Poisson goal rates
(lambda_home, lambda_away) for any fixture:

- ``poisson``: independent-Poisson attack/defence model. Each team has an
  attack and a defence multiplier applied to league-average home/away
  scoring rates. Optionally applies the Dixon-Coles (1997) low-score
  correlation correction, which fixes the known Poisson bias on 0-0, 1-0,
  0-1 and 1-1 scorelines.

- ``elo``: derives the goal rates from the Elo gap between the sides plus
  a home-advantage bonus, splitting an average total-goals budget
  asymmetrically toward the stronger team.

For each fixture the full score-probability grid (0-10 goals each) is
precomputed once; simulations then draw scorelines from the cumulative
distribution with a single binary search, which keeps large Monte Carlo
runs fast in pure Python.
"""

import bisect
import math

from .teams import BASE_HOME_GOALS, BASE_AWAY_GOALS

MAX_GOALS = 10          # per-team cap for the score grid (P(>10) is ~0)
GRID = MAX_GOALS + 1
ELO_HOME_BONUS = 60.0   # Elo points of home advantage
ELO_GOAL_SCALE = 0.45   # how strongly the Elo gap skews the goal split
DC_RHO = -0.12          # Dixon-Coles correlation parameter

_FACT = [math.factorial(k) for k in range(GRID)]


class PoissonModel:
    """Attack/defence Poisson model."""

    name = "poisson"

    def __init__(self, teams):
        self.teams = teams

    def lambdas(self, home, away):
        th, ta = self.teams[home], self.teams[away]
        lam_h = BASE_HOME_GOALS * th["attack"] * ta["defence"]
        lam_a = BASE_AWAY_GOALS * ta["attack"] * th["defence"]
        return lam_h, lam_a


class EloModel:
    """Elo-driven goal-rate model."""

    name = "elo"

    def __init__(self, teams):
        self.teams = teams
        self.total_goals = BASE_HOME_GOALS + BASE_AWAY_GOALS

    def lambdas(self, home, away):
        diff = self.teams[home]["elo"] - self.teams[away]["elo"] + ELO_HOME_BONUS
        expected = 1.0 / (1.0 + 10.0 ** (-diff / 400.0))
        skew = ELO_GOAL_SCALE * (2.0 * expected - 1.0) * math.log(10)
        half = self.total_goals / 2.0
        return half * math.exp(skew), half * math.exp(-skew)


def make_model(name, teams):
    if name == "poisson":
        return PoissonModel(teams)
    if name == "elo":
        return EloModel(teams)
    raise ValueError(f"unknown model {name!r}")


def _dc_tau(h, a, lam_h, lam_a, rho):
    """Dixon-Coles adjustment factor for low scorelines."""
    if h == 0 and a == 0:
        return 1.0 - lam_h * lam_a * rho
    if h == 0 and a == 1:
        return 1.0 + lam_h * rho
    if h == 1 and a == 0:
        return 1.0 + lam_a * rho
    if h == 1 and a == 1:
        return 1.0 - rho
    return 1.0


def score_grid(lam_h, lam_a, dixon_coles=False, rho=DC_RHO):
    """Flat probability grid over scorelines; index = home * GRID + away."""
    ph = [math.exp(-lam_h) * lam_h**k / _FACT[k] for k in range(GRID)]
    pa = [math.exp(-lam_a) * lam_a**k / _FACT[k] for k in range(GRID)]
    grid = [ph[h] * pa[a] for h in range(GRID) for a in range(GRID)]
    if dixon_coles:
        for h in (0, 1):
            for a in (0, 1):
                grid[h * GRID + a] *= _dc_tau(h, a, lam_h, lam_a, rho)
    total = sum(grid)
    return [p / total for p in grid]


def cumulative(grid):
    """Cumulative distribution for fast sampling with bisect."""
    cum, running = [], 0.0
    for p in grid:
        running += p
        cum.append(running)
    cum[-1] = 1.0
    return cum


def sample_score(cum, rng):
    """Draw one (home_goals, away_goals) scoreline from a cumulative grid."""
    idx = bisect.bisect_left(cum, rng.random())
    return divmod(idx, GRID)


def outcome_probs(grid):
    """(P(home win), P(draw), P(away win)) from a score grid."""
    p_home = p_draw = p_away = 0.0
    for h in range(GRID):
        row = h * GRID
        for a in range(GRID):
            p = grid[row + a]
            if h > a:
                p_home += p
            elif h == a:
                p_draw += p
            else:
                p_away += p
    return p_home, p_draw, p_away


def most_likely_score(grid):
    idx = max(range(len(grid)), key=grid.__getitem__)
    return divmod(idx, GRID)


def poisson_sample(lam, rng):
    """Knuth's Poisson sampler (used only when per-season noise is on)."""
    threshold = math.exp(-lam)
    k, product = 0, rng.random()
    while product > threshold:
        k += 1
        product *= rng.random()
    return k
