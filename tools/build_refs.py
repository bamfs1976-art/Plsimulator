"""Build data/referees.json — the week's match-official assignments.

The Premier League announces referee appointments a few days before each
matchday, but there is no stable machine-readable feed, so this tool
structures a hand-collected list rather than scraping one. Feed it a small
CSV (path argument, or stdin with ``-``):

    home,away,referee
    Arsenal,Coventry City,Michael Oliver
    Hull City,Manchester United,Anthony Taylor

    python3 tools/build_refs.py appointments.csv

Club names are forgiving: exact bundle names, openfootball "FC" names and
unambiguous substrings ("Spurs" won't work, "Tottenham" will) all resolve.
The matchday number is inferred from the official fixture list, so it never
needs to be supplied. Output goes to data/referees.json, which
tools/build_bundle.py folds into model.json under ``referees``; consumers
match assignments to fixtures by the (home, away) pairing.

Assignments are cumulative across runs within a season — feeding matchday 2
keeps matchday 1's rows — so the season's referee history accretes. Rerun
with corrected rows to overwrite a fixture's referee.
"""

import csv
import datetime
import json
import os
import sys

sys.path.insert(0, ".")

from plsim.calibrate import NAME_MAP  # noqa: E402
from plsim.fixtures import load_real_fixtures  # noqa: E402

OUT_PATH = "data/referees.json"


def resolve_club(raw, names):
    """Map a hand-typed club name onto a bundle team name, or None."""
    raw = raw.strip()
    if raw in names:
        return raw
    if raw in NAME_MAP:
        return NAME_MAP[raw]
    low = raw.lower()
    hits = [n for n in names if low in n.lower() or n.lower() in low]
    return hits[0] if len(hits) == 1 else None


def matchday_index(fixtures):
    """(home, away) -> matchday number for the official calendar."""
    return {
        (home, away): md
        for md, pairs in enumerate(fixtures, start=1)
        for home, away in pairs
    }


def parse_rows(fh, names, md_of):
    matches, errors = [], []
    for lineno, row in enumerate(csv.reader(fh), start=1):
        row = [c.strip() for c in row if c.strip()]
        if not row or row[0].lower() == "home":
            continue
        if len(row) != 3:
            errors.append(f"line {lineno}: expected home,away,referee")
            continue
        home, away = resolve_club(row[0], names), resolve_club(row[1], names)
        if not home or not away:
            errors.append(f"line {lineno}: unknown club in {row[:2]}")
            continue
        md = md_of.get((home, away))
        if md is None:
            errors.append(f"line {lineno}: no fixture {home} v {away}")
            continue
        matches.append({"md": md, "home": home, "away": away, "ref": row[2]})
    return matches, errors


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    with open("teams_calibrated.json", encoding="utf-8") as fh:
        ratings = json.load(fh)
    ratings.pop("_meta", None)
    names = list(ratings)
    real = load_real_fixtures(names)
    if not real:
        print("official fixture list not cached; cannot infer matchdays")
        return 1
    md_of = matchday_index(real[0])

    if argv[1] == "-":
        matches, errors = parse_rows(sys.stdin, names, md_of)
    else:
        with open(argv[1], encoding="utf-8") as fh:
            matches, errors = parse_rows(fh, names, md_of)
    for err in errors:
        print(f"skipped: {err}")
    if not matches:
        print("no valid assignments parsed; data/referees.json unchanged")
        return 1

    existing = []
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as fh:
            existing = json.load(fh).get("matches", [])
    merged = {(m["home"], m["away"]): m for m in existing}
    merged.update({(m["home"], m["away"]): m for m in matches})
    out = {
        "updated": datetime.date.today().isoformat(),
        "matches": sorted(merged.values(), key=lambda m: (m["md"], m["home"])),
    }
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print(f"{OUT_PATH}: {len(out['matches'])} assignments "
          f"({len(matches)} new/updated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
