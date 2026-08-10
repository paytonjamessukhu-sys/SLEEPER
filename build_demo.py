#!/usr/bin/env python3
"""
Build a self-contained, offline preview of Warchest.

`index.html` is live-API-driven, which is exactly what a sandboxed host (a
published Claude artifact, an offline demo) will not allow. This script bakes a
sample league into a copy of the page and sets `window.WARCHEST_DEMO`, which
index.html detects and uses instead of the network. Same rendering code runs
either way — only the transport changes.

The player names are real NFL players; **every value, roster, league, and
matchup here is invented sample data**, and the page says so in a banner that
cannot be dismissed. Nothing in this file should ever be used to make an actual
fantasy decision.

Usage:
    python3 build_demo.py [-o out.html]

Stdlib only, like everything else in this repo.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEASON = "2026"
TEAM_COUNT = 10
ROSTER_SIZE = 13
LEAGUE_ID = "demo-sf-dynasty"

# --- player pool: (sleeper_id, name, pos, nfl_team, age, sample_value) --------
# Values are illustrative only — spaced to look like a real dynasty superflex
# market so the charts and the trade calculator have realistic shape.
POOL: list[tuple[str, str, str, str, int, int]] = [
    ("7564", "Ja'Marr Chase", "WR", "CIN", 26, 9880),
    ("9509", "Bijan Robinson", "RB", "ATL", 24, 9540),
    ("6794", "Justin Jefferson", "WR", "MIN", 27, 9120),
    ("8155", "Jahmyr Gibbs", "RB", "DET", 24, 8760),
    ("9756", "Malik Nabers", "WR", "NYG", 23, 8480),
    ("8112", "Brock Bowers", "TE", "LV", 23, 8300),
    ("5850", "Josh Allen", "QB", "BUF", 30, 8090),
    ("9502", "Jayden Daniels", "QB", "WAS", 25, 7860),
    ("9997", "Marvin Harrison Jr.", "WR", "ARI", 24, 7420),
    ("6786", "Jalen Hurts", "QB", "PHI", 28, 7180),
    ("4046", "Patrick Mahomes", "QB", "KC", 31, 7040),
    ("9226", "De'Von Achane", "RB", "MIA", 25, 6890),
    ("8146", "Puka Nacua", "WR", "LAR", 25, 6740),
    ("6803", "CeeDee Lamb", "WR", "DAL", 27, 6610),
    ("9493", "Caleb Williams", "QB", "CHI", 25, 6380),
    ("7594", "Amon-Ra St. Brown", "WR", "DET", 27, 6120),
    ("9508", "Drake Maye", "QB", "NE", 24, 5980),
    ("5859", "A.J. Brown", "WR", "PHI", 29, 5730),
    ("8130", "Jaxon Smith-Njigba", "WR", "SEA", 24, 5610),
    ("6790", "Justin Herbert", "QB", "LAC", 28, 5380),
    ("9221", "Sam LaPorta", "TE", "DET", 25, 5140),
    ("4034", "Christian McCaffrey", "RB", "SF", 30, 4980),
    ("9484", "Rome Odunze", "WR", "CHI", 24, 4860),
    ("8138", "Zay Flowers", "WR", "BAL", 25, 4700),
    ("6904", "Trevor Lawrence", "QB", "JAX", 26, 4520),
    ("4866", "Saquon Barkley", "RB", "PHI", 29, 4380),
    ("9229", "Brian Robinson Jr.", "RB", "WAS", 27, 4160),
    ("6944", "Kyle Pitts", "TE", "ATL", 25, 3980),
    ("7526", "Trey McBride", "TE", "ARI", 26, 3840),
    ("6813", "Jordan Love", "QB", "GB", 27, 3720),
    ("8144", "Tank Bigsby", "RB", "JAX", 25, 3560),
    ("4881", "Lamar Jackson", "QB", "BAL", 29, 3410),
    ("7591", "Kenneth Walker III", "RB", "SEA", 26, 3280),
    ("5872", "DK Metcalf", "WR", "PIT", 28, 3120),
    ("8134", "Jordan Addison", "WR", "MIN", 24, 2980),
    ("4217", "George Kittle", "TE", "SF", 32, 2840),
    ("6151", "Tee Higgins", "WR", "CIN", 27, 2710),
    ("9503", "Bo Nix", "QB", "DEN", 26, 2580),
    ("7543", "Garrett Wilson", "WR", "NYJ", 26, 2460),
    ("5892", "Josh Jacobs", "RB", "GB", 28, 2340),
    ("8121", "Bijan Wilson", "WR", "TB", 24, 2210),
    ("6997", "Chris Olave", "WR", "NO", 26, 2090),
    ("4098", "Alvin Kamara", "RB", "NO", 31, 1980),
    ("9518", "Xavier Worthy", "WR", "KC", 24, 1870),
    ("1466", "Travis Kelce", "TE", "KC", 37, 1760),
    ("7611", "Breece Hall", "RB", "NYJ", 26, 1650),
    ("6820", "Michael Pittman Jr.", "WR", "IND", 28, 1540),
    ("8110", "Dalton Kincaid", "TE", "BUF", 26, 1450),
    ("5045", "Baker Mayfield", "QB", "TB", 31, 1360),
    ("7553", "Christian Watson", "WR", "GB", 27, 1270),
    ("9227", "Jaylen Wright", "RB", "MIA", 24, 1190),
    ("5022", "Dallas Goedert", "TE", "PHI", 31, 1110),
    ("6943", "Rashod Bateman", "WR", "BAL", 27, 1030),
    ("4199", "Aaron Jones", "RB", "MIN", 31, 960),
    ("7561", "Romeo Doubs", "WR", "GB", 27, 890),
    ("8117", "Roschon Johnson", "RB", "CHI", 26, 820),
    ("6989", "Wan'Dale Robinson", "WR", "NYG", 26, 760),
    ("4993", "Gus Edwards", "RB", "LAC", 31, 700),
    ("7605", "Jake Ferguson", "TE", "DAL", 27, 650),
    ("5967", "Rondale Moore", "WR", "ATL", 26, 590),
    ("4035", "Austin Ekeler", "RB", "WAS", 31, 540),
    ("8103", "Tyjae Spears", "RB", "TEN", 25, 490),
    ("6126", "Brandon Aiyuk", "WR", "SF", 28, 450),
    ("7002", "Alec Pierce", "WR", "IND", 26, 410),
    ("5000", "Tyler Higbee", "TE", "LAR", 33, 370),
    ("9231", "Ray Davis", "RB", "BUF", 26, 330),
    ("6111", "Jalen Tolbert", "WR", "DAL", 27, 300),
    ("4141", "Mike Gesicki", "TE", "CIN", 30, 270),
    ("7809", "Isaiah Likely", "TE", "BAL", 26, 240),
    ("5163", "Darnell Mooney", "WR", "ATL", 28, 210),
    # depth — keeps every roster deeper than its starting lineup, so "team value"
    # and "starter value" are meaningfully different numbers
    ("3001", "Kyler Murray", "QB", "ARI", 29, 3060),
    ("3002", "Dak Prescott", "QB", "DAL", 33, 2650),
    ("3003", "Michael Penix Jr.", "QB", "ATL", 26, 2520),
    ("3004", "J.J. McCarthy", "QB", "MIN", 24, 2430),
    ("3005", "Anthony Richardson", "QB", "IND", 25, 1930),
    ("3006", "Tua Tagovailoa", "QB", "MIA", 28, 1690),
    ("3007", "Matthew Stafford", "QB", "LAR", 38, 880),
    ("3008", "Geno Smith", "QB", "LV", 36, 620),
    ("3009", "Brian Thomas Jr.", "WR", "JAX", 24, 5290),
    ("3010", "Ladd McConkey", "WR", "LAC", 25, 4440),
    ("3011", "Keon Coleman", "WR", "BUF", 24, 3350),
    ("3012", "Jayden Reed", "WR", "GB", 26, 2890),
    ("3013", "Khalil Shakir", "WR", "BUF", 27, 2260),
    ("3014", "George Pickens", "WR", "DAL", 26, 2170),
    ("3015", "Calvin Ridley", "WR", "TEN", 32, 1420),
    ("3016", "Courtland Sutton", "WR", "DEN", 31, 1330),
    ("3017", "Cooper Kupp", "WR", "SEA", 33, 940),
    ("3018", "Jakobi Meyers", "WR", "LV", 30, 830),
    ("3019", "Jerry Jeudy", "WR", "CLE", 27, 720),
    ("3020", "Chase Brown", "RB", "CIN", 26, 3620),
    ("3021", "Travis Etienne Jr.", "RB", "JAX", 27, 2760),
    ("3022", "Zach Charbonnet", "RB", "SEA", 25, 2020),
    ("3023", "Isiah Pacheco", "RB", "KC", 27, 1610),
    ("3024", "Rachaad White", "RB", "TB", 27, 1240),
    ("3025", "Jaylen Warren", "RB", "PIT", 27, 1150),
    ("3026", "Javonte Williams", "RB", "DAL", 26, 1000),
    ("3027", "Rhamondre Stevenson", "RB", "NE", 28, 780),
    ("3028", "Najee Harris", "RB", "LAC", 28, 640),
    ("3029", "Kenneth Gainwell", "RB", "PIT", 27, 430),
    ("3030", "Tucker Kraft", "TE", "GB", 26, 2900),
    ("3031", "Colston Loveland", "TE", "CHI", 23, 2400),
    ("3032", "David Njoku", "TE", "CLE", 30, 1290),
    ("3033", "Evan Engram", "TE", "DEN", 32, 860),
    ("3034", "Pat Freiermuth", "TE", "PIT", 28, 560),
    ("3035", "Cole Kmet", "TE", "CHI", 27, 380),
    ("3036", "Hunter Henry", "TE", "NE", 32, 260),
]
# Draft order and every rank derive from value, so the literals above can be
# written in any order.
POOL.sort(key=lambda p: -p[5])

DEFENSES = ["PHI", "BAL", "DEN", "PIT", "SF", "BUF", "MIN", "HOU", "GB", "DET"]

TEAM_NAMES = [
    "Bijan Mustard", "The Pitt Stop", "Nabers Watch", "Chase Priority",
    "Purple Reign", "Bowers of London", "Herbert Hoovers", "Mahomie Depot",
    "Waiver Wire Warriors", "Championship or Bust",
]
OWNER_NAMES = [
    "PaySuk34", "dyno_dan", "wrcorps", "punt_te", "tank_commander", "jetsfan92",
    "big_board_bob", "zero_rb_zach", "sf_supremacy", "the_commish",
]
USER_ID = "demo-user-paysuk34"


def build_dataset() -> dict:
    """Snake-draft the pool into 12 rosters so every team is plausibly built."""
    order = list(range(TEAM_COUNT))
    picks: list[list[str]] = [[] for _ in range(TEAM_COUNT)]
    pool = [p[0] for p in POOL]
    i = 0
    rnd = 0
    while i < len(pool) and rnd < ROSTER_SIZE - 1:
        seq = order if rnd % 2 == 0 else order[::-1]
        for team in seq:
            if i >= len(pool):
                break
            picks[team].append(pool[i])
            i += 1
        rnd += 1
    for team in range(TEAM_COUNT):          # one defense each
        picks[team].append(DEFENSES[team])

    players = {}
    for pid, name, pos, nfl, age, _v in POOL:
        players[pid] = {"full_name": name, "position": pos, "team": nfl,
                        "age": age, "active": True, "search_rank": len(players) + 1}
    for d in DEFENSES:
        players[d] = {"full_name": f"{d} Defense", "position": "DEF", "team": d,
                      "active": True, "search_rank": 400}

    values = [
        {"player": {"sleeperId": pid, "name": name, "position": pos},
         "value": v, "overallRank": rank + 1,
         "positionRank": sum(1 for q in POOL[:rank + 1] if q[2] == pos),
         # deterministic pseudo-trend so the 30-day column has movement
         "trend30Day": ((rank * 137) % 900) - 380}
        for rank, (pid, name, pos, _t, _a, v) in enumerate(POOL)
    ]
    values += [
        {"player": {"sleeperId": None, "name": f"{yr} Round {rd}", "position": "PICK"},
         "value": v, "overallRank": None, "positionRank": None, "trend30Day": 0}
        for yr, rd, v in [("2027", 1, 5400), ("2027", 2, 2300), ("2027", 3, 900),
                          ("2028", 1, 4600), ("2028", 2, 1900), ("2028", 3, 750)]
    ]

    roster_positions = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX",
                        "SUPER_FLEX", "DEF", "BN", "BN", "BN", "BN", "BN"]
    rosters, lusers = [], []
    # A fixed W-L ladder: the top-value team is not the top record, which is the
    # tension the whole app exists to surface.
    records = [(8, 4), (10, 2), (7, 5), (9, 3), (6, 6),
               (5, 7), (7, 5), (4, 8), (3, 9), (2, 10)]
    for t in range(TEAM_COUNT):
        ids = picks[t]
        starters = ids[:9]
        wins, losses = records[t]
        uid = USER_ID if t == 0 else f"demo-user-{t}"
        rosters.append({
            "roster_id": t + 1, "owner_id": uid, "co_owners": None,
            "players": ids, "starters": starters, "reserve": None, "taxi": None,
            "settings": {"wins": wins, "losses": losses, "ties": 0,
                         "fpts": 1180 + t * 7 + wins * 24, "fpts_decimal": (t * 31) % 100,
                         "fpts_against": 1240 - t * 5, "fpts_against_decimal": (t * 17) % 100},
        })
        lusers.append({"user_id": uid, "display_name": OWNER_NAMES[t],
                       "metadata": {"team_name": TEAM_NAMES[t]}})

    league = {
        "league_id": LEAGUE_ID, "name": f"Sample Dynasty ({TEAM_COUNT}-team SF)",
        "total_rosters": TEAM_COUNT, "status": "in_season", "season": SEASON,
        "scoring_settings": {"rec": 1, "bonus_rec_te": 0.5},
        "settings": {"playoff_teams": 6}, "roster_positions": roster_positions,
    }
    trending = lambda ids, base: [                                    # noqa: E731
        {"player_id": pid, "count": base - i * (base // 14)} for i, pid in enumerate(ids)]

    return {
        "season": SEASON,
        "user": {"user_id": USER_ID, "username": "PaySuk34",
                 "display_name": "PaySuk34", "avatar": None},
        "state": {"week": 13, "display_week": 13, "season": SEASON,
                  "league_season": SEASON, "season_type": "regular"},
        "leagues": [league],
        "_sanity": {"players_per_team": len(rosters[0]["players"]),
                    "starting_slots": len(starters)},
        "leagueData": {LEAGUE_ID: {"rosters": rosters, "users": lusers}},
        "players": players,
        "values": values,
        "trendingAdd": trending([p[0] for p in POOL[42:54]], 58000),
        "trendingDrop": trending([p[0] for p in POOL[54:66]], 31000),
    }


BANNER = """<div class="demo-note">
  <b>Preview with sample data.</b> Real player names, but the league, rosters and
  every value below are invented to show the interface &mdash; do not use them for
  actual trades. The live version reads your real Sleeper leagues and pulls
  market values from FantasyCalc.
</div>"""

BANNER_CSS = """
.demo-note { border: 1px solid var(--s2); border-radius: 10px; padding: 10px 14px;
  margin: 14px 0 0; font-size: 13px; color: var(--ink-2); line-height: 1.5;
  background: color-mix(in srgb, var(--s2) 8%, var(--surface)); }
.demo-note b { color: var(--ink-1); }
"""


# Some hosts (a published artifact) supply their own <html>/<head>/<body> and
# reject a nested document, so --fragment emits just the stylesheet plus the body.
VIEWPORT_SHIM = """<script>
/* Hosts that wrap this fragment own the <head>; without a viewport meta a phone
   lays the page out at ~980px and every mobile breakpoint misses. */
if (!document.querySelector('meta[name="viewport"]')) {
  var m = document.createElement("meta");
  m.name = "viewport"; m.content = "width=device-width, initial-scale=1";
  document.head.appendChild(m);
}
</script>"""


def to_fragment(html: str) -> str:
    style = html[html.index("<style>"): html.index("</style>") + len("</style>")]
    body = html[html.index("<body>") + len("<body>"): html.rindex("</body>")]
    return f"{style}\n{VIEWPORT_SHIM}\n{body}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--out", default=str(HERE / "demo.html"))
    ap.add_argument("--fragment", action="store_true",
                    help="emit <style> + body only, for hosts that supply the document")
    args = ap.parse_args()

    html = (HERE / "index.html").read_text()
    data = json.dumps(build_dataset(), separators=(",", ":"))

    html = html.replace("</style>", BANNER_CSS + "</style>", 1)
    html = html.replace('<title>Warchest — Dynasty HQ for Sleeper</title>',
                        '<title>Warchest — Dynasty HQ for Sleeper (preview)</title>', 1)
    # The dataset must exist before the app script reads window.WARCHEST_DEMO.
    html = html.replace('<div id="banner"></div>',
                        BANNER + '\n  <div id="banner"></div>', 1)
    html = html.replace('<script>\n"use strict";',
                        f'<script>window.WARCHEST_DEMO={data};</script>\n<script>\n"use strict";', 1)

    sanity = json.loads(data)["_sanity"]
    if sanity["players_per_team"] <= sanity["starting_slots"]:
        raise SystemExit(
            f"demo rosters ({sanity['players_per_team']} players) do not exceed the "
            f"{sanity['starting_slots']} starting slots, so every player would start "
            "and 'team value' would equal 'starter value' — deepen POOL or cut slots")

    if args.fragment:
        html = to_fragment(html)

    out = Path(args.out)
    out.write_text(html)
    kb = len(html.encode()) / 1024
    print(f"wrote {out} ({kb:.0f} KB) — {sanity['players_per_team']} players/team, "
          f"{sanity['starting_slots']} starting slots")


if __name__ == "__main__":
    main()
