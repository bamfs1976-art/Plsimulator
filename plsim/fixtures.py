"""Fixture list generation: a double round-robin over 38 matchdays.

Uses the circle (Berger) method for the first 19 rounds, then mirrors them
with venues swapped. The team order is shuffled with a fixed seed so the
calendar is stable across runs but not alphabetical.
"""

import datetime
import random

SCHEDULE_SEED = 20262027
FIRST_MATCHDAY = datetime.date(2026, 8, 15)  # nominal opening Saturday


def generate_fixtures(team_names):
    """Return a list of 38 matchdays; each is a list of (home, away) tuples."""
    teams = sorted(team_names)
    random.Random(SCHEDULE_SEED).shuffle(teams)
    n = len(teams)
    if n % 2:
        raise ValueError("need an even number of teams")

    fixed, rest = teams[0], teams[1:]
    first_half = []
    for rnd in range(n - 1):
        rotation = rest[rnd:] + rest[:rnd]
        pairs = []
        # Fixed team alternates home/away round by round.
        if rnd % 2 == 0:
            pairs.append((fixed, rotation[0]))
        else:
            pairs.append((rotation[0], fixed))
        for i in range(1, n // 2):
            a, b = rotation[i], rotation[-i]
            if i % 2 == rnd % 2:
                pairs.append((a, b))
            else:
                pairs.append((b, a))
        first_half.append(pairs)

    second_half = [[(away, home) for home, away in rnd] for rnd in first_half]
    return first_half + second_half


def matchday_date(matchday):
    """Nominal date for a matchday (1-38): weekly from mid-August 2026."""
    return FIRST_MATCHDAY + datetime.timedelta(weeks=matchday - 1)


def all_matches(matchdays):
    """Flatten to a list of (matchday_number, home, away)."""
    return [
        (md + 1, home, away)
        for md, fixtures in enumerate(matchdays)
        for home, away in fixtures
    ]
