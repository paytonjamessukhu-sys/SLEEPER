# Warchest

A KTC / Dynasty Daddy–style dynasty HQ built on the
[Sleeper fantasy sports API](https://docs.sleeper.com), defaulting to the
username **PaySuk34**. Two things live here:

1. **`index.html` — Warchest**, a single-file web app (no server, no build step)
2. **`sleeper_client.py`**, a zero-dependency Python client + CLI (stdlib only, Python 3.10+)

**Live:** https://paytonjamessukhu-sys.github.io/sleeper/

## Warchest (the site)

Visit the live link above, or run it locally — everything loads in your browser,
no server needed beyond a static file host:

```bash
python3 -m http.server              # from the repo root, then visit:
# http://localhost:8000/    (double-clicking index.html usually works too)
```

- **Power Rankings** — every roster valued and stacked by position group (QB/RB/WR/TE),
  with starter-lineup value, value-weighted age, and your team tagged
- **Rosters** — any team's players with market value bars, position ranks, and 30-day trends
- **Trade Calculator** — search any players *and draft picks*, two sides, verdict bar
- **Standings** and **Market** (league-wide hottest adds/drops in the last 24h)

Values come from the free [FantasyCalc](https://www.fantasycalc.com) API
(market-based, KTC-style 0–10k scale), auto-matched to your league's format —
Superflex vs 1QB, PPR, and team count are detected from league settings, with a
Dynasty/Redraft toggle. If FantasyCalc is unreachable, the site falls back to
estimates derived from Sleeper's own player ranks and says so on a badge.
Nothing but `api.sleeper.app`, `api.fantasycalc.com`, and `sleepercdn.com`
(avatars) is ever contacted; the page itself is fully self-contained. It also
works for any username — share it with leaguemates via `?user=TheirName`.

## Offline preview

`build_demo.py` bakes a sample 10-team league into a copy of `index.html` and
sets `window.WARCHEST_DEMO`, which the app reads instead of calling the
network — the same rendering code, just a different data source. That's what
makes it possible to preview Warchest somewhere sandboxed (a published Claude
artifact, a phone with no server running):

```bash
python3 build_demo.py                 # writes demo.html — full document
python3 build_demo.py --fragment -o x.html   # <style> + <body> only, for hosts
                                              # that supply their own document
```

The generated page carries a visible "sample data" banner — every name is a
real NFL player, but the league, rosters, and values are invented and must
never be used for actual trades.

## The Python CLI

### "Can it sign into my account?"

No — and nothing can. Sleeper's public API is **read-only and unauthenticated by
design**: there is no login endpoint, no API key, and no OAuth. Your username is
the only thing it ever needs, which also means:

- **Never enter your Sleeper password** into any third-party tool or script.
- This tool can *read* everything (leagues, rosters, matchups, drafts,
  transactions) but can *change* nothing — no lineup edits, no waiver claims.
  Sleeper simply doesn't expose write access.

### Quickstart

```bash
python3 sleeper_client.py profile            # who is PaySuk34
python3 sleeper_client.py leagues            # leagues this season
python3 sleeper_client.py standings          # standings (first league)
python3 sleeper_client.py roster             # your starters + bench
python3 sleeper_client.py matchup            # this week's head-to-head
python3 sleeper_client.py trending --type add  # waiver-wire heat check
```

Useful flags on every command:

| Flag | Meaning |
|---|---|
| `--user NAME` | Any Sleeper username (default `PaySuk34`, or `$SLEEPER_USERNAME`) |
| `--season 2025` | A past season (default: current, from `/state/nfl`) |
| `--league <id\|N>` | League id, or 1-based index from the `leagues` list |
| `--raw` | Dump the raw API JSON — handy for building on top |

### Using it as a library

```python
from sleeper_client import Sleeper

s = Sleeper()
me = s.get_user("PaySuk34")
leagues = s.get_leagues(me["user_id"], "2026")
rosters = s.get_rosters(leagues[0]["league_id"])
```

`Sleeper` wraps every public endpoint: users, state, leagues, rosters, league
users, matchups, playoff brackets, transactions, traded picks, drafts + picks,
the full player database, and trending adds/drops. Avatar images:
`Sleeper.avatar_url(user["avatar"])`.

### Good-citizen notes (from Sleeper's docs)

- Stay **under 1,000 API calls/minute** or risk an IP block. The CLI's request
  volume is nowhere near this.
- The full player database (`/players/nfl`, ~5 MB) should be fetched **at most
  once a day** — the client caches it in `.cache/` (gitignored) for 24h.
