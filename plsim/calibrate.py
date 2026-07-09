"""Fit team ratings from historical match data (openfootball).

Downloads Premier League and Championship results for recent seasons from
the public-domain openfootball/england dataset (cached locally in
``data/``), then produces a ratings JSON usable with ``--teams``:

- **attack / defence** come from a weighted iterative Poisson fit
  (maximum likelihood): lambda = base x attack(scorer) x defence(conceder),
  with separate home/away baselines. Both divisions are fitted jointly, so
  promoted clubs' Championship goals are anchored to Premier League level
  through the clubs that moved between divisions.
- **home** is a per-club home-advantage multiplier (mean 1.0), fitted with
  shrinkage toward neutral so small samples cannot produce wild values.
- **elo** comes from a chronological Elo pass over the same matches.
- **rho**, the Dixon-Coles low-score correlation, is fitted by maximum
  likelihood and stored in the ratings file's ``_meta`` block.

Matches are weighted by exponential decay on the match *date* (half-life
``DECAY_HALF_LIFE_DAYS``, chosen by backtest), so last month's form counts more than last
season's. Ratings are additionally shrunk toward league-average in
proportion to how much weighted data a club has, which keeps promoted
clubs from being over-trusted. These choices are validated by the
backtesting harness in ``plsim.backtest`` (see ``plsim backtest``).
"""

import datetime
import json
import math
import os
import re
import urllib.request

from .teams import BASE_HOME_GOALS, BASE_AWAY_GOALS, DEFAULT_TEAMS

DATA_URL = "https://raw.githubusercontent.com/openfootball/england/master/{season}/{fname}"
DIVISION_FILES = {1: "1-premierleague.txt", 2: "2-championship.txt"}
DEFAULT_SEASONS = ("2023-24", "2024-25", "2025-26")
DECAY_HALF_LIFE_DAYS = 250  # weight halves every ~8 months (backtest-validated)
FIT_ITERATIONS = 60
SHRINK_MATCHES = 15.0       # weighted matches at which att/def shrinkage is 50/50
HOME_PRIOR_MATCHES = 12.0   # pseudo-matches anchoring each club's home factor at 1.0
RHO_RANGE = (-0.30, 0.10)   # search window for the Dixon-Coles correlation
XG_ALPHA = 0.4              # xG share of the fit target (backtest-validated)
# First-PL-season factors for promoted clubs vs their Championship-implied
# ratings, estimated over 28 promoted-club seasons 2016-26 (see README):
PROMOTED_ATT = 0.59
PROMOTED_DEF = 1.57
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
_DATE_RE = re.compile(
    r"^\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"([A-Z][a-z]{2})[a-z]*\s+(\d{1,2})(?:\s+(\d{4}))?\s*$"
)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


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


def _season_year(season, month):
    """Calendar year for a month within a 'YYYY-YY' season string."""
    start = int(season.split("-")[0])
    return start if month >= 7 else start + 1


def parse_matches(text, season=None):
    """Yield (matchday, date, home, away, hg, ag) from an openfootball file.

    Handles both line layouts ("Home v Away  2-1" and the older
    "Home  2-1  Away"), tracks the date headers between fixtures, and
    skips non-league stages such as the Championship playoffs. ``date``
    is a ``datetime.date`` when a date header has been seen (the year is
    inferred from ``season`` when the header omits it), else None.
    """
    matchday = 0
    date = None
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
        d = _DATE_RE.match(line)
        if d:
            mon, day, year = _MONTHS.get(d.group(1)), int(d.group(2)), d.group(3)
            if mon:
                if year:
                    y = int(year)
                elif season:
                    y = _season_year(season, mon)
                else:
                    y = None
                if y:
                    try:
                        date = datetime.date(y, mon, day)
                    except ValueError:
                        pass
            continue
        m = _MATCH_V_RE.match(line)
        if m:
            home, away, hg, ag = m.groups()
        else:
            m = _MATCH_MID_RE.match(line)
            if not m:
                continue
            home, hg, ag, away = m.groups()
        yield matchday, date, home.strip(), away.strip(), int(hg), int(ag)


def parse_fixtures(text, season=None):
    """Yield (matchday, date, home, away) for scheduled (scoreless) fixtures."""
    fixture_re = re.compile(
        r"^\s*(?:\d{1,2}[.:]\d{2}\s+)?(.+?)\s+v\s+(\S.*?)\s*$")
    matchday = 0
    date = None
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
        d = _DATE_RE.match(line)
        if d:
            mon, day, year = _MONTHS.get(d.group(1)), int(d.group(2)), d.group(3)
            if mon:
                y = int(year) if year else (_season_year(season, mon) if season else None)
                if y:
                    try:
                        date = datetime.date(y, mon, day)
                    except ValueError:
                        pass
            continue
        if _MATCH_V_RE.match(line) or _MATCH_MID_RE.match(line):
            continue  # played match, not a scheduled fixture
        m = fixture_re.match(line)
        if m:
            yield matchday, date, m.group(1).strip(), m.group(2).strip()


def load_matches(seasons=DEFAULT_SEASONS, cache_dir="data", download=True):
    """All matches as dicts, chronologically sortable.

    Keys: season_idx (0 = oldest), season, division, matchday, date,
    home, away, hg, ag.
    """
    matches = []
    for idx, season in enumerate(seasons):
        for division in DIVISION_FILES:
            text = fetch_file(season, division, cache_dir, download)
            for md, date, home, away, hg, ag in parse_matches(text, season):
                matches.append({
                    "season_idx": idx, "season": season, "division": division,
                    "matchday": md, "date": date,
                    "home": home, "away": away, "hg": hg, "ag": ag,
                })
    return matches


# openfootball names for clubs relegated since 2023 (xG join only)
_OF_EXTRA = {
    "Wolverhampton Wanderers FC": "Wolves", "West Ham United FC": "West Ham",
    "Burnley FC": "Burnley", "Luton Town FC": "Luton",
    "Sheffield United FC": "Sheffield United",
    "Leicester City FC": "Leicester", "Southampton FC": "Southampton",
}


def _canon(name):
    return NAME_MAP.get(name) or _OF_EXTRA.get(name) or name


def attach_xg(matches, cache_dir="data"):
    """Attach per-match team xG (m['hxg'], m['axg']) where files exist.

    xG comes from FPL's official per-player expected-goals, summed to
    team level per fixture (see tools/build_xg.py). Returns the number
    of matches that got xG attached.
    """
    import csv

    by_season = {}
    for season in {m["season"] for m in matches}:
        path = os.path.join(cache_dir, f"xg-{season}.csv")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                by_season[(season, r["home"], r["away"])] = (
                    float(r["hxg"]), float(r["axg"]))
    hit = 0
    for m in matches:
        xg = by_season.get((m["season"], _canon(m["home"]), _canon(m["away"])))
        if xg:
            m["hxg"], m["axg"] = xg
            hit += 1
    return hit


def decay_weights(matches, reference_date=None, half_life=DECAY_HALF_LIFE_DAYS):
    """Exponential time-decay weight per match, relative to reference_date.

    Matches without a parsed date fall back to a season-level midpoint
    estimate so they still decay sensibly.
    """
    if reference_date is None:
        dates = [m["date"] for m in matches if m["date"]]
        reference_date = max(dates) if dates else datetime.date.today()
    weights = []
    for m in matches:
        date = m["date"]
        if date is None:
            y = int(m["season"].split("-")[0])
            date = datetime.date(y + 1, 1, 15)  # mid-season fallback
        age = max(0, (reference_date - date).days)
        weights.append(0.5 ** (age / half_life))
    return weights


def fit_poisson(matches, weights, iterations=FIT_ITERATIONS, home_adv=True,
                xg_alpha=0.0):
    """Weighted iterative Poisson fit.

    Returns (attack, defence, home, base_h, base_a): attack/defence dicts
    over every club seen (mean 1.0); ``home`` is the per-club home
    multiplier (mean 1.0, shrunk toward 1 by HOME_PRIOR_MATCHES
    pseudo-matches); base_h/base_a are the fitted average home/away goal
    rates between two average sides on neutral home advantage.

    With ``xg_alpha`` > 0 the fit target for matches that carry xG (see
    attach_xg) becomes ``alpha*xG + (1-alpha)*goals`` — xG has far more
    signal per match than goals, so blending reduces noise. Matches
    without xG (e.g. the Championship) keep plain goals.
    """
    teams = sorted({m["home"] for m in matches} | {m["away"] for m in matches})
    targets = []
    for m in matches:
        if xg_alpha and m.get("hxg") is not None:
            targets.append((xg_alpha * m["hxg"] + (1 - xg_alpha) * m["hg"],
                            xg_alpha * m["axg"] + (1 - xg_alpha) * m["ag"]))
        else:
            targets.append((float(m["hg"]), float(m["ag"])))
    att = {t: 1.0 for t in teams}
    dfn = {t: 1.0 for t in teams}
    hom = {t: 1.0 for t in teams}
    w_total = sum(weights) or 1.0
    base_h = sum(w * t[0] for w, t in zip(weights, targets)) / w_total
    base_a = sum(w * t[1] for w, t in zip(weights, targets)) / w_total

    for _ in range(iterations):
        scored = {t: 0.0 for t in teams}
        exp_scored = {t: 1e-9 for t in teams}
        conceded = {t: 0.0 for t in teams}
        exp_conceded = {t: 1e-9 for t in teams}
        h_goals = {t: HOME_PRIOR_MATCHES * base_h for t in teams}
        h_exp = {t: HOME_PRIOR_MATCHES * base_h * hom[t] for t in teams}
        for w, m, (tg_h, tg_a) in zip(weights, matches, targets):
            home, away = m["home"], m["away"]
            lam_h = base_h * att[home] * dfn[away] * hom[home]
            lam_a = base_a * att[away] * dfn[home]
            scored[home] += w * tg_h
            exp_scored[home] += w * lam_h
            scored[away] += w * tg_a
            exp_scored[away] += w * lam_a
            conceded[home] += w * tg_a
            exp_conceded[home] += w * lam_a
            conceded[away] += w * tg_h
            exp_conceded[away] += w * lam_h
            h_goals[home] += w * tg_h
            h_exp[home] += w * lam_h
        for t in teams:
            att[t] *= math.sqrt(scored[t] / exp_scored[t])
            dfn[t] *= math.sqrt(conceded[t] / exp_conceded[t])
            if home_adv:
                hom[t] *= math.sqrt(h_goals[t] / h_exp[t])
        # Renormalise multipliers to mean 1, folding scale into the bases.
        mean_att = sum(att.values()) / len(teams)
        mean_dfn = sum(dfn.values()) / len(teams)
        mean_hom = sum(hom.values()) / len(teams)
        for t in teams:
            att[t] /= mean_att
            dfn[t] /= mean_dfn
            hom[t] /= mean_hom
        base_h *= mean_att * mean_dfn * mean_hom
        base_a *= mean_att * mean_dfn
    return att, dfn, hom, base_h, base_a


def promoted_adjust(att, dfn, matches, weights):
    """Adjust ratings for clubs whose evidence is mostly Championship play.

    Promoted clubs systematically underperform what a joint two-division
    fit implies for them (attack ~x0.59, defence ~x1.57 in their first
    PL season, measured over 28 club-seasons 2016-26). The adjustment is
    graded by each club's Championship share of weighted evidence, so it
    applies fully at season start and fades to nothing as real Premier
    League results accumulate. Modifies att/dfn in place.
    """
    div2 = {}
    total = {}
    for w, m in zip(weights, matches):
        for team in (m["home"], m["away"]):
            total[team] = total.get(team, 0.0) + w
            if m["division"] == 2:
                div2[team] = div2.get(team, 0.0) + w
    for team in att:
        share = div2.get(team, 0.0) / (total.get(team, 0.0) or 1.0)
        if share > 0:
            att[team] *= PROMOTED_ATT ** share
            dfn[team] *= PROMOTED_DEF ** share


def _dc_tau(h, a, lam_h, lam_a, rho):
    if h == 0 and a == 0:
        return 1.0 - lam_h * lam_a * rho
    if h == 0 and a == 1:
        return 1.0 + lam_h * rho
    if h == 1 and a == 0:
        return 1.0 + lam_a * rho
    if h == 1 and a == 1:
        return 1.0 - rho
    return 1.0


def fit_rho(matches, weights, att, dfn, hom, base_h, base_a,
            lo=RHO_RANGE[0], hi=RHO_RANGE[1]):
    """Maximum-likelihood Dixon-Coles rho by golden-section search."""
    lams = []
    for w, m in zip(weights, matches):
        lam_h = base_h * att[m["home"]] * dfn[m["away"]] * hom[m["home"]]
        lam_a = base_a * att[m["away"]] * dfn[m["home"]]
        lams.append((w, m["hg"], m["ag"], lam_h, lam_a))

    def loglik(rho):
        ll = 0.0
        for w, hg, ag, lh, la in lams:
            if hg <= 1 and ag <= 1:
                tau = max(_dc_tau(hg, ag, lh, la, rho), 1e-10)
                ll += w * math.log(tau)
        return ll

    invphi = (math.sqrt(5) - 1) / 2
    a, b = lo, hi
    c, d = b - invphi * (b - a), a + invphi * (b - a)
    fc, fd = loglik(c), loglik(d)
    for _ in range(40):
        if fc > fd:
            b, d, fd = d, c, fc
            c = b - invphi * (b - a)
            fc = loglik(c)
        else:
            a, c, fc = c, d, fd
            d = a + invphi * (b - a)
            fd = loglik(d)
    return round((a + b) / 2, 4)


def fit_elo(matches):
    """Chronological Elo over all matches -> dict of raw ratings."""
    elo = {}
    ordered = sorted(matches, key=lambda m: (
        m["season_idx"], m["date"] or datetime.date.min, m["matchday"]))
    for m in ordered:
        rh = elo.setdefault(m["home"], ELO_START)
        ra = elo.setdefault(m["away"], ELO_START)
        expected = 1.0 / (1.0 + 10.0 ** (-(rh - ra + ELO_HOME) / 400.0))
        actual = 1.0 if m["hg"] > m["ag"] else (0.5 if m["hg"] == m["ag"] else 0.0)
        delta = ELO_K * (actual - expected)
        elo[m["home"]] = rh + delta
        elo[m["away"]] = ra - delta
    return elo


def calibrate(seasons=DEFAULT_SEASONS, cache_dir="data", download=True,
              half_life=DECAY_HALF_LIFE_DAYS, xg_alpha=XG_ALPHA):
    """Fit ratings for the 20 2026/27 clubs -> (ratings dict, info dict).

    The ratings dict carries attack/defence/home/elo per club plus a
    ``_meta`` block with the fitted Dixon-Coles rho and fit settings.
    """
    matches = load_matches(seasons, cache_dir, download)
    if not matches:
        raise RuntimeError("no matches parsed - check the data files")
    missing = [raw for raw in NAME_MAP if not any(
        raw in (m["home"], m["away"]) for m in matches)]
    if missing:
        raise RuntimeError(f"no match data found for: {', '.join(missing)}")

    xg_hit = attach_xg(matches, cache_dir)
    weights = decay_weights(matches, half_life=half_life)
    att, dfn, hom, base_h, base_a = fit_poisson(matches, weights,
                                                xg_alpha=xg_alpha)
    rho = fit_rho(matches, weights, att, dfn, hom, base_h, base_a)
    elo = fit_elo(matches)

    # Weighted match count per club, for data-proportional shrinkage.
    data_weight = {}
    for w, m in zip(weights, matches):
        data_weight[m["home"]] = data_weight.get(m["home"], 0.0) + w
        data_weight[m["away"]] = data_weight.get(m["away"], 0.0) + w

    ratings = {}
    for raw, name in NAME_MAP.items():
        trust = data_weight[raw] / (data_weight[raw] + SHRINK_MATCHES)
        ratings[name] = {
            "attack": 1.0 + trust * (att[raw] - 1.0),
            "defence": 1.0 + trust * (dfn[raw] - 1.0),
            "home": hom[raw],
            "elo": elo[raw],
        }

    # Renormalise over the 20 clubs: multipliers to mean 1.0, and fold the
    # fitted scoring level into attack so the fixed model baselines
    # (BASE_HOME_GOALS/BASE_AWAY_GOALS) reproduce the fitted goal rates.
    mean_att = sum(r["attack"] for r in ratings.values()) / len(ratings)
    mean_dfn = sum(r["defence"] for r in ratings.values()) / len(ratings)
    mean_hom = sum(r["home"] for r in ratings.values()) / len(ratings)
    level = (base_h + base_a) / (BASE_HOME_GOALS + BASE_AWAY_GOALS)
    mean_elo = sum(r["elo"] for r in ratings.values()) / len(ratings)
    for r in ratings.values():
        r["attack"] = round(r["attack"] / mean_att * level, 4)
        r["defence"] = round(r["defence"] / mean_dfn, 4)
        r["home"] = round(r["home"] / mean_hom, 4)
        r["elo"] = round(r["elo"] - mean_elo + ELO_TARGET_MEAN, 1)

    info = {
        "matches": len(matches),
        "seasons": list(seasons),
        "base_home": base_h,
        "base_away": base_a,
        "rho": rho,
        "half_life_days": half_life,
        "xg_alpha": xg_alpha if xg_hit else 0.0,
        "xg_matches": xg_hit,
    }
    return ratings, info


def write_ratings(ratings, path, info=None):
    order = [n for n in DEFAULT_TEAMS if n in ratings]
    out = {n: ratings[n] for n in order}
    if info is not None:
        out["_meta"] = {
            "rho": info["rho"],
            "seasons": info["seasons"],
            "matches": info["matches"],
            "half_life_days": info["half_life_days"],
        }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
        fh.write("\n")
