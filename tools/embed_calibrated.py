"""Inject calibrated ratings and the real fixture list into index.html."""

import json
import re
import sys

sys.path.insert(0, ".")

from plsim.fixtures import load_real_fixtures  # noqa: E402

with open("teams_calibrated.json", encoding="utf-8") as fh:
    ratings = json.load(fh)
ratings.pop("_meta", None)  # fit metadata, not a team

with open("index.html", encoding="utf-8") as fh:
    html = fh.read()

block = (
    '<script id="calibrated-data">\n'
    "/* Written by tools/embed_calibrated.py from teams_calibrated.json */\n"
    f"CALIBRATED_TEAMS = {json.dumps(ratings)};\n"
    "</script>"
)
html, n = re.subn(
    r'<script id="calibrated-data">.*?</script>', block, html, flags=re.S
)
if n != 1:
    raise SystemExit("calibrated-data block not found in index.html")

real = load_real_fixtures(list(ratings))
if real:
    matchdays, _dates = real
    fx_block = (
        '<script id="fixtures-data">\n'
        "/* Official 2026/27 fixture list (openfootball), embedded by\n"
        "   tools/embed_calibrated.py; null falls back to a generated calendar. */\n"
        f"REAL_FIXTURES = {json.dumps(matchdays)};\n"
        "</script>"
    )
else:
    fx_block = ('<script id="fixtures-data">\nREAL_FIXTURES = null;\n</script>')
html, n = re.subn(
    r'<script id="fixtures-data">.*?</script>', fx_block, html, flags=re.S
)
if n != 1:
    raise SystemExit("fixtures-data block not found in index.html")

with open("index.html", "w", encoding="utf-8") as fh:
    fh.write(html)
print(f"embedded {len(ratings)} teams and "
      f"{'the official' if real else 'no'} fixture list into index.html")
