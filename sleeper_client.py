#!/usr/bin/env python3
"""
Sleeper fantasy-football client + CLI, built around https://docs.sleeper.com.

The Sleeper public API is read-only and unauthenticated: there is no login, no
API key, and no OAuth. A username is the only input it ever needs, so this tool
never asks for (and could never use) a password.

Usage:
    python3 sleeper_client.py profile
    python3 sleeper_client.py leagues
    python3 sleeper_client.py standings [--league <id-or-index>]
    python3 sleeper_client.py roster    [--league <id-or-index>]
    python3 sleeper_client.py matchup   [--league <id-or-index>] [--week N]
    python3 sleeper_client.py trending  [--type add|drop]

Every command accepts --user (default: PaySuk34, or $SLEEPER_USERNAME),
--season, --sport, and --raw (dump the API JSON instead of formatted text).

Stdlib only — same rule as the rest of this repo's scripts.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://api.sleeper.app/v1"
CDN_URL = "https://sleepercdn.com"
DEFAULT_USERNAME = os.environ.get("SLEEPER_USERNAME", "PaySuk34")
USER_AGENT = "dc-portfolio-atlas-sleeper-cli/1.0 (+github.com/paytonjamessukhu-sys)"

# The players dump is ~5 MB; Sleeper asks that it be fetched at most once a day,
# so it is cached on disk (.cache/ is gitignored).
CACHE_DIR = Path(__file__).resolve().parent / ".cache"
PLAYERS_TTL_SECONDS = 24 * 60 * 60


class SleeperError(RuntimeError):
    """A request to the Sleeper API failed after retries."""


def _get(path: str, retries: int = 3) -> object:
    """GET {BASE_URL}{path} as JSON. Returns None on 404 (Sleeper's 'not found')."""
    url = BASE_URL + path
    delay = 1.0
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return None
            # 429 = over Sleeper's 1000-calls/minute limit; 5xx = their outage.
            if err.code in (429,) or err.code >= 500:
                if attempt < retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
            raise SleeperError(f"GET {url} -> HTTP {err.code}") from err
        except (urllib.error.URLError, TimeoutError) as err:
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise SleeperError(f"GET {url} failed: {err}") from err
    raise SleeperError(f"GET {url} failed after {retries + 1} attempts")


class Sleeper:
    """Thin wrapper over every public Sleeper endpoint."""

    # -- users ---------------------------------------------------------------
    def get_user(self, username_or_id: str) -> dict | None:
        return _get(f"/user/{username_or_id}")

    # -- app/season state ----------------------------------------------------
    def get_state(self, sport: str = "nfl") -> dict:
        return _get(f"/state/{sport}") or {}

    # -- leagues -------------------------------------------------------------
    def get_leagues(self, user_id: str, season: str, sport: str = "nfl") -> list:
        return _get(f"/user/{user_id}/leagues/{sport}/{season}") or []

    def get_league(self, league_id: str) -> dict | None:
        return _get(f"/league/{league_id}")

    def get_rosters(self, league_id: str) -> list:
        return _get(f"/league/{league_id}/rosters") or []

    def get_league_users(self, league_id: str) -> list:
        return _get(f"/league/{league_id}/users") or []

    def get_matchups(self, league_id: str, week: int) -> list:
        return _get(f"/league/{league_id}/matchups/{week}") or []

    def get_winners_bracket(self, league_id: str) -> list:
        return _get(f"/league/{league_id}/winners_bracket") or []

    def get_losers_bracket(self, league_id: str) -> list:
        return _get(f"/league/{league_id}/losers_bracket") or []

    def get_transactions(self, league_id: str, week: int) -> list:
        return _get(f"/league/{league_id}/transactions/{week}") or []

    def get_traded_picks(self, league_id: str) -> list:
        return _get(f"/league/{league_id}/traded_picks") or []

    # -- drafts --------------------------------------------------------------
    def get_user_drafts(self, user_id: str, season: str, sport: str = "nfl") -> list:
        return _get(f"/user/{user_id}/drafts/{sport}/{season}") or []

    def get_league_drafts(self, league_id: str) -> list:
        return _get(f"/league/{league_id}/drafts") or []

    def get_draft(self, draft_id: str) -> dict | None:
        return _get(f"/draft/{draft_id}")

    def get_draft_picks(self, draft_id: str) -> list:
        return _get(f"/draft/{draft_id}/picks") or []

    def get_draft_traded_picks(self, draft_id: str) -> list:
        return _get(f"/draft/{draft_id}/traded_picks") or []

    # -- players -------------------------------------------------------------
    def get_players(self, sport: str = "nfl") -> dict:
        """Full player database, disk-cached for 24h (Sleeper asks max 1/day)."""
        cache_file = CACHE_DIR / f"players_{sport}.json"
        if cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age < PLAYERS_TTL_SECONDS:
                return json.loads(cache_file.read_text())
        print("Downloading Sleeper player database (~5 MB, cached 24h)...",
              file=sys.stderr)
        players = _get(f"/players/{sport}") or {}
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(players))
        return players

    def get_trending(self, kind: str = "add", sport: str = "nfl",
                     lookback_hours: int = 24, limit: int = 25) -> list:
        return _get(f"/players/{sport}/trending/{kind}"
                    f"?lookback_hours={lookback_hours}&limit={limit}") or []

    # -- avatars -------------------------------------------------------------
    @staticmethod
    def avatar_url(avatar_id: str | None, thumb: bool = False) -> str | None:
        if not avatar_id:
            return None
        return f"{CDN_URL}/avatars/{'thumbs/' if thumb else ''}{avatar_id}"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _points(settings: dict, prefix: str = "fpts") -> float:
    return settings.get(prefix, 0) + settings.get(f"{prefix}_decimal", 0) / 100.0


def _record(settings: dict) -> str:
    rec = f"{settings.get('wins', 0)}-{settings.get('losses', 0)}"
    if settings.get("ties"):
        rec += f"-{settings['ties']}"
    return rec


def _scoring_label(league: dict) -> str:
    rec = (league.get("scoring_settings") or {}).get("rec", 0)
    label = {1: "PPR", 0.5: "Half PPR", 0: "Standard"}.get(rec, f"{rec} PPR")
    if (league.get("settings") or {}).get("best_ball") == 1:
        label += " Best Ball"
    return label


def _player_label(player_id: str, players: dict) -> str:
    info = players.get(str(player_id))
    if info:
        name = info.get("full_name") or (
            f"{info.get('first_name', '')} {info.get('last_name', '')}".strip())
        pos = info.get("position") or "?"
        team = info.get("team") or "FA"
        return f"{name} ({pos}, {team})"
    # Team defenses are keyed by team abbreviation ("PHI", "SF", ...).
    if player_id.isalpha() and len(player_id) <= 3:
        return f"{player_id} D/ST"
    return f"player {player_id}"


def _team_names(sleeper: Sleeper, league_id: str) -> dict:
    """roster_id -> team display name, from the league's users + rosters."""
    users = {u["user_id"]: u for u in sleeper.get_league_users(league_id)}
    names = {}
    for roster in sleeper.get_rosters(league_id):
        user = users.get(roster.get("owner_id")) or {}
        meta = user.get("metadata") or {}
        names[roster["roster_id"]] = (meta.get("team_name")
                                      or user.get("display_name")
                                      or f"Roster {roster['roster_id']}")
    return names


def _season_chain(sleeper: "Sleeper", league: dict) -> list[dict]:
    """Every season of this league's history, oldest first.

    Sleeper re-creates a new league_id each season and links them backward via
    previous_league_id, so a league that has run since 2023 is really a chain
    of four separate league objects. This walks that chain from whichever
    season you started at back to the very first one.
    """
    chain = [league]
    seen = {league["league_id"]}
    current = league
    while True:
        prev_id = current.get("previous_league_id")
        if not prev_id or str(prev_id) == "0" or prev_id in seen:
            break
        prev = sleeper.get_league(prev_id)
        if not prev:
            break
        chain.append(prev)
        seen.add(prev["league_id"])
        current = prev
    chain.reverse()
    return chain


# ---------------------------------------------------------------------------
# Shared CLI plumbing
# ---------------------------------------------------------------------------

def _resolve_user(sleeper: Sleeper, username: str) -> dict:
    user = sleeper.get_user(username)
    if not user:
        sys.exit(f"Sleeper user '{username}' not found. "
                 "Check the spelling at https://sleeper.com/@" + username)
    return user


def _resolve_season(sleeper: Sleeper, args) -> str:
    if args.season:
        return str(args.season)
    state = sleeper.get_state(args.sport)
    return str(state.get("league_season") or state.get("season") or "")


def _resolve_leagues(sleeper: Sleeper, user: dict, args) -> tuple[list, str]:
    """User's leagues for the chosen season, falling back one season if empty."""
    season = _resolve_season(sleeper, args)
    leagues = sleeper.get_leagues(user["user_id"], season, args.sport)
    if not leagues and not args.season and season.isdigit():
        previous = str(int(season) - 1)
        leagues = sleeper.get_leagues(user["user_id"], previous, args.sport)
        if leagues:
            print(f"(no {season} leagues yet — showing {previous})\n",
                  file=sys.stderr)
            season = previous
    return leagues, season


def _pick_league(leagues: list, choice: str | None) -> dict:
    if not leagues:
        sys.exit("No leagues found for that user/season.")
    if choice:
        for league in leagues:
            if league["league_id"] == choice:
                return league
        if choice.isdigit() and 1 <= int(choice) <= len(leagues):
            return leagues[int(choice) - 1]
        needle = choice.strip().lower()
        matches = [l for l in leagues if needle in l["name"].strip().lower()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            sys.exit(f"--league '{choice}' matches {len(matches)} leagues by name "
                     f"({', '.join(l['name'] for l in matches)}) — use the id or "
                     "1-based index from 'leagues' instead.")
        sys.exit(f"--league '{choice}' does not match a league id, 1-based "
                 f"index, or name (you are in {len(leagues)} league(s); run 'leagues').")
    if len(leagues) > 1:
        print(f"(you are in {len(leagues)} leagues — using '{leagues[0]['name']}'; "
              "pick another with --league)\n", file=sys.stderr)
    return leagues[0]


def _dump(obj) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_profile(sleeper: Sleeper, args) -> None:
    user = _resolve_user(sleeper, args.user)
    if args.raw:
        _dump(user)
        return
    print(f"User:        {user.get('display_name') or user.get('username')}")
    print(f"Username:    {user.get('username')}")
    print(f"User ID:     {user.get('user_id')}")
    avatar = Sleeper.avatar_url(user.get("avatar"))
    if avatar:
        print(f"Avatar:      {avatar}")
    print(f"Profile:     https://sleeper.com/@{user.get('username')}")


def cmd_leagues(sleeper: Sleeper, args) -> None:
    user = _resolve_user(sleeper, args.user)
    leagues, season = _resolve_leagues(sleeper, user, args)
    if args.raw:
        _dump(leagues)
        return
    if not leagues:
        print(f"No {args.sport.upper()} leagues found for "
              f"{user['username']} in {season}.")
        return
    print(f"{user['username']} — {len(leagues)} league(s), {season} season:\n")
    for i, league in enumerate(leagues, 1):
        settings = league.get("settings") or {}
        print(f"{i}. {league['name']}")
        print(f"   id {league['league_id']} | {league.get('total_rosters', '?')} teams"
              f" | {_scoring_label(league)} | status: {league.get('status')}"
              f" | playoff teams: {settings.get('playoff_teams', '?')}")


def cmd_standings(sleeper: Sleeper, args) -> None:
    user = _resolve_user(sleeper, args.user)
    leagues, _season = _resolve_leagues(sleeper, user, args)
    league = _pick_league(leagues, args.league)
    rosters = sleeper.get_rosters(league["league_id"])
    if args.raw:
        _dump(rosters)
        return
    names = _team_names(sleeper, league["league_id"])
    rosters.sort(key=lambda r: (r.get("settings", {}).get("wins", 0),
                                _points(r.get("settings", {}))),
                 reverse=True)
    print(f"{league['name']} — standings\n")
    print(f"{'#':>2}  {'Team':<28} {'W-L':>6} {'PF':>8} {'PA':>8}")
    for rank, roster in enumerate(rosters, 1):
        settings = roster.get("settings") or {}
        name = names.get(roster["roster_id"], f"Roster {roster['roster_id']}")
        marker = " <- you" if roster.get("owner_id") == user["user_id"] else ""
        print(f"{rank:>2}  {name[:28]:<28} {_record(settings):>6} "
              f"{_points(settings):>8.2f} "
              f"{_points(settings, 'fpts_against'):>8.2f}{marker}")


def _find_my_roster(rosters: list, user_id: str) -> dict:
    for roster in rosters:
        owners = [roster.get("owner_id")] + (roster.get("co_owners") or [])
        if user_id in owners:
            return roster
    sys.exit("You don't have a roster in that league.")


def cmd_roster(sleeper: Sleeper, args) -> None:
    user = _resolve_user(sleeper, args.user)
    leagues, _season = _resolve_leagues(sleeper, user, args)
    league = _pick_league(leagues, args.league)
    rosters = sleeper.get_rosters(league["league_id"])
    mine = _find_my_roster(rosters, user["user_id"])
    if args.raw:
        _dump(mine)
        return
    players = sleeper.get_players(args.sport)
    settings = mine.get("settings") or {}
    print(f"{league['name']} — {user['username']}'s roster "
          f"({_record(settings)}, {_points(settings):.2f} PF)\n")
    starters = mine.get("starters") or []
    positions = league.get("roster_positions") or []
    print("Starters:")
    for i, player_id in enumerate(starters):
        slot = positions[i] if i < len(positions) else "?"
        label = ("(empty)" if player_id in ("0", 0, None)
                 else _player_label(player_id, players))
        print(f"  {slot:<6} {label}")
    bench = [p for p in (mine.get("players") or []) if p not in starters]
    if bench:
        print("Bench:")
        for player_id in bench:
            print(f"  {'BN':<6} {_player_label(player_id, players)}")
    for slot_name, key in (("Taxi", "taxi"), ("IR", "reserve")):
        extras = mine.get(key) or []
        if extras:
            print(f"{slot_name}:")
            for player_id in extras:
                print(f"  {'':<6} {_player_label(player_id, players)}")


def cmd_matchup(sleeper: Sleeper, args) -> None:
    user = _resolve_user(sleeper, args.user)
    leagues, _season = _resolve_leagues(sleeper, user, args)
    league = _pick_league(leagues, args.league)
    state = sleeper.get_state(args.sport)
    week = args.week or state.get("display_week") or state.get("week") or 1
    matchups = sleeper.get_matchups(league["league_id"], week)
    if args.raw:
        _dump(matchups)
        return
    if not matchups:
        season_type = state.get("season_type", "?")
        print(f"No week-{week} matchups in '{league['name']}' yet "
              f"(season_type is '{season_type}' — matchups appear once the "
              "regular season starts, or pass --week N).")
        return
    rosters = sleeper.get_rosters(league["league_id"])
    mine = _find_my_roster(rosters, user["user_id"])
    names = _team_names(sleeper, league["league_id"])
    by_roster = {m["roster_id"]: m for m in matchups}
    me = by_roster.get(mine["roster_id"])
    if not me:
        print(f"No week-{week} matchup for your roster (bye or not scheduled).")
        return
    opponent = next((m for m in matchups
                     if m.get("matchup_id") == me.get("matchup_id")
                     and m["roster_id"] != me["roster_id"]), None)
    players = sleeper.get_players(args.sport)

    def side(entry: dict) -> None:
        print(f"{names.get(entry['roster_id'], '?')} — "
              f"{entry.get('points') or 0:.2f} pts")
        starters = entry.get("starters") or []
        starter_points = entry.get("starters_points") or []
        for i, player_id in enumerate(starters):
            pts = (f"{starter_points[i]:>7.2f}" if i < len(starter_points)
                   else "       ")
            print(f"  {pts}  {_player_label(player_id, players)}")

    print(f"{league['name']} — week {week}\n")
    side(me)
    if opponent:
        print("\n   vs\n")
        side(opponent)
    else:
        print("\n(no opponent this week)")


def cmd_trending(sleeper: Sleeper, args) -> None:
    trending = sleeper.get_trending(args.type, args.sport, limit=args.limit)
    if args.raw:
        _dump(trending)
        return
    players = sleeper.get_players(args.sport)
    verb = "added" if args.type == "add" else "dropped"
    print(f"Most-{verb} players, last 24h:\n")
    for i, entry in enumerate(trending, 1):
        print(f"{i:>2}. {_player_label(entry['player_id'], players):<40} "
              f"{entry.get('count', 0):>8,} {verb}")


def _fmt_ts(ms: int | None) -> str:
    if not ms:
        return "?"
    return (datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
            .astimezone().strftime("%Y-%m-%d %H:%M"))


_TX_LABELS = {"trade": "TRADE", "waiver": "WAIVER",
             "free_agent": "FREE AGENT", "commissioner": "COMMISH"}


def _fmt_transaction(t: dict, names: dict, players: dict) -> str:
    """One human-readable block (trades) or line (everything else)."""
    ttype = t.get("type", "?")
    label = _TX_LABELS.get(ttype, ttype.upper())
    week = t.get("leg", "?")
    when = _fmt_ts(t.get("status_updated") or t.get("created"))
    status = t.get("status", "complete")
    status_tag = "" if status == "complete" else f" [{status.upper()}]"
    adds = t.get("adds") or {}
    drops = t.get("drops") or {}
    picks = t.get("draft_picks") or []
    budget = t.get("waiver_budget") or []
    roster_ids = t.get("roster_ids") or []

    def team(rid) -> str:
        return names.get(rid, f"Roster {rid}")

    if ttype == "trade":
        lines = [f"{when}  wk{week:>2}  {label}{status_tag}"]
        for rid in roster_ids:
            gets = [_player_label(pid, players) for pid, r in adds.items() if r == rid]
            gets += [f"{p.get('season', '?')} round {p.get('round', '?')} pick "
                    f"(orig. {team(p.get('roster_id'))})"
                    for p in picks if p.get("owner_id") == rid]
            gets += [f"${fb.get('amount', 0)} FAAB (from {team(fb.get('sender'))})"
                    for fb in budget if fb.get("receiver") == rid]
            if gets:
                lines.append(f"    {team(rid)} gets:  " + "  ·  ".join(gets))
        return "\n".join(lines)

    rid = roster_ids[0] if roster_ids else None
    bits = [f"+{_player_label(pid, players)}" for pid in adds]
    bits += [f"-{_player_label(pid, players)}" for pid in drops]
    settings = t.get("settings") or {}
    faab = f"   ${settings['waiver_bid']} FAAB" if settings.get("waiver_bid") else ""
    note = ((t.get("metadata") or {}).get("notes") or "") if status != "complete" else ""
    note = f"   ({note})" if note else ""
    return (f"{when}  wk{week:>2}  {label:<10}{status_tag}  {team(rid):<24} "
           f"{'  '.join(bits)}{faab}{note}")


def _transaction_rows(t: dict, season: str, names: dict, players: dict) -> list[dict]:
    """Flat rows (one per player/pick/FAAB movement) for CSV export."""
    ttype, week = t.get("type", "?"), t.get("leg", "")
    when = _fmt_ts(t.get("status_updated") or t.get("created"))
    status = t.get("status", "complete")
    base = {"season": season, "week": week, "date": when, "type": ttype, "status": status}
    rows = []
    for pid, rid in (t.get("adds") or {}).items():
        rows.append({**base, "team": names.get(rid, f"Roster {rid}"),
                    "action": "add", "detail": _player_label(pid, players)})
    for pid, rid in (t.get("drops") or {}).items():
        rows.append({**base, "team": names.get(rid, f"Roster {rid}"),
                    "action": "drop", "detail": _player_label(pid, players)})
    for pick in t.get("draft_picks") or []:
        rows.append({**base, "team": names.get(pick.get("owner_id"), "?"),
                    "action": "pick",
                    "detail": f"{pick.get('season', '?')} round {pick.get('round', '?')} "
                              f"(orig. {names.get(pick.get('roster_id'), '?')})"})
    for fb in t.get("waiver_budget") or []:
        rows.append({**base, "team": names.get(fb.get("receiver"), "?"),
                    "action": "faab",
                    "detail": f"${fb.get('amount', 0)} (from "
                              f"{names.get(fb.get('sender'), '?')})"})
    return rows


def cmd_transactions(sleeper: Sleeper, args) -> None:
    user = _resolve_user(sleeper, args.user)
    leagues, _season = _resolve_leagues(sleeper, user, args)
    league = _pick_league(leagues, args.league)
    chain = _season_chain(sleeper, league)
    if args.season:
        chain = [l for l in chain if str(l.get("season")) == str(args.season)]
        if not chain:
            sys.exit(f"'{league['name']}' has no {args.season} season.")

    print(f"Walking {len(chain)} season(s) of '{league['name']}' "
         f"({chain[0].get('season')}-{chain[-1].get('season')})...", file=sys.stderr)

    entries = []  # (season, names, transaction)
    for season_league in chain:
        lid = season_league["league_id"]
        season = str(season_league.get("season", "?"))
        names = _team_names(sleeper, lid)
        for week in range(1, 19):
            for t in sleeper.get_transactions(lid, week):
                entries.append((season, names, t))

    if args.type != "all":
        entries = [e for e in entries if e[2].get("type") == args.type]
    if args.team:
        needle = args.team.strip().lower()
        entries = [e for e in entries
                  if any(needle in e[1].get(rid, "").lower()
                        for rid in (e[2].get("roster_ids") or []))]

    entries.sort(key=lambda e: e[2].get("status_updated") or e[2].get("created") or 0)

    if args.raw:
        _dump([{"season": s, **t} for s, _n, t in entries])
        return

    if args.csv:
        players = sleeper.get_players(args.sport)
        rows = [row for s, n, t in entries for row in _transaction_rows(t, s, n, players)]
        with open(args.csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["season", "week", "date", "type",
                                                    "status", "team", "action", "detail"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {len(rows)} rows ({len(entries)} transactions) to {args.csv}",
             file=sys.stderr)
        return

    players = sleeper.get_players(args.sport)
    counts = Counter(t.get("type") for _s, _n, t in entries)
    seasons_label = (f"{chain[0].get('season')}-{chain[-1].get('season')}"
                     if len(chain) > 1 else str(chain[0].get("season")))
    print(f"\n{league['name']} — full transaction history ({seasons_label})\n")
    print(f"{len(chain)} season(s) · {len(entries)} transactions  "
         f"({counts.get('trade', 0)} trades, {counts.get('waiver', 0)} waiver moves, "
         f"{counts.get('free_agent', 0)} free-agent moves, "
         f"{counts.get('commissioner', 0)} commish moves)")

    current_season = None
    for season, names, t in entries:
        if season != current_season:
            current_season = season
            print(f"\n{season}\n" + "-" * 40)
        print(_fmt_transaction(t, names, players))


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--user", default=DEFAULT_USERNAME,
                        help=f"Sleeper username (default: {DEFAULT_USERNAME})")
    common.add_argument("--sport", default="nfl", help="Sport (default: nfl)")
    common.add_argument("--season", help="Season year (default: current)")
    common.add_argument("--raw", action="store_true",
                        help="Print raw API JSON instead of formatted text")

    parser = argparse.ArgumentParser(
        description="Read-only Sleeper fantasy CLI (no login — the public API "
                    "is unauthenticated by design).")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("profile", parents=[common],
                   help="Show the user's Sleeper profile")
    sub.add_parser("leagues", parents=[common],
                   help="List the user's leagues this season")
    for name, help_text in (("standings", "League standings"),
                            ("roster", "Your roster in a league"),
                            ("matchup", "Your matchup for a week")):
        p = sub.add_parser(name, parents=[common], help=help_text)
        p.add_argument("--league",
                       help="League id, or 1-based index from 'leagues'")
        if name == "matchup":
            p.add_argument("--week", type=int, help="Week (default: current)")
    p = sub.add_parser("trending", parents=[common],
                       help="Most added/dropped players (24h)")
    p.add_argument("--type", choices=("add", "drop"), default="add")
    p.add_argument("--limit", type=int, default=25)

    p = sub.add_parser("transactions", parents=[common],
                       help="Full trade/waiver/free-agent history since week 1, "
                            "walking every season of the league's history")
    p.add_argument("--league",
                   help="League id, 1-based index, or name (e.g. 'girls r stupid')")
    p.add_argument("--type", choices=("all", "trade", "waiver", "free_agent",
                                      "commissioner"), default="all",
                   help="Only show this transaction type (default: all)")
    p.add_argument("--team", help="Only show transactions involving this team "
                                  "(matches team/display name, case-insensitive)")
    p.add_argument("--csv", metavar="PATH",
                   help="Write a flat CSV (one row per player/pick/FAAB move) "
                        "instead of printing")

    args = parser.parse_args(argv)
    sleeper = Sleeper()
    try:
        {"profile": cmd_profile, "leagues": cmd_leagues,
         "standings": cmd_standings, "roster": cmd_roster,
         "matchup": cmd_matchup, "trending": cmd_trending,
         "transactions": cmd_transactions}[args.command](sleeper, args)
    except SleeperError as err:
        sys.exit(f"Sleeper API error: {err}")


if __name__ == "__main__":
    main()
