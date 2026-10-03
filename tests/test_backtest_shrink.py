"""The matchday-block interval in tools/backtest_shrink.py."""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from backtest_shrink import paired_interval  # noqa: E402


def season(shift, seed, matchdays=38, per=10, shock=0.0):
    rnd = random.Random(seed)
    rows = []
    for md in range(matchdays):
        s = rnd.gauss(0, shock)
        for _ in range(per):
            a = 0.2 + rnd.gauss(0, 0.05)
            rows.append({"block": md, "a": a, "b": a + shift + s + rnd.gauss(0, 0.01)})
    return rows


class PairedIntervalTests(unittest.TestCase):
    def test_reproducible(self):
        rows = season(-0.002, 1)
        self.assertEqual(paired_interval(rows, "a", "b"), paired_interval(rows, "a", "b"))

    def test_finds_a_real_gain_and_a_real_loss(self):
        self.assertEqual(paired_interval(season(-0.005, 2), "a", "b")[3], "better")
        self.assertEqual(paired_interval(season(0.005, 3), "a", "b")[3], "worse")

    def test_estimate_is_the_pooled_mean_difference(self):
        rows = season(-0.003, 4)
        direct = sum(r["b"] - r["a"] for r in rows) / len(rows)
        self.assertAlmostEqual(paired_interval(rows, "a", "b")[0], direct, places=12)

    def test_noise_is_rarely_called_a_gain(self):
        alarms = sum(paired_interval(season(0.0, s, shock=0.01), "a", "b", reps=300, seed=s)[3] != "unclear"
                     for s in range(60))
        self.assertLessEqual(alarms, 8)


if __name__ == "__main__":
    unittest.main()
