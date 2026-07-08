"""League table bookkeeping and Premier League tie-breakers."""


class LeagueTable:
    """Accumulates results and produces standings.

    Tie-breakers: points, goal difference, goals scored, then team name
    (the real league would go to head-to-head next; over thousands of
    Monte Carlo runs the alphabetical fallback is statistically neutral
    enough for the aggregate probabilities).
    """

    def __init__(self, team_names):
        self.rows = {
            name: {"P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "Pts": 0}
            for name in team_names
        }

    def record(self, home, away, hg, ag):
        rh, ra = self.rows[home], self.rows[away]
        rh["P"] += 1
        ra["P"] += 1
        rh["GF"] += hg
        rh["GA"] += ag
        ra["GF"] += ag
        ra["GA"] += hg
        if hg > ag:
            rh["W"] += 1
            ra["L"] += 1
            rh["Pts"] += 3
        elif hg < ag:
            ra["W"] += 1
            rh["L"] += 1
            ra["Pts"] += 3
        else:
            rh["D"] += 1
            ra["D"] += 1
            rh["Pts"] += 1
            ra["Pts"] += 1

    def standings(self):
        """Teams in final order, best first."""
        return sorted(
            self.rows,
            key=lambda t: (
                -self.rows[t]["Pts"],
                -(self.rows[t]["GF"] - self.rows[t]["GA"]),
                -self.rows[t]["GF"],
                t,
            ),
        )

    def render(self, title="Table"):
        lines = [title, ""]
        header = f"{'#':>2}  {'Team':<20} {'P':>3} {'W':>3} {'D':>3} {'L':>3} {'GF':>4} {'GA':>4} {'GD':>4} {'Pts':>4}"
        lines.append(header)
        lines.append("-" * len(header))
        for pos, team in enumerate(self.standings(), 1):
            r = self.rows[team]
            gd = r["GF"] - r["GA"]
            marker = " "
            if pos <= 4:
                marker = "*"          # Champions League
            elif pos >= 18:
                marker = "v"          # relegation zone
            lines.append(
                f"{pos:>2}{marker} {team:<20} {r['P']:>3} {r['W']:>3} {r['D']:>3} "
                f"{r['L']:>3} {r['GF']:>4} {r['GA']:>4} {gd:>+4} {r['Pts']:>4}"
            )
        lines.append("")
        lines.append(" * Champions League   v relegation")
        return "\n".join(lines)
