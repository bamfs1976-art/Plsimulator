"""Remove the bookmaker margin from decimal odds -> fair probabilities.

Two methods:

- ``proportional`` — divide each inverse-odds by the book sum. Simple, but
  assumes the margin is spread evenly across outcomes.
- ``shin`` — Shin (1992/1993) de-vigging, which models a proportion ``z``
  of insider (informed) money and removes more margin from short-priced
  favourites than from longshots. It is the more principled de-vig and is
  what sharp-odds analyses generally prefer.

Both return fair probabilities that sum to 1.
"""

import math


def proportional(odds):
    """Fair probabilities by normalising inverse decimal odds."""
    inv = [1.0 / o for o in odds]
    total = sum(inv)
    return [x / total for x in inv]


def shin(odds, iterations=100):
    """Shin fair probabilities plus the fitted insider proportion z.

    Returns ``(probs, z)``. ``z`` is 0 when the book carries no implied
    insider component (proportional and Shin then coincide).
    """
    r = [1.0 / o for o in odds]
    book = sum(r)

    def q(z):
        # Shin's fair-probability inversion for a given z.
        return [(math.sqrt(z * z + 4.0 * (1.0 - z) * ri * ri / book) - z)
                / (2.0 * (1.0 - z)) for ri in r]

    # sum(q(0)) = sqrt(book) >= 1; sum(q) decreases in z, so bisect for the
    # z that makes the fair probabilities sum to exactly 1.
    lo, hi = 0.0, 0.999
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        if sum(q(mid)) > 1.0:
            lo = mid
        else:
            hi = mid
    z = 0.5 * (lo + hi)
    probs = q(z)
    total = sum(probs)
    return [p / total for p in probs], z
