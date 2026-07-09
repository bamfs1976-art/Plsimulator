"""Inject teams_calibrated.json into index.html's calibrated-data block."""

import json
import re

with open("teams_calibrated.json", encoding="utf-8") as fh:
    ratings = json.load(fh)

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

with open("index.html", "w", encoding="utf-8") as fh:
    fh.write(html)
print("embedded", len(ratings), "teams into index.html")
