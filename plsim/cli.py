"""Command-line interface for the Premier League 2026/27 simulator."""

import argparse
import random
import sys
import time

from . import models, simulate
from .calibrate import DEFAULT_SEASONS
from .fixtures import get_fixtures, matchday_date
from .table import LeagueTable
from .teams import load_ratings, load_teams


def _build_model(args, teams):
    return models.make_model(args.model, teams)


def _md_date(md, md_dates):
    return md_dates.get(md) or matchday_date(md)


def _print_matchday_results(md, results, md_dates, table=None):
    print(f"\nMatchday {md}  ({_md_date(md, md_dates):%a %d %b %Y})")
    print("-" * 44)
    for _md, home, away, hg, ag in results:
        print(f"  {home:<20} {hg} - {ag} {away}")
    if table is not None:
        print()
        print(table.render(title=f"Table after matchday {md}"))


# ---------------------------------------------------------------- commands


def cmd_teams(args):
    teams = load_teams(args.teams)
    print(f"{'Team':<20} {'Attack':>7} {'Defence':>8} {'Elo':>6}")
    print("-" * 44)
    for name in sorted(teams, key=lambda t: -teams[t]["elo"]):
        r = teams[name]
        print(f"{name:<20} {r['attack']:>7.2f} {r['defence']:>8.2f} {r['elo']:>6.0f}")


def cmd_fixtures(args):
    teams = load_teams(args.teams)
    matchdays, md_dates, src_label = get_fixtures(teams)
    print(f"[{src_label} 2026/27 fixture list]")
    selected = [args.matchday] if args.matchday else range(1, len(matchdays) + 1)
    for md in selected:
        print(f"\nMatchday {md}  ({_md_date(md, md_dates):%a %d %b %Y})")
        print("-" * 44)
        for home, away in matchdays[md - 1]:
            print(f"  {home:<20} v  {away}")


def cmd_matchday(args):
    """Predictions + one simulated set of results for a single matchday."""
    teams, meta = load_ratings(args.teams)
    rho = meta.get("rho", models.DC_RHO)
    model = _build_model(args, teams)
    matchdays, md_dates, _src = get_fixtures(teams)
    md = args.matchday
    if not 1 <= md <= len(matchdays):
        sys.exit(f"matchday must be 1-{len(matchdays)}")
    rng = random.Random(args.seed)

    print(f"Matchday {md}  ({_md_date(md, md_dates):%a %d %b %Y})  —  model: {model.name}"
          + ("+dixon-coles" if args.dixon_coles else ""))
    header = (f"{'Fixture':<42} {'Home%':>6} {'Draw%':>6} {'Away%':>6}  "
              f"{'xG':>9}  {'Likely':>6}  {'Simulated':>9}")
    print(header)
    print("-" * len(header))
    for home, away in matchdays[md - 1]:
        lam_h, lam_a = model.lambdas(home, away)
        grid = models.score_grid(lam_h, lam_a, args.dixon_coles, rho)
        p_h, p_d, p_a = models.outcome_probs(grid)
        ml_h, ml_a = models.most_likely_score(grid)
        sim_h, sim_a = models.sample_score(models.cumulative(grid), rng)
        fixture = f"{home} v {away}"
        print(f"{fixture:<42} {p_h * 100:>5.1f}% {p_d * 100:>5.1f}% {p_a * 100:>5.1f}%  "
              f"{lam_h:>4.2f}-{lam_a:4.2f}  {ml_h:>3}-{ml_a:<3}  {sim_h:>4}-{sim_a:<4}")


def cmd_season(args):
    """Play out one full season matchday by matchday."""
    teams, meta = load_ratings(args.teams)
    model = _build_model(args, teams)
    matchdays, md_dates, _src = get_fixtures(teams)
    rng = random.Random(args.seed)
    grids = simulate.fixture_grids(
        simulate.fixture_lambdas(model, matchdays), args.dixon_coles,
        meta.get("rho")
    )

    table, results = simulate.simulate_season(grids, list(teams), rng)

    if not args.quiet:
        running = LeagueTable(list(teams))
        for md in range(1, len(matchdays) + 1):
            md_results = [r for r in results if r[0] == md]
            for _md, home, away, hg, ag in md_results:
                running.record(home, away, hg, ag)
            show_table = args.tables and (md % args.tables == 0 or md == len(matchdays))
            _print_matchday_results(md, md_results, md_dates, running if show_table else None)
        print()

    print(table.render(title=f"Final 2026/27 table  (model: {model.name}, seed: {args.seed})"))
    standings = table.standings()
    print(f"\nChampions: {standings[0]}")
    print(f"Champions League: {', '.join(standings[:4])}")
    print(f"Relegated: {', '.join(standings[-3:])}")


def cmd_montecarlo(args):
    """Monte Carlo over many seasons -> outcome probabilities."""
    teams, meta = load_ratings(args.teams)
    model = _build_model(args, teams)
    matchdays, _md_dates, _src = get_fixtures(teams)
    team_names = list(teams)

    label = model.name + ("+dixon-coles" if args.dixon_coles and not args.noise else "")
    if args.noise:
        label += f"+noise({args.noise:g})"
    print(f"Simulating {args.sims:,} seasons  (model: {label}) ...", flush=True)
    start = time.time()

    def progress(done, total):
        print(f"  workers finished: {done}/{total}", flush=True)

    agg = simulate.monte_carlo(
        model, matchdays, team_names, args.sims,
        seed=args.seed, dixon_coles=args.dixon_coles,
        rho=meta.get("rho"), noise=args.noise, workers=args.workers,
        progress=progress if args.sims >= 20000 else None,
    )
    elapsed = time.time() - start
    print(f"Done: {agg.n:,} seasons in {elapsed:.1f}s "
          f"({agg.n / elapsed:,.0f} seasons/s)\n")

    order = sorted(team_names, key=lambda t: (-agg.prob_champion(t), agg.mean_position(t)))
    header = (f"{'Team':<20} {'Title%':>7} {'Top4%':>7} {'Top6%':>7} {'Rel%':>7} "
              f"{'AvgPos':>7} {'AvgPts':>7} {'±':>5} {'Min':>4} {'Max':>4}")
    print(header)
    print("-" * len(header))
    for t in order:
        print(f"{t:<20} {agg.prob_champion(t) * 100:>6.2f}% "
              f"{agg.prob_top4(t) * 100:>6.2f}% "
              f"{agg.prob_position_range(t, 1, 6) * 100:>6.2f}% "
              f"{agg.prob_relegated(t) * 100:>6.2f}% "
              f"{agg.mean_position(t):>7.2f} {agg.mean_points(t):>7.1f} "
              f"{agg.std_points(t):>5.1f} {agg.points_min[t]:>4} {agg.points_max[t]:>4}")

    if args.positions:
        print(f"\nPosition probabilities (%) — rows are teams, columns finishing position")
        cols = "".join(f"{p:>5}" for p in range(1, 21))
        print(f"{'Team':<20}{cols}")
        print("-" * (20 + 5 * 20))
        for t in order:
            row = "".join(
                f"{100 * c / agg.n:>5.1f}" if c else "    ." for c in agg.pos_counts[t]
            )
            print(f"{t:<20}{row}")


def cmd_calibrate(args):
    """Fit ratings from historical results and write a --teams JSON."""
    from . import calibrate as cal

    print(f"Fitting ratings from seasons: {', '.join(args.seasons)}")
    ratings, info = cal.calibrate(
        seasons=args.seasons, cache_dir=args.cache_dir,
        download=not args.no_download,
    )
    print(f"Fitted {info['matches']} matches "
          f"(baselines: {info['base_home']:.2f} home / {info['base_away']:.2f} away goals, "
          f"rho: {info['rho']:+.3f}, decay half-life: {info['half_life_days']}d)\n")

    defaults = load_teams()
    header = (f"{'Team':<20} {'Attack':>7} {'Defence':>8} {'Home':>6} {'Elo':>6}   "
              f"{'(default':>9} {'att':>5} {'def':>5} {'elo)':>6}")
    print(header)
    print("-" * len(header))
    for name in sorted(ratings, key=lambda t: -ratings[t]["elo"]):
        r, d = ratings[name], defaults[name]
        print(f"{name:<20} {r['attack']:>7.2f} {r['defence']:>8.2f} {r['home']:>6.2f} {r['elo']:>6.0f}   "
              f"{'':>9} {d['attack']:>5.2f} {d['defence']:>5.2f} {d['elo']:>6.0f}")

    cal.write_ratings(ratings, args.out, info)
    print(f"\nWrote {args.out} - use it with:  python3 -m plsim montecarlo --teams {args.out}")


def cmd_backtest(args):
    """Walk-forward accuracy evaluation on a held-out season."""
    from . import backtest as bt

    target = args.target or args.seasons[-1]
    print(f"Backtesting on {target} Premier League "
          f"(training data: {', '.join(args.seasons)}; walk-forward, "
          f"refit before every {'matchday' if args.every == 1 else f'{args.every}th matchday'})")
    start = time.time()

    def progress(done, total, md):
        print(f"  matchday {md} scored ({done}/{total})", flush=True)

    summaries, winner = bt.run(
        seasons=args.seasons, target=args.target, cache_dir=args.cache_dir,
        download=not args.no_download, every=args.every,
        progress=progress if not args.quiet else None,
    )
    print(f"\nScored in {time.time() - start:.0f}s — lower is better on every metric.\n")
    header = (f"{'Variant':<14} {'Matches':>8} {'RPS':>8} {'LogLoss':>9} "
              f"{'Brier':>8} {'CS-Brier':>9}")
    print(header)
    print("-" * len(header))
    for s in summaries:
        print(f"{s['variant']:<14} {s['matches']:>8} {s['rps']:>8.4f} "
              f"{s['logloss']:>9.4f} {s['brier']:>8.4f} {s['cs_brier']:>9.4f}")

    print(f"\nBest model variant by RPS: {winner.name}")
    print("\nClean-sheet calibration for the best variant")
    print(f"{'Predicted':>12} {'Actual':>8} {'N':>6}")
    for lo, (sum_p, hits, count) in enumerate(winner.cs_bins):
        if not count:
            continue
        print(f"{sum_p / count:>11.1%} {hits / count:>7.1%} {count:>6}")


# ---------------------------------------------------------------- parser


def _add_common(p):
    p.add_argument("--teams", metavar="JSON",
                   help="path to a custom team-ratings JSON file")
    p.add_argument("--model", choices=("poisson", "elo"), default="poisson",
                   help="prediction model (default: poisson)")
    p.add_argument("--dixon-coles", action="store_true",
                   help="apply the Dixon-Coles low-score correction")
    p.add_argument("--seed", type=int, default=None,
                   help="random seed for reproducible runs")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="plsim",
        description="Premier League 2026/27 season simulator "
                    "(Poisson / Elo models, Monte Carlo engine).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("teams", help="show the 20 teams and their ratings")
    p.add_argument("--teams", metavar="JSON")
    p.set_defaults(func=cmd_teams)

    p = sub.add_parser("fixtures", help="show the generated fixture list")
    p.add_argument("--teams", metavar="JSON")
    p.add_argument("--matchday", type=int, metavar="N",
                   help="show a single matchday only")
    p.set_defaults(func=cmd_fixtures)

    p = sub.add_parser("matchday",
                       help="predict and simulate one matchday's fixtures")
    p.add_argument("matchday", type=int, metavar="N", help="matchday number (1-38)")
    _add_common(p)
    p.set_defaults(func=cmd_matchday)

    p = sub.add_parser("season", help="simulate one full season, day by day")
    _add_common(p)
    p.add_argument("--quiet", action="store_true",
                   help="print only the final table")
    p.add_argument("--tables", type=int, default=0, metavar="N",
                   help="also print the league table every N matchdays")
    p.set_defaults(func=cmd_season)

    p = sub.add_parser("montecarlo",
                       help="run many seasons and report outcome probabilities")
    _add_common(p)
    p.add_argument("--sims", type=int, default=10000, metavar="N",
                   help="number of seasons to simulate (default: 10000)")
    p.add_argument("--noise", type=float, default=0.0, metavar="SIGMA",
                   help="per-season team-strength noise, e.g. 0.08 "
                        "(disables Dixon-Coles)")
    p.add_argument("--workers", type=int, default=None, metavar="W",
                   help="worker processes (default: auto)")
    p.add_argument("--positions", action="store_true",
                   help="print the full 20x20 finishing-position matrix")
    p.set_defaults(func=cmd_montecarlo)

    p = sub.add_parser("calibrate",
                       help="fit ratings from historical results (openfootball)")
    p.add_argument("--out", default="teams_calibrated.json", metavar="JSON",
                   help="output ratings file (default: teams_calibrated.json)")
    p.add_argument("--seasons", nargs="+", metavar="YYYY-YY",
                   default=list(DEFAULT_SEASONS),
                   help="seasons to fit, oldest first (default: 2023-24 2024-25 2025-26)")
    p.add_argument("--cache-dir", default="data", metavar="DIR",
                   help="where downloaded results are cached (default: data/)")
    p.add_argument("--no-download", action="store_true",
                   help="use cached files only, never hit the network")
    p.set_defaults(func=cmd_calibrate)

    p = sub.add_parser("backtest",
                       help="score model variants on a held-out season")
    p.add_argument("--seasons", nargs="+", metavar="YYYY-YY",
                   default=list(DEFAULT_SEASONS),
                   help="seasons to load, oldest first")
    p.add_argument("--target", metavar="YYYY-YY", default=None,
                   help="season to hold out and predict (default: most recent)")
    p.add_argument("--every", type=int, default=1, metavar="N",
                   help="evaluate every N-th matchday only (quick mode)")
    p.add_argument("--cache-dir", default="data", metavar="DIR")
    p.add_argument("--no-download", action="store_true")
    p.add_argument("--quiet", action="store_true",
                   help="suppress per-matchday progress")
    p.set_defaults(func=cmd_backtest)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if getattr(args, "seed", None) is None and hasattr(args, "seed"):
        args.seed = random.randrange(10**9)
    args.func(args)


if __name__ == "__main__":
    main()
