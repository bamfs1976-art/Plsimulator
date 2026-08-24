#!/usr/bin/env python3
"""Generate sitemap.xml for the deployed site.

Lists the home route and every generated per-club route (clubs/<slug>/).
The in-app tabs (Season odds, Matchday forecast, …) are JavaScript views
on the home page, not real URLs, so they are deliberately not listed.
The lastmod date comes from the model bundle's recalibration date, so the
sitemap ages with the weekly update. Run after tools/build_clubs.py:

    python3 tools/build_sitemap.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SITE = "https://plsimulation.netlify.app"


def lastmod():
    try:
        with open(os.path.join(ROOT, "model.json"), encoding="utf-8") as fh:
            season = json.load(fh).get("season_state") or {}
        return season.get("updated") or ""
    except (OSError, ValueError):
        return ""


def club_slugs():
    clubs_dir = os.path.join(ROOT, "clubs")
    if not os.path.isdir(clubs_dir):
        return []
    return sorted(
        d for d in os.listdir(clubs_dir)
        if os.path.isfile(os.path.join(clubs_dir, d, "index.html"))
    )


def url_entry(loc, mod, priority):
    parts = [f"  <url>", f"    <loc>{loc}</loc>"]
    if mod:
        parts.append(f"    <lastmod>{mod}</lastmod>")
    parts.append(f"    <changefreq>weekly</changefreq>")
    parts.append(f"    <priority>{priority}</priority>")
    parts.append("  </url>")
    return "\n".join(parts)


def build():
    mod = lastmod()
    entries = [url_entry(f"{SITE}/", mod, "1.0")]
    for slug in club_slugs():
        entries.append(url_entry(f"{SITE}/clubs/{slug}/", mod, "0.7"))
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )
    out = os.path.join(ROOT, "sitemap.xml")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(xml)
    print(f"Wrote {out} with {len(entries)} URLs (1 home + {len(entries) - 1} clubs).")


if __name__ == "__main__":
    build()
