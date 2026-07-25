#!/usr/bin/env python3
"""Generate the static per-club routes at /clubs/<slug>/index.html.

Each page carries its own title, meta description, canonical URL, Open
Graph / Twitter tags and SportsTeam JSON-LD, and renders — as plain,
crawlable HTML — the club's finishing-position distribution, its current
title / top-4 / relegation odds and every remaining fixture's
win/draw/loss probability.

The numbers come from the deployed model bundle (model.json) run through
the existing plsim engine (no engine changes): a Monte Carlo for the
position distribution and the same Poisson + Dixon-Coles score grid the
site uses for per-match outcomes. Regenerate after each recalibration:

    python3 tools/build_clubs.py
"""
import html
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from plsim import models, simulate  # noqa: E402
from plsim.simulate import Aggregate  # noqa: E402

SIMS = 8000
SEED = 42
SITE = "https://plsimulation.netlify.app"


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def club_colors():
    with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"const CLUB_COLOR = (\{.*?\});", text, re.S)
    return json.loads(m.group(1)) if m else {}


def load_bundle():
    with open(os.path.join(ROOT, "model.json"), encoding="utf-8") as fh:
        return json.load(fh)


def run_montecarlo(teams, fixtures, rho, results):
    """Position distribution per club from the shared plsim engine."""
    model = models.make_model("poisson", teams)
    lambdas = []
    for i, md in enumerate(fixtures, start=1):
        for home, away in md:
            lh, la = model.lambdas(home, away)
            lambdas.append((i, home, away, lh, la))
    grids = simulate.fixture_grids(lambdas, dixon_coles=True, rho=rho)
    grids = simulate.pin_results(grids, results)
    agg = Aggregate(list(teams))
    rng = random.Random(SEED)
    for _ in range(SIMS):
        table, _res = simulate.simulate_season(grids, list(teams), rng)
        agg.add_season(table)
    return agg, model


def remaining_fixtures(team, fixtures, model, rho, results):
    played = {(r["md"], r["home"], r["away"]) for r in (results or [])}
    rows = []
    for i, md in enumerate(fixtures, start=1):
        for home, away in md:
            if team not in (home, away) or (i, home, away) in played:
                continue
            lh, la = model.lambdas(home, away)
            grid = models.score_grid(lh, la, True, rho)
            ph, pd, pa = models.outcome_probs(grid)
            is_home = home == team
            rows.append({
                "md": i, "opp": away if is_home else home, "home": is_home,
                "w": ph if is_home else pa, "d": pd, "l": pa if is_home else ph,
            })
    return rows


def bar_svg(pos_pct, color):
    """A 1–20 finishing-position histogram, same idiom as the app."""
    w, cw = 640, 640 / 20
    maxp = max(pos_pct) or 1
    cells = []
    for i, v in enumerate(pos_pct):
        h = 96 * v / maxp
        cells.append(
            f'<rect x="{i * cw:.1f}" y="{100 - h:.1f}" width="{cw - 2:.1f}" height="{h:.1f}" '
            f'rx="2" fill="{color}" fill-opacity="{0.3 + 0.7 * v / maxp:.2f}">'
            f'<title>Position {i + 1}: {v:.1f}%</title></rect>'
            f'<text x="{i * cw + cw / 2:.1f}" y="116" text-anchor="middle" class="axis">{i + 1}</text>'
        )
    return (
        f'<svg viewBox="0 0 {w} 122" role="img" aria-label="Finishing-position distribution" '
        f'style="width:100%;height:auto">{"".join(cells)}</svg>'
    )


def e(s):
    return html.escape(str(s), quote=True)


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}">
<meta name="robots" content="index,follow">
<meta property="og:type" content="website">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{og_desc}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{site}/og-default.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{og_title}">
<meta name="twitter:description" content="{og_desc}">
<meta name="twitter:image" content="{site}/og-default.png">
<meta name="theme-color" content="#2a78d6">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='7' fill='%232a78d6'/%3E%3Ctext x='8' y='11.5' font-size='9' text-anchor='middle' fill='white' font-family='sans-serif' font-weight='bold'%3EPL%3C/text%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700;12..96,800&family=Public+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --surface:#fff; --surface-2:#f4f4f2; --text-1:#1a1a19; --text-2:#55544e; --text-3:#8a887f;
    --border:#e3e2dd; --series-1:#2a78d6; --series-2:#1baf7a; --accent:#2a78d6; --danger:#e34948;
    --grad:linear-gradient(118deg,#2456b8 0%,#2a78d6 48%,#6c56c9 100%); --grad-glow:0 6px 24px rgba(42,120,214,.25);
    --font-display:'Bricolage Grotesque',system-ui,sans-serif; --font-body:'Public Sans',system-ui,sans-serif;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --surface:#1a1a19; --surface-2:#242422; --text-1:#fff; --text-2:#c3c2b7; --text-3:#8a887f;
      --border:#3a3935; --series-1:#3987e5; --series-2:#199e70; --accent:#3987e5; --danger:#e66767;
      --grad:linear-gradient(118deg,#2f6fd8 0%,#3f8ce8 48%,#8a74e8 100%); --grad-glow:0 6px 26px rgba(63,140,232,.22);
    }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--surface); color:var(--text-1); font:15px/1.55 var(--font-body); }}
  h1,h2,.v {{ font-family:var(--font-display); letter-spacing:-.02em; }}
  td,.v {{ font-variant-numeric:tabular-nums; }}
  .wrap {{ max-width:960px; margin:0 auto; padding:24px 20px 64px; }}
  a {{ color:var(--accent); }}
  .crumbs {{ font-size:13px; color:var(--text-3); margin-bottom:14px; }}
  .crumbs a {{ text-decoration:none; }}
  .brand {{ display:flex; align-items:center; gap:10px; margin-bottom:6px; }}
  .mark {{ width:34px; height:34px; border-radius:9px; background:var(--grad); color:#fff;
    font:800 15px/34px var(--font-display); text-align:center; box-shadow:var(--grad-glow); flex-shrink:0; }}
  h1 {{ font-size:26px; margin:0; }}
  .sub {{ color:var(--text-2); margin:4px 0 20px; }}
  .dot {{ display:inline-block; width:12px; height:12px; border-radius:3px; margin-right:8px; vertical-align:baseline; }}
  .hero {{ display:flex; gap:14px; flex-wrap:wrap; margin:2px 0 24px; background:var(--grad);
    border-radius:14px; padding:12px; box-shadow:var(--grad-glow); }}
  .hero .stat {{ flex:1 1 130px; background:rgba(255,255,255,.13); border:1px solid rgba(255,255,255,.18);
    border-radius:10px; padding:12px 14px; min-width:0; }}
  .hero .k {{ font-size:11px; color:rgba(255,255,255,.78); letter-spacing:.07em; text-transform:uppercase; font-weight:700; }}
  .hero .v {{ font-size:24px; font-weight:800; color:#fff; line-height:1.2; }}
  .hero .s {{ font-size:12px; color:rgba(255,255,255,.75); }}
  h2 {{ font-size:18px; margin:30px 0 10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:14px; }}
  th,td {{ text-align:right; padding:6px 9px; border-bottom:1px solid var(--border); font-variant-numeric:tabular-nums; }}
  th {{ color:var(--text-2); font-weight:600; font-size:12px; }}
  th.t,td.t {{ text-align:left; }}
  .scroll {{ overflow-x:auto; }}
  .axis {{ font-size:11px; fill:var(--text-3); }}
  .note {{ color:var(--text-3); font-size:13px; margin-top:8px; }}
  .bar {{ background-size:var(--w) 100%; background-repeat:no-repeat; }}
  footer {{ margin-top:44px; padding-top:18px; border-top:1px solid var(--border); color:var(--text-3); font-size:13px; }}
</style>
<script type="application/ld+json">
{jsonld}
</script>
</head>
<body>
<div class="wrap">
  <nav class="crumbs"><a href="{site}/">PL Simulator</a> › {team}</nav>
  <div class="brand"><span class="mark">PL</span><h1><span class="dot" style="background:{color}"></span>{team}</h1></div>
  <p class="sub">2026/27 Premier League forecast — {sims:,} simulated seasons of the real fixture list, recalibrated weekly.{recal}</p>

  <div class="hero">
    <div class="stat"><div class="k">Title</div><div class="v">{title:.1f}%</div></div>
    <div class="stat"><div class="k">Top 4</div><div class="v">{top4:.1f}%</div></div>
    <div class="stat"><div class="k">European</div><div class="v">{europe:.1f}%</div><div class="s">top-7 finish</div></div>
    <div class="stat"><div class="k">Relegation</div><div class="v">{rel:.1f}%</div></div>
    <div class="stat"><div class="k">Expected points</div><div class="v">{xpts:.0f}</div><div class="s">likely finish {mlpos}</div></div>
  </div>

  <h2>Finishing-position distribution</h2>
  {dist}
  <p class="note">How often {team} finishes in each position across {sims:,} simulated seasons. Darker = more likely.</p>

  <h2>Remaining fixtures — win / draw / loss</h2>
  <div class="scroll"><table>
    <thead><tr><th class="t">Matchday</th><th class="t">Fixture</th><th>Win</th><th>Draw</th><th>Loss</th></tr></thead>
    <tbody>{fixtures}</tbody>
  </table></div>
  <p class="note">Per-match probabilities from the same Poisson + Dixon-Coles model behind the simulator. Home advantage and opponent strength are both priced in.</p>

  <footer>
    <a href="{site}/">← Run the full simulator</a> · <a href="{site}/">title &amp; relegation odds for all 20 clubs</a>
  </footer>
</div>
</body>
</html>
"""


def build():
    bundle = load_bundle()
    teams = bundle["teams"]
    fixtures = bundle.get("fixtures")
    if not fixtures:
        sys.exit("model.json has no fixtures; cannot build club pages")
    rho = (bundle.get("constants") or {}).get("DC_RHO", -0.0855)
    results = bundle.get("results") or []
    season = bundle.get("season_state") or {}
    recal = ""
    if season.get("updated"):
        recal = f" Last recalibrated {e(season['updated'])}."
    colors = club_colors()

    print(f"Running {SIMS:,} seasons for position distributions ...", flush=True)
    agg, model = run_montecarlo(teams, fixtures, rho, results)
    n = agg.n

    out_root = os.path.join(ROOT, "clubs")
    os.makedirs(out_root, exist_ok=True)
    written = []
    for team in teams:
        slug = slugify(team)
        pos_pct = [100 * c / n for c in agg.pos_counts[team]]
        title = 100 * agg.prob_position_range(team, 1, 1)
        top4 = 100 * agg.prob_position_range(team, 1, 4)
        europe = 100 * agg.prob_position_range(team, 1, 7)
        rel = 100 * agg.prob_position_range(team, 18, 20)
        xpts = agg.points_sum[team] / n
        mlpos = pos_pct.index(max(pos_pct)) + 1
        color = colors.get(team, "#2a78d6")

        rows = remaining_fixtures(team, fixtures, model, rho, results)
        frows = "".join(
            f'<tr><td class="t">MD{r["md"]}</td>'
            f'<td class="t">{"vs " if r["home"] else "at "}{e(r["opp"])}</td>'
            f'<td>{r["w"] * 100:.0f}%</td><td>{r["d"] * 100:.0f}%</td><td>{r["l"] * 100:.0f}%</td></tr>'
            for r in rows
        ) or '<tr><td colspan="5" class="t">Season complete.</td></tr>'

        canonical = f"{SITE}/clubs/{slug}/"
        title_tag = f"{team} 2026/27 odds — Premier League title & relegation forecast | PL Simulator"
        desc = (
            f"{team}'s 2026/27 Premier League chances from {n:,} Monte Carlo seasons: "
            f"{title:.0f}% title, {top4:.0f}% top four, {rel:.0f}% relegation, plus every "
            f"remaining fixture's win/draw/loss odds."
        )
        og_desc = (
            f"{title:.0f}% title · {top4:.0f}% top four · {rel:.0f}% relegation, from {n:,} "
            f"simulated 2026/27 seasons — with per-fixture win/draw/loss odds."
        )
        jsonld = json.dumps({
            "@context": "https://schema.org",
            "@type": "SportsTeam",
            "name": team,
            "sport": "Association football",
            "url": canonical,
            "memberOf": {"@type": "SportsOrganization", "name": "Premier League"},
            "subjectOf": {
                "@type": "WebPage", "url": canonical,
                "description": desc,
            },
        }, indent=1)

        page = PAGE.format(
            page_title=e(title_tag), desc=e(desc), canonical=canonical, site=SITE,
            og_title=e(f"{team} — 2026/27 Premier League odds"), og_desc=e(og_desc),
            jsonld=jsonld, team=e(team), color=e(color), sims=n, recal=recal,
            title=title, top4=top4, europe=europe, rel=rel, xpts=xpts, mlpos=mlpos,
            dist=bar_svg(pos_pct, color), fixtures=frows,
        )
        club_dir = os.path.join(out_root, slug)
        os.makedirs(club_dir, exist_ok=True)
        with open(os.path.join(club_dir, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(page)
        written.append((slug, team, title, rel))

    print(f"Wrote {len(written)} club pages under clubs/:")
    for slug, team, title, rel in written:
        print(f"  /clubs/{slug}/  — {team}: title {title:.1f}%, rel {rel:.1f}%")
    return [s for s, *_ in written]


if __name__ == "__main__":
    build()
