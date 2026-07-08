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


class CalibrateParserTests(unittest.TestCase):
    V_FORMAT = """\
= English Premier League 2025/26

# Teams      20

▪ Matchday 1
  Fri Aug 15 2025
    20:00  Liverpool FC            v AFC Bournemouth          4-2 (1-0)
  Sat Aug 16
    12:30  Aston Villa FC          v Newcastle United FC      0-0
           Brighton & Hove Albion FC v Fulham FC                1-1 (0-0)
"""

    MID_FORMAT = """\
= English Premier League 2023/24

▪ Matchday 1
Fri Aug 11
  20:00  Burnley FC               0-3 (0-2)  Manchester City FC
Sat Aug 12
         Brighton & Hove Albion FC  4-1 (1-0)  Luton Town FC
"""

    PLAYOFFS = """\
= Championship 2025/26

▪ Matchday 46
  Sat May 2
    12:30  Hull City AFC           v Norwich City FC          2-1 (1-1)

▪ Playoffs
  Fri May 8
    20:00  Hull City AFC           v Millwall FC              0-0
"""

    def test_v_format(self):
        from plsim.calibrate import parse_matches
        got = list(parse_matches(self.V_FORMAT))
        self.assertEqual(got, [
            (1, "Liverpool FC", "AFC Bournemouth", 4, 2),
            (1, "Aston Villa FC", "Newcastle United FC", 0, 0),
            (1, "Brighton & Hove Albion FC", "Fulham FC", 1, 1),
        ])

    def test_mid_score_format(self):
        from plsim.calibrate import parse_matches
        got = list(parse_matches(self.MID_FORMAT))
        self.assertEqual(got, [
            (1, "Burnley FC", "Manchester City FC", 0, 3),
            (1, "Brighton & Hove Albion FC", "Luton Town FC", 4, 1),
        ])

    def test_playoffs_excluded(self):
        from plsim.calibrate import parse_matches
        got = list(parse_matches(self.PLAYOFFS))
        self.assertEqual(got, [(46, "Hull City AFC", "Norwich City FC", 2, 1)])

    def test_calibrate_from_cached_data(self):
        import os
        if not os.path.isdir("data"):
            self.skipTest("no cached data/ directory")
        from plsim.calibrate import calibrate
        ratings, info = calibrate(download=False)
        self.assertEqual(len(ratings), 20)
        self.assertEqual(info["matches"], 2796)
        for r in ratings.values():
            self.assertGreater(r["attack"], 0.3)
            self.assertLess(r["attack"], 2.0)
            self.assertGreater(r["defence"], 0.3)
            self.assertLess(r["defence"], 2.0)
        # The fit should still rank Arsenal well above Hull.
        self.assertGreater(ratings["Arsenal"]["attack"],
                           ratings["Hull City"]["attack"])
        self.assertLess(ratings["Arsenal"]["defence"],
                        ratings["Hull City"]["defence"])
        self.assertGreater(ratings["Arsenal"]["elo"],
                           ratings["Hull City"]["elo"])


if __name__ == "__main__":
    unittest.main()
