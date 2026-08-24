"""Tests for the odds de-vigging methods (plsim.devig)."""

import unittest

from plsim import devig


class TestDevig(unittest.TestCase):
    def test_proportional_sums_to_one(self):
        probs = devig.proportional([1.5, 4.0, 7.0])
        self.assertAlmostEqual(sum(probs), 1.0, places=9)
        # Shorter odds -> higher probability.
        self.assertGreater(probs[0], probs[1])
        self.assertGreater(probs[1], probs[2])

    def test_shin_sums_to_one(self):
        probs, z = devig.shin([1.5, 4.0, 7.0])
        self.assertAlmostEqual(sum(probs), 1.0, places=9)
        self.assertGreaterEqual(z, 0.0)
        self.assertLess(z, 1.0)

    def test_shin_removes_margin(self):
        # A vigged book (implied probs sum > 1) must map to fair probs summing to 1.
        odds = [2.0, 3.5, 3.6]  # ~1.06 booksum
        p_prop = devig.proportional(odds)
        p_shin, z = devig.shin(odds)
        self.assertAlmostEqual(sum(p_prop), 1.0, places=9)
        self.assertAlmostEqual(sum(p_shin), 1.0, places=9)
        # Favourite-longshot bias: Shin removes relatively more margin from
        # longshots, so the favourite's fair prob rises vs proportional and
        # the longest-priced outcome falls.
        fav = odds.index(min(odds))
        dog = odds.index(max(odds))
        self.assertGreaterEqual(p_shin[fav], p_prop[fav] - 1e-9)
        self.assertLessEqual(p_shin[dog], p_prop[dog] + 1e-9)

    def test_fair_book_gives_zero_z(self):
        # A margin-free book (probabilities already sum to 1) -> z ~ 0.
        odds = [2.0, 4.0, 4.0]  # 0.5 + 0.25 + 0.25 = 1.0
        probs, z = devig.shin(odds)
        self.assertAlmostEqual(sum(probs), 1.0, places=9)
        self.assertLess(z, 1e-3)


if __name__ == "__main__":
    unittest.main()
