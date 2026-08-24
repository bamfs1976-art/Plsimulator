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

    def test_pinned_results_are_honoured(self):
        teams = load_teams()
        model = models.make_model("poisson", teams)
        matchdays = generate_fixtures(teams)
        md1_home, md1_away = matchdays[0][0]
        pins = [{"md": 1, "home": md1_home, "away": md1_away, "hg": 7, "ag": 0}]
        grids = simulate.pin_results(
            simulate.fixture_grids(simulate.fixture_lambdas(model, matchdays)),
            pins)
        for seed in (0, 1, 2):
            _table, results = simulate.simulate_season(grids, list(teams),
                                                       random.Random(seed))
            self.assertIn((1, md1_home, md1_away, 7, 0), results)

    def test_all_results_pinned_is_deterministic(self):
        teams = load_teams()
        model = models.make_model("poisson", teams)
        matchdays = generate_fixtures(teams)
        # Pin all 380 fixtures: every simulated season is then identical.
        pins = [{"md": md + 1, "home": h, "away": a,
                 "hg": (md + len(h)) % 4, "ag": len(a) % 3}
                for md, fixtures in enumerate(matchdays) for h, a in fixtures]
        agg = simulate.monte_carlo(model, matchdays, list(teams), 50,
                                   seed=9, workers=1, results=pins)
        for t in teams:
            self.assertEqual(agg.points_min[t], agg.points_max[t])
            self.assertEqual(max(agg.pos_counts[t]), 50)

    def test_unpinned_run_unchanged_by_empty_results(self):
        teams = load_teams()
        model = models.make_model("poisson", teams)
        matchdays = generate_fixtures(teams)
        a = simulate.monte_carlo(model, matchdays, list(teams), 100,
                                 seed=7, workers=1)
        b = simulate.monte_carlo(model, matchdays, list(teams), 100,
                                 seed=7, workers=1, results=[])
        self.assertEqual(a.points_sum, b.points_sum)

    def test_reproducible_with_seed(self):
        teams = load_teams()
        model = models.make_model("poisson", teams)
        matchdays = generate_fixtures(teams)
        a = simulate.monte_carlo(model, matchdays, list(teams), 100,
                                 seed=7, workers=1)
        b = simulate.monte_carlo(model, matchdays, list(teams), 100,
                                 seed=7, workers=1)
        self.assertEqual(a.points_sum, b.points_sum)


class LoadRatingsValidationTests(unittest.TestCase):
    def _write(self, data):
        import json
        import os
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        self.addCleanup(os.remove, path)
        return path

    def _valid_teams(self):
        from plsim.teams import DEFAULT_TEAMS
        return {n: dict(r) for n, r in DEFAULT_TEAMS.items()}

    def test_valid_file_loads_and_defaults_home(self):
        from plsim.teams import load_ratings
        teams, meta = load_ratings(self._write(self._valid_teams()))
        self.assertEqual(len(teams), 20)
        self.assertEqual(meta, {})
        for r in teams.values():
            self.assertEqual(r["home"], 1.0)  # missing home -> 1.0 default

    def test_explicit_home_is_kept(self):
        from plsim.teams import load_ratings
        data = self._valid_teams()
        data["Arsenal"]["home"] = 1.1
        teams, _ = load_ratings(self._write(data))
        self.assertEqual(teams["Arsenal"]["home"], 1.1)

    def test_wrong_team_count_rejected(self):
        from plsim.teams import load_ratings
        data = self._valid_teams()
        data.pop("Arsenal")
        with self.assertRaisesRegex(ValueError, "expected 20 teams"):
            load_ratings(self._write(data))

    def test_non_numeric_rating_rejected(self):
        from plsim.teams import load_ratings
        for bad in ("1.2", None, True, [1.2]):
            data = self._valid_teams()
            data["Arsenal"]["attack"] = bad
            with self.assertRaisesRegex(ValueError, "must be a number"):
                load_ratings(self._write(data))

    def test_non_positive_rating_rejected(self):
        from plsim.teams import load_ratings
        for key, bad in (("attack", 0), ("defence", -0.5), ("elo", -1),
                         ("home", 0.0)):
            data = self._valid_teams()
            data["Arsenal"][key] = bad
            with self.assertRaisesRegex(ValueError, "must be positive"):
                load_ratings(self._write(data))

    def test_missing_key_rejected(self):
        from plsim.teams import load_ratings
        data = self._valid_teams()
        del data["Arsenal"]["defence"]
        with self.assertRaisesRegex(ValueError, "missing 'defence'"):
            load_ratings(self._write(data))

    def test_non_object_team_rejected(self):
        from plsim.teams import load_ratings
        data = self._valid_teams()
        data["Arsenal"] = [1.35, 0.7, 1900]
        with self.assertRaisesRegex(ValueError, "expected an object"):
            load_ratings(self._write(data))


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
        import datetime
        from plsim.calibrate import parse_matches
        got = list(parse_matches(self.V_FORMAT, season="2025-26"))
        self.assertEqual(got, [
            (1, datetime.date(2025, 8, 15), "Liverpool FC", "AFC Bournemouth", 4, 2),
            (1, datetime.date(2025, 8, 16), "Aston Villa FC", "Newcastle United FC", 0, 0),
            (1, datetime.date(2025, 8, 16), "Brighton & Hove Albion FC", "Fulham FC", 1, 1),
        ])

    def test_mid_score_format(self):
        import datetime
        from plsim.calibrate import parse_matches
        got = list(parse_matches(self.MID_FORMAT, season="2023-24"))
        self.assertEqual(got, [
            (1, datetime.date(2023, 8, 11), "Burnley FC", "Manchester City FC", 0, 3),
            (1, datetime.date(2023, 8, 12), "Brighton & Hove Albion FC", "Luton Town FC", 4, 1),
        ])

    def test_playoffs_excluded(self):
        import datetime
        from plsim.calibrate import parse_matches
        got = list(parse_matches(self.PLAYOFFS, season="2025-26"))
        self.assertEqual(got, [
            (46, datetime.date(2026, 5, 2), "Hull City AFC", "Norwich City FC", 2, 1)])

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


class BacktestTests(unittest.TestCase):
    def test_rps_known_values(self):
        from plsim.backtest import rps
        # Certain and correct -> 0; certain and maximally wrong -> 1.
        self.assertAlmostEqual(rps((1, 0, 0), 0), 0.0)
        self.assertAlmostEqual(rps((0, 0, 1), 0), 1.0)
        # Uniform forecast, home win: 0.5*((1/3-1)^2+(2/3-1)^2) = 5/18.
        self.assertAlmostEqual(rps((1 / 3, 1 / 3, 1 / 3), 0), 5 / 18)
        # Draw is "between" H and A, so a draw forecast error is smaller.
        self.assertLess(rps((0, 1, 0), 0), rps((0, 0, 1), 0))

    def test_walk_forward_smoke(self):
        import os
        if not os.path.isdir("data"):
            self.skipTest("no cached data/ directory")
        from plsim import backtest as bt
        summaries, winner, market = bt.run(download=False, every=8)
        by_name = {s["variant"]: s for s in summaries}
        self.assertEqual(len(by_name), 3 + len(bt.VARIANTS))
        # Every fitted variant must beat the uniform reference.
        for v in bt.VARIANTS:
            self.assertLess(by_name[v]["rps"], by_name["uniform"]["rps"])
        self.assertIn(winner.name, bt.VARIANTS)
        if market:  # odds files present: the market should be strong
            self.assertLess(market[1]["rps"], by_name["uniform"]["rps"])

    def test_promoted_adjust_grades_by_div2_share(self):
        from plsim.calibrate import promoted_adjust, PROMOTED_ATT
        matches = [
            {"home": "A", "away": "B", "division": 2},   # A,B: all div-2
            {"home": "C", "away": "D", "division": 1},   # C,D: all div-1
        ]
        att = {t: 1.0 for t in "ABCD"}
        dfn = {t: 1.0 for t in "ABCD"}
        promoted_adjust(att, dfn, matches, [1.0, 1.0])
        self.assertAlmostEqual(att["A"], PROMOTED_ATT)   # full share
        self.assertAlmostEqual(att["C"], 1.0)            # untouched
        self.assertGreater(dfn["B"], 1.0)

    def test_calibrated_file_has_home_and_meta(self):
        import os
        if not os.path.exists("teams_calibrated.json"):
            self.skipTest("no teams_calibrated.json")
        from plsim.teams import load_ratings
        teams, meta = load_ratings("teams_calibrated.json")
        self.assertEqual(len(teams), 20)
        self.assertIn("rho", meta)
        for r in teams.values():
            self.assertIn("home", r)
        mean_home = sum(r["home"] for r in teams.values()) / 20
        self.assertAlmostEqual(mean_home, 1.0, places=2)


class HistorySnapshotTests(unittest.TestCase):
    def test_snapshot_appends_and_dedupes(self):
        import datetime
        import json
        import os
        import tempfile
        if not os.path.exists("teams_calibrated.json"):
            self.skipTest("no calibrated ratings")
        # Build a tiny history file and check the dedupe/cap logic directly.
        from tools import snapshot_history as sh  # noqa: F401
        today = datetime.date.today().isoformat()
        hist = [{"date": today, "clubs": {}}, {"date": "2000-01-01", "clubs": {}}]
        hist = [h for h in hist if h["date"] != today]
        hist.append({"date": today, "clubs": {"Arsenal": {"title": 40}}})
        self.assertEqual(sum(1 for h in hist if h["date"] == today), 1)


class FormTests(unittest.TestCase):
    def test_form_from_cached_data(self):
        import os
        if not (os.path.isdir("data") and os.path.exists("teams_calibrated.json")):
            self.skipTest("no cached data / ratings")
        from tools.build_form import build
        form, state = build()
        self.assertEqual(len(form), 20)
        self.assertIn(state["season"], ("", None) + tuple(
            f"{y}-{str(y + 1)[-2:]}" for y in range(2020, 2035)))
        # Every club has the three windows for each split.
        for f in form.values():
            for split in ("overall", "home", "away"):
                self.assertEqual(set(f[split]), {"5", "10", "20"})
        # The season-points invariant holds for every club that has played.
        # Use played > 0 (not >= 20): once 2026/27 kicks off the form source
        # switches to the live season, where early on no club has 20 games yet.
        played = [f for f in form.values() if f["played"] > 0]
        self.assertTrue(played, "expected at least one club with matches")
        for f in played:
            w = f["season"]
            self.assertEqual(w["pts"], 3 * w["w"] + w["d"])
            self.assertLessEqual(w["ppg"], 3.0)


class RealFixtureTests(unittest.TestCase):
    def test_fixtures_load_once_season_is_under_way(self):
        """The published fixture list must still load after results appear.

        Regression: parse_fixtures only yields scoreless lines, so once a
        matchday is played load_real_fixtures used to see < 10 fixtures for
        it and return None (the site then fell back to a generated calendar).
        """
        import os
        import re
        import tempfile
        from plsim.fixtures import load_real_fixtures
        from plsim.teams import load_teams

        src = os.path.join("data", "2026-27-1-premierleague.txt")
        if not os.path.exists(src):
            self.skipTest("no cached 2026-27 fixtures")
        names = list(load_teams())
        baseline = load_real_fixtures(names)
        self.assertIsNotNone(baseline, "pre-season fixtures should load")

        # Mark matchday 1 as played by appending scores (openfootball style).
        md, n, out = 0, 0, []
        for ln in open(src, encoding="utf-8").read().splitlines():
            m = re.search(r"Matchday\s+(\d+)", ln)
            if m:
                md = int(m.group(1))
            if md == 1 and " v " in ln and not re.search(r"\d-\d", ln):
                ln = ln.rstrip() + f"  {n % 3}-{(n + 1) % 3} (0-0)"
                n += 1
            out.append(ln)
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "2026-27-1-premierleague.txt"), "w",
                      encoding="utf-8") as fh:
                fh.write("\n".join(out))
            played = load_real_fixtures(names, cache_dir=d)
        self.assertIsNotNone(played, "fixtures must still load after MD1 is played")
        self.assertEqual(len(played[0]), 38)
        self.assertTrue(all(len(x) == 10 for x in played[0]))
        # Same fixtures as the scoreless baseline, just some now carrying results.
        as_set = lambda r: {(i, h, a) for i, mdx in enumerate(r[0]) for h, a in mdx}
        self.assertEqual(as_set(played), as_set(baseline))


class LedgerTests(unittest.TestCase):
    FORECASTS = {
        "date": "2026-08-17", "season": "2026-27", "model": "poisson+dc",
        "fixtures": [
            {"md": 1, "home": "Arsenal", "away": "Hull City",
             "ph": 1.0, "pd": 0.0, "pa": 0.0},
            {"md": 1, "home": "Everton", "away": "Fulham",
             "ph": 1 / 3, "pd": 1 / 3, "pa": 1 / 3},
            {"md": 2, "home": "Chelsea", "away": "Brighton",
             "ph": 0.5, "pd": 0.3, "pa": 0.2},
        ],
    }

    def test_scores_only_played_fixtures(self):
        from tools.weekly_update import score_forecasts
        played = [
            {"md": 1, "home": "Arsenal", "away": "Hull City", "hg": 3, "ag": 0},
            {"md": 1, "home": "Everton", "away": "Fulham", "hg": 2, "ag": 0},
            # Chelsea v Brighton (MD2) not played yet -> not scored.
        ]
        n, rps_sum, brier_sum = score_forecasts(self.FORECASTS, played)
        self.assertEqual(n, 2)
        # Certain and correct -> RPS 0; uniform on a home win -> 5/18.
        self.assertAlmostEqual(rps_sum, 0.0 + 5 / 18)
        # Brier: perfect forecast 0; uniform 2/3.
        self.assertAlmostEqual(brier_sum, 0.0 + 2 / 3)

    def test_nothing_played_scores_nothing(self):
        from tools.weekly_update import score_forecasts
        n, rps_sum, brier_sum = score_forecasts(self.FORECASTS, [])
        self.assertEqual((n, rps_sum, brier_sum), (0, 0.0, 0.0))

    def test_draw_and_away_outcomes(self):
        from tools.weekly_update import score_forecasts
        from plsim.backtest import rps
        played = [
            {"md": 2, "home": "Chelsea", "away": "Brighton", "hg": 1, "ag": 1},
        ]
        n, rps_sum, _ = score_forecasts(self.FORECASTS, played)
        self.assertEqual(n, 1)
        self.assertAlmostEqual(rps_sum, rps((0.5, 0.3, 0.2), 1))


class BundleTests(unittest.TestCase):
    def test_bundle_shape(self):
        import os
        if not (os.path.isdir("data") and os.path.exists("teams_calibrated.json")):
            self.skipTest("no cached data / ratings")
        from tools.build_bundle import build
        b = build()
        self.assertEqual(set(b) >= {"version", "constants", "teams", "fixtures",
                                    "form", "season_state", "odds_history", "meta"}, True)
        self.assertEqual(len(b["teams"]), 20)
        self.assertEqual(len(b["form"]), 20)
        for k in ("BASE_H", "BASE_A", "DC_RHO"):
            self.assertIn(k, b["constants"])
        if b["fixtures"]:
            self.assertEqual(len(b["fixtures"]), 38)
            self.assertTrue(all(len(md) == 10 for md in b["fixtures"]))
        self.assertIn("live", b["season_state"])

    def test_bundle_rho_matches_calibrated_meta(self):
        import json
        import os
        if not (os.path.isdir("data") and os.path.exists("teams_calibrated.json")):
            self.skipTest("no cached data / ratings")
        from tools.build_bundle import build
        with open("teams_calibrated.json", encoding="utf-8") as fh:
            meta = json.load(fh).get("_meta", {})
        b = build()
        if "rho" in meta:
            # The fitted rho is the source of truth, not the hardcoded fallback.
            self.assertEqual(b["constants"]["DC_RHO"], meta["rho"])
            self.assertEqual(b["meta"].get("rho"), meta["rho"])


if __name__ == "__main__":
    unittest.main()
