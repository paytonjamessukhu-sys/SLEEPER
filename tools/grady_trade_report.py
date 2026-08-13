#!/usr/bin/env python3
"""
Full hindsight trade report for one team in a Sleeper dynasty league:
every trade since week 1, every asset resolved to what it's worth *today*
(FantasyCalc dynasty market values), every traded pick resolved to the
actual player it turned into (once that season's rookie draft is complete).

Built for 'girls r stupid' / GradyNBilo235, but works for any team by name.

Usage:
    python3 tools/grady_trade_report.py                       # Grady, default
    python3 tools/grady_trade_report.py --team "Will you suck it"
    python3 tools/grady_trade_report.py -o ../data/grady_trades.json

Stdlib + sleeper_client only (network: api.sleeper.app, api.fantasycalc.com).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sleeper_client as sc  # noqa: E402

FC_URL = "https://api.fantasycalc.com/values/current"
GENERIC_PICK_RE = re.compile(r"^(\d{4}) (1st|2nd|3rd|4th)$")
ORDINAL = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}


# ---------------------------------------------------------------------------
# FantasyCalc values
# ---------------------------------------------------------------------------

def fetch_fc_values(num_qbs: int, ppr: float, teams: int) -> dict:
    """-> {'players': {sleeper_id: value_row}, 'generic_picks': {(season, round): value}}"""
    url = f"{FC_URL}?isDynasty=true&numQbs={num_qbs}&numTeams={teams}&ppr={ppr}"
    req = urllib.request.Request(url, headers={"User-Agent": "warchest-grady-report/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        rows = json.loads(resp.read().decode("utf-8"))

    players, generic_picks = {}, {}
    for row in rows:
        p = row["player"]
        sid = p.get("sleeperId")
        if sid:
            players[str(sid)] = row
        m = GENERIC_PICK_RE.match(p.get("name", ""))
        if m:
            season, ord_label = m.group(1), m.group(2)
            rnd = {v: k for k, v in ORDINAL.items()}[ord_label]
            generic_picks[(season, rnd)] = row["value"]
    return {"players": players, "generic_picks": generic_picks}


def player_value(sleeper_pid: str, fc: dict, players_db: dict) -> tuple[int, str, str]:
    """-> (value, display name, position). 0/'' if FantasyCalc has no line on the
    player; position falls back to Sleeper's player db either way."""
    info = players_db.get(str(sleeper_pid)) or {}
    pos = info.get("position") or ""
    row = fc["players"].get(str(sleeper_pid))
    if row:
        return row["value"], row["player"]["name"], row["player"].get("position") or pos
    if pos:
        name = info.get("full_name") or (
            f"{info.get('first_name', '')} {info.get('last_name', '')}".strip())
        return 0, name, pos
    return 0, sc._player_label(sleeper_pid, players_db), pos


# ---------------------------------------------------------------------------
# League-history plumbing (season chain, per-season roster/draft state)
# ---------------------------------------------------------------------------

def build_season_state(sleeper: sc.Sleeper, chain: list[dict]) -> dict:
    """Per season: names, owner_by_roster, draft_order, and resolved rookie-draft
    results (round, draft_slot) -> player_id, once that season's draft is done."""
    state = {}
    for league in chain:
        season = str(league.get("season"))
        lid = league["league_id"]
        names = sc._team_names(sleeper, lid)
        rosters = sleeper.get_rosters(lid)
        owner_by_roster = {r["roster_id"]: r["owner_id"] for r in rosters}

        drafts = sleeper.get_league_drafts(lid)
        rookie_draft = min(
            (d for d in drafts if d.get("status") == "complete"),
            key=lambda d: d.get("settings", {}).get("rounds", 999),
            default=None,
        )
        draft_order, results = {}, {}
        if rookie_draft:
            draft_order = rookie_draft.get("draft_order") or {}
            for pick in sleeper.get_draft_picks(rookie_draft["draft_id"]):
                results[(pick["round"], pick["draft_slot"])] = pick.get("player_id")

        state[season] = {
            "league_id": lid, "names": names, "owner_by_roster": owner_by_roster,
            "draft_order": draft_order, "draft_results": results,
        }
    return state


def resolve_pick(season: str, rnd: int, orig_roster_id: int, state: dict,
                 fc: dict, players_db: dict) -> tuple[str, int, str]:
    """-> (label, value, position) for a traded pick: drafted-player value/pos
    if the draft happened, else FantasyCalc's generic market value for that
    future pick (position 'PICK')."""
    season_state = state.get(season)
    if season_state and season_state["draft_results"]:
        owner_uid = season_state["owner_by_roster"].get(orig_roster_id)
        slot = season_state["draft_order"].get(owner_uid) if owner_uid else None
        player_id = season_state["draft_results"].get((rnd, slot)) if slot else None
        if player_id:
            value, name, pos = player_value(player_id, fc, players_db)
            orig_team = season_state["names"].get(orig_roster_id, f"Roster {orig_roster_id}")
            return f"{season} rd{rnd} pick (orig. {orig_team}) -> {name}", value, pos
    # future / unresolved pick: fall back to today's generic market value.
    # The pick's season isn't in our known chain yet, but roster_id numbering
    # is stable across it (build_season_state fills `state` oldest-first), so
    # the most-recently-inserted season's names are the best team-name guess.
    latest_names = list(state.values())[-1]["names"] if state else {}
    value = fc["generic_picks"].get((season, rnd), 0)
    orig_team = latest_names.get(orig_roster_id, f"Roster {orig_roster_id}")
    return (f"{season} {ORDINAL.get(rnd, f'rd{rnd}')} pick (orig. {orig_team}, undrafted)",
           value, "PICK")


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

def grade(net: int, moved: int) -> str:
    if moved == 0:
        return "-"
    pct = net / moved
    if pct >= 0.30:
        return "A+"
    if pct >= 0.15:
        return "A"
    if pct >= 0.05:
        return "B"
    if pct > -0.05:
        return "C"
    if pct > -0.15:
        return "D"
    if pct > -0.30:
        return "D-"
    return "F"


# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--user", default=sc.DEFAULT_USERNAME)
    ap.add_argument("--league", default="girls r stupid")
    ap.add_argument("--team", default="GradyNBilo235",
                    help="Team/display name to build the report for")
    ap.add_argument("-o", "--out", help="Write JSON report to this path")
    args = ap.parse_args()

    sleeper = sc.Sleeper()
    user = sc._resolve_user(sleeper, args.user)
    leagues, _season = sc._resolve_leagues(sleeper, user, argparse.Namespace(
        season=None, sport="nfl"))
    league = sc._pick_league(leagues, args.league)
    chain = sc._season_chain(sleeper, league)
    print(f"'{league['name']}' — {len(chain)} season(s), "
         f"{chain[0]['season']}-{chain[-1]['season']}", file=sys.stderr)

    lg = sleeper.get_league(chain[-1]["league_id"])
    num_qbs = 2 if lg.get("roster_positions", []).count("QB") + \
                    lg.get("roster_positions", []).count("SUPER_FLEX") > 1 else 1
    ppr = (lg.get("scoring_settings") or {}).get("rec", 1)
    teams = lg.get("total_rosters", 12)

    print("Fetching FantasyCalc dynasty values...", file=sys.stderr)
    fc = fetch_fc_values(num_qbs, ppr, teams)
    players_db = sleeper.get_players("nfl")

    print("Building per-season roster/draft state...", file=sys.stderr)
    state = build_season_state(sleeper, chain)

    latest = state[str(chain[-1]["season"])]
    try:
        my_roster_id = next(rid for rid, name in latest["names"].items()
                            if name.lower() == args.team.lower())
    except StopIteration:
        sys.exit(f"No team named '{args.team}' in '{league['name']}' "
                 f"(teams: {', '.join(latest['names'].values())})")

    trades = []
    for league_season in chain:
        season = str(league_season["season"])
        lid = league_season["league_id"]
        names = state[season]["names"]
        for week in range(1, 19):
            for t in sleeper.get_transactions(lid, week):
                if t.get("type") != "trade" or my_roster_id not in (t.get("roster_ids") or []):
                    continue
                adds = t.get("adds") or {}
                picks, budget = t.get("draft_picks") or [], t.get("waiver_budget") or []

                # adds[pid] = destination roster, drops[pid] = origin roster —
                # both keyed on the same player for a trade, so adds alone
                # tells us which side of the swap each player landed on.
                received, given = [], []
                for pid, rid in adds.items():
                    value, name, pos = player_value(pid, fc, players_db)
                    (received if rid == my_roster_id else given).append(
                        {"kind": "player", "name": name, "value": value, "pos": pos})
                for p in picks:
                    label, value, pos = resolve_pick(p["season"], p["round"], p["roster_id"],
                                                     state, fc, players_db)
                    side = received if p["owner_id"] == my_roster_id else given
                    side.append({"kind": "pick", "name": label, "value": value, "pos": pos})
                for fb in budget:
                    entry = {"kind": "faab", "name": f"${fb.get('amount', 0)} FAAB",
                             "value": 0, "pos": "FAAB"}
                    if fb.get("receiver") == my_roster_id:
                        received.append(entry)
                    elif fb.get("sender") == my_roster_id:
                        given.append(entry)

                opp_ids = [r for r in (t.get("roster_ids") or []) if r != my_roster_id]
                v_recv = sum(x["value"] for x in received)
                v_give = sum(x["value"] for x in given)
                trades.append({
                    "season": season, "week": t.get("leg"),
                    "date": sc._fmt_ts(t.get("status_updated") or t.get("created")),
                    "opponents": [names.get(r, f"Roster {r}") for r in opp_ids],
                    "received": sorted(received, key=lambda x: -x["value"]),
                    "given": sorted(given, key=lambda x: -x["value"]),
                    "value_received": v_recv, "value_given": v_give,
                    "net": v_recv - v_give,
                    "grade": grade(v_recv - v_give, v_recv + v_give),
                })

    trades.sort(key=lambda tr: (tr["season"], tr["week"] or 0))
    total_recv = sum(tr["value_received"] for tr in trades)
    total_give = sum(tr["value_given"] for tr in trades)
    report = {
        "league_name": league["name"],
        "team_name": args.team,
        "format": {"numQbs": num_qbs, "ppr": ppr, "teams": teams},
        "seasons": [str(l["season"]) for l in chain],
        "summary": {
            "trade_count": len(trades),
            "value_received": total_recv,
            "value_given": total_give,
            "net": total_recv - total_give,
            "wins": sum(1 for tr in trades if tr["net"] > 0),
            "losses": sum(1 for tr in trades if tr["net"] < 0),
            "pushes": sum(1 for tr in trades if tr["net"] == 0),
        },
        "trades": trades,
    }

    text = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).write_text(text)
        print(f"Wrote {len(trades)} trades to {args.out}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
