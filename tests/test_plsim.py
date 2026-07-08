"""Sanity tests: run with  python3 -m unittest discover tests"""

import random
import unittest
from collections import Counter

from plsim import models, simulate
from plsim.fixtures import generate_fixtures
from plsim.teams import load_teams


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.teams = load_teams()
        self.matchdays = generate_fixtures(self.teams)

    def test_38_matchdays_of_10_games(self):
        self.assertEqual(len(self.matchdays), 38)
        for md in self.matchdays:
            self.assertEqual(len(md), 10)

    def test_double_round_robin(self):
        pairs = Counter(
            (h, a) for md in self.matchdays for h, a in md
        )
        self.assertEqual(len(pairs), 380)
        self.assertEqual(max(pairs.values()), 1)
        for home, away in list(pairs):
            self.assertIn((away, home), pairs)

    def test_19_home_19_away_each(self):
        home = Counter(h for md in self.matchdays for h, _ in md)
        away = Counter(a for md in self.matchdays for _, a in md)
        for t in self.teams:
            self.assertEqual(home[t], 19)
            self.assertEqual(away[t], 19)

    def test_no_team_plays_twice_in_a_matchday(self):
        for md in self.matchdays:
            names = [t for pair in md for t in pair]
            self.assertEqual(len(names), len(set(names)))


class ModelTests(unittest.TestCase):
    def test_score_grid_sums_to_one(self):
        for dc in (False, True):
            grid = models.score_grid(1.6, 1.2, dixon_coles=dc)
            self.assertAlmostEqual(sum(grid), 1.0, places=9)

    def test_outcome_probs_sum_to_one(self):
        grid = models.score_grid(1.8, 1.1)
        self.assertAlmostEqual(sum(models.outcome_probs(grid)), 1.0, places=9)

    def test_better_team_favoured_both_models(self):
        teams = load_teams()
        for name in ("poisson", "elo"):
            model = models.make_model(name, teams)
            lh, la = model.lambdas("Arsenal", "Hull City")
            self.assertGreater(lh, la)


class SimulationTests(unittest.TestCase):
    def test_season_is_consistent(self):
        teams = load_teams()
        model = models.make_model("poisson", teams)
        matchdays = generate_fixtures(teams)
        grids = simulate.fixture_grids(simulate.fixture_lambdas(model, matchdays))
        table, results = simulate.simulate_season(grids, list(teams), random.Random(0))
        self.assertEqual(len(results), 380)
        rows = table.rows
        for r in rows.values():
            self.assertEqual(r["P"], 38)
            self.assertEqual(r["W"] + r["D"] + r["L"], 38)
        self.assertEqual(sum(r["GF"] for r in rows.values()),
                         sum(r["GA"] for r in rows.values()))
        total_pts = sum(r["Pts"] for r in rows.values())
        draws = sum(r["D"] for r in rows.values()) // 2
        self.assertEqual(total_pts, 3 * (380 - draws) + 2 * draws)

    def test_monte_carlo_probabilities_consistent(self):
        teams = load_teams()
        model = models.make_model("poisson", teams)
        matchdays = generate_fixtures(teams)
        agg = simulate.monte_carlo(model, matchdays, list(teams), 300,
                                   seed=123, workers=1)
        self.assertEqual(agg.n, 300)
        self.assertAlmostEqual(
            sum(agg.prob_champion(t) for t in teams), 1.0, places=9)
        self.assertAlmostEqual(
            sum(agg.prob_relegated(t) for t in teams), 3.0, places=9)

    def test_reproducible_with_seed(self):
        teams = load_teams()
        model = models.make_model("poisson", teams)
        matchdays = generate_fixtures(teams)
        a = simulate.monte_carlo(model, matchdays, list(teams), 100,
                                 seed=7, workers=1)
        b = simulate.monte_carlo(model, matchdays, list(teams), 100,
                                 seed=7, workers=1)
        self.assertEqual(a.points_sum, b.points_sum)


if __name__ == "__main__":
    unittest.main()
