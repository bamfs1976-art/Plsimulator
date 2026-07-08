"""Fit team ratings from historical match data (openfootball).

Downloads Premier League and Championship results for recent seasons from
the public-domain openfootball/england dataset (cached locally in
``data/``), then produces a ratings JSON usable with ``--teams``:

- **attack / defence** come from a weighted iterative Poisson fit
  (maximum likelihood): lambda = base x attack(scorer) x defence(conceder),
  with separate home/away baselines. Both divisions are fitted jointly, so
  promoted clubs' Championship goals are anchored to Premier League level
  through the clubs that moved between divisions.
- **elo** comes from a chronological Elo pass over the same matches.

Recent seasons count more (exponential decay), and ratings are shrunk
toward league-average in proportion to how much (weighted) data a club
has, which keeps promoted clubs from being over-trusted.
"""

import json
import math
import os
import re
import urllib.request

from .teams import BASE_HOME_GOALS, BASE_AWAY_GOALS, DEFAULT_TEAMS

DATA_URL = "https://raw.githubusercontent.com/openfootball/england/master/{season}/{fname}"
DIVISION_FILES = {1: "1-premierleague.txt", 2: "2-championship.txt"}
DEFAULT_SEASONS = ("2023-24", "2024-25", "2025-26")
SEASON_DECAY = 0.5          # weight halves per season into the past
FIT_ITERATIONS = 60
SHRINK_MATCHES = 15.0       # weighted matches at which shrinkage is 50/50
ELO_K = 24.0
ELO_HOME = 60.0
ELO_START = 1500.0
ELO_TARGET_MEAN = 1725.0    # recentre fitted Elo near the default scale

# openfootball club names -> plsim names for the 2026/27 clubs
NAME_MAP = {
    "Arsenal FC": "Arsenal",
    "Manchester City FC": "Manchester City",
    "Liverpool FC": "Liverpool",
    "Manchester United FC": "Manchester United",
    "Chelsea FC": "Chelsea",
    "Aston Villa FC": "Aston Villa",
    "Newcastle United FC": "Newcastle United",
    "Tottenham Hotspur FC": "Tottenham Hotspur",
    "Crystal Palace FC": "Crystal Palace",
    "Brighton & Hove Albion FC": "Brighton",
    "Nottingham Forest FC": "Nottingham Forest",
    "AFC Bournemouth": "Bournemouth",
    "Brentford FC": "Brentford",
    "Fulham FC": "Fulham",
    "Everton FC": "Everton",
    "Sunderland AFC": "Sunderland",
    "Leeds United FC": "Leeds United",
    "Coventry City FC": "Coventry City",
    "Ipswich Town FC": "Ipswich Town",
    "Hull City AFC": "Hull City",
}

# "Home FC v Away FC  2-1 (1-0)"  (2024-25 onwards)
_MATCH_V_RE = re.compile(
    r"^\s*(?:\d{1,2}[.:]\d{2}\s+)?"          # optional kick-off time
    r"(.+?)\s+v\s+(.+?)"                     # home v away
    r"\s+(\d+)-(\d+)\s*(?:\(\d+-\d+\))?\s*$"  # full-time (half-time) score
)
# "Home FC  2-1 (1-0)  Away FC"  (older files put the score in the middle)
_MATCH_MID_RE = re.compile(
    r"^\s*(?:\d{1,2}[.:]\d{2}\s+)?"
    r"(.+?)\s+(\d+)-(\d+)\s*(?:\(\d+-\d+\))?\s+(\S.*?)\s*$"
)
_MATCHDAY_RE = re.compile(r"Matchday\s+(\d+)")
_STAGE_RE = re.compile(r"^\s*[▪=]")           # section headers


def fetch_file(season, division, cache_dir="data", download=True):
    """Return the raw text for one season/division, caching on disk."""
    fname = DIVISION_FILES[division]
    path = os.path.join(cache_dir, f"{season}-{fname}")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    if not download:
        raise FileNotFoundError(f"{path} missing and downloads disabled")
    url = DATA_URL.format(season=season, fname=fname)
    with urllib.request.urlopen(url, timeout=60) as resp:
        text = resp.read().decode("utf-8")
    os.makedirs(cache_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text


def parse_matches(text):
    """Yield (matchday, home, away, hg, ag) from an openfootball file.

    Handles both line layouts ("Home v Away  2-1" and the older
    "Home  2-1  Away") and skips non-league stages such as the
    Championship playoffs.
    """
    matchday = 0
    in_league_stage = True
    for line in text.splitlines():
        if _STAGE_RE.match(line):
            md = _MATCHDAY_RE.search(line)
            if md:
                matchday = int(md.group(1))
                in_league_stage = True
            else:
                in_league_stage = line.lstrip().startswith("=")
            continue
        if not in_league_stage or line.lstrip().startswith("#"):
            continue
        m = _MATCH_V_RE.match(line)
        if m:
            home, away, hg, ag = m.groups()
        else:
            m = _MATCH_MID_RE.match(line)
            if not m:
                continue
            home, hg, ag, away = m.groups()
        yield matchday, home.strip(), away.strip(), int(hg), int(ag)


def load_matches(seasons=DEFAULT_SEASONS, cache_dir="data", download=True):
    """All matches as (season_idx, weight, division, matchday, home, away, hg, ag).

    season_idx counts from 0 = oldest; weight applies SEASON_DECAY.
    """
    matches = []
    n = len(seasons)
    for idx, season in enumerate(seasons):
        weight = SEASON_DECAY ** (n - 1 - idx)
        for division in DIVISION_FILES:
            text = fetch_file(season, division, cache_dir, download)
            for md, home, away, hg, ag in parse_matches(text):
                matches.append((idx, weight, division, md, home, away, hg, ag))
    return matches


def fit_poisson(matches):
    """Weighted iterative Poisson fit -> (attack, defence, base_h, base_a).

    attack/defence are dicts over every club seen (raw openfootball names),
    each normalised to mean 1.0; base_h/base_a are the fitted average
    home/away goal rates between two average sides.
    """
    teams = sorted({m[4] for m in matches} | {m[5] for m in matches})
    att = {t: 1.0 for t in teams}
    dfn = {t: 1.0 for t in teams}
    w_total = sum(m[1] for m in matches)
    base_h = sum(m[1] * m[6] for m in matches) / w_total
    base_a = sum(m[1] * m[7] for m in matches) / w_total

    for _ in range(FIT_ITERATIONS):
        scored = {t: 0.0 for t in teams}
        exp_scored = {t: 1e-9 for t in teams}
        conceded = {t: 0.0 for t in teams}
        exp_conceded = {t: 1e-9 for t in teams}
        for _s, w, _d, _md, home, away, hg, ag in matches:
            lam_h = base_h * att[home] * dfn[away]
            lam_a = base_a * att[away] * dfn[home]
            scored[home] += w * hg
            exp_scored[home] += w * lam_h
            scored[away] += w * ag
            exp_scored[away] += w * lam_a
            conceded[home] += w * ag
            exp_conceded[home] += w * lam_a
            conceded[away] += w * hg
            exp_conceded[away] += w * lam_h
        for t in teams:
            att[t] *= math.sqrt(scored[t] / exp_scored[t])
            dfn[t] *= math.sqrt(conceded[t] / exp_conceded[t])
        # Renormalise multipliers to mean 1, folding scale into the bases.
        mean_att = sum(att.values()) / len(teams)
        mean_dfn = sum(dfn.values()) / len(teams)
        for t in teams:
            att[t] /= mean_att
            dfn[t] /= mean_dfn
        base_h *= mean_att * mean_dfn
        base_a *= mean_att * mean_dfn
    return att, dfn, base_h, base_a


def fit_elo(matches):
    """Chronological Elo over all matches -> dict of raw ratings."""
    elo = {}
    ordered = sorted(matches, key=lambda m: (m[0], m[3], m[2]))
    for _s, _w, _d, _md, home, away, hg, ag in ordered:
        rh = elo.setdefault(home, ELO_START)
        ra = elo.setdefault(away, ELO_START)
        expected = 1.0 / (1.0 + 10.0 ** (-(rh - ra + ELO_HOME) / 400.0))
        actual = 1.0 if hg > ag else (0.5 if hg == ag else 0.0)
        delta = ELO_K * (actual - expected)
        elo[home] = rh + delta
        elo[away] = ra - delta
    return elo


def calibrate(seasons=DEFAULT_SEASONS, cache_dir="data", download=True):
    """Fit ratings for the 20 2026/27 clubs -> (ratings dict, info dict)."""
    matches = load_matches(seasons, cache_dir, download)
    if not matches:
        raise RuntimeError("no matches parsed - check the data files")
    missing = [raw for raw in NAME_MAP if not any(
        raw in (m[4], m[5]) for m in matches)]
    if missing:
        raise RuntimeError(f"no match data found for: {', '.join(missing)}")

    att, dfn, base_h, base_a = fit_poisson(matches)
    elo = fit_elo(matches)

    # Weighted match count per club, for data-proportional shrinkage.
    data_weight = {}
    for _s, w, _d, _md, home, away, _hg, _ag in matches:
        data_weight[home] = data_weight.get(home, 0.0) + w
        data_weight[away] = data_weight.get(away, 0.0) + w

    ratings = {}
    for raw, name in NAME_MAP.items():
        trust = data_weight[raw] / (data_weight[raw] + SHRINK_MATCHES)
        ratings[name] = {
            "attack": 1.0 + trust * (att[raw] - 1.0),
            "defence": 1.0 + trust * (dfn[raw] - 1.0),
            "elo": elo[raw],
        }

    # Renormalise over the 20 clubs: multipliers to mean 1.0, and fold the
    # fitted scoring level into attack so the fixed model baselines
    # (BASE_HOME_GOALS/BASE_AWAY_GOALS) reproduce the fitted goal rates.
    mean_att = sum(r["attack"] for r in ratings.values()) / len(ratings)
    mean_dfn = sum(r["defence"] for r in ratings.values()) / len(ratings)
    level = (base_h + base_a) / (BASE_HOME_GOALS + BASE_AWAY_GOALS)
    mean_elo = sum(r["elo"] for r in ratings.values()) / len(ratings)
    for r in ratings.values():
        r["attack"] = round(r["attack"] / mean_att * level, 4)
        r["defence"] = round(r["defence"] / mean_dfn, 4)
        r["elo"] = round(r["elo"] - mean_elo + ELO_TARGET_MEAN, 1)

    info = {
        "matches": len(matches),
        "seasons": list(seasons),
        "base_home": base_h,
        "base_away": base_a,
    }
    return ratings, info


def write_ratings(ratings, path):
    order = [n for n in DEFAULT_TEAMS if n in ratings]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({n: ratings[n] for n in order}, fh, indent=2)
        fh.write("\n")
