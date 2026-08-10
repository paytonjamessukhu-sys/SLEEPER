#!/usr/bin/env python3
"""Bake nflverse opportunity data into a compact file the browser can load.

nflverse publishes as GitHub Release assets, which browsers cannot fetch (no
CORS headers anywhere in the redirect chain). So we join and reduce here, keyed
by Sleeper player id, and commit the result next to index.html where it is
same-origin and needs no CORS at all.

The metrics follow what the research supports: opportunity is sticky year to
year, touchdowns are the least stable thing in football. So we separate the work
a player earned from the luck he got, and let the app compare each against price.

Joining is by normalised name + position, not by id: Sleeper stopped populating
gsis_id/espn_id for everyone drafted 2023 onward, so an id join silently loses
Nacua, Gibbs, Bijan and every other young star. Name matching covers 592 of 608
skill players; ambiguous names are dropped rather than guessed at.
"""
import csv, json, os, re, sys
from collections import defaultdict

NFLV = "/tmp/nflv"
SEASONS = [2023, 2024, 2025]
LATEST = 2025
POS = {"QB", "RB", "WR", "TE"}
OUT = "/Users/paytonsukhu/Desktop/SLEEPER/data/signals.json"


def rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def norm(s):
    """Fold the spelling differences between sources: punctuation and the
    generational suffixes that one source keeps and the other drops."""
    s = (s or "").lower()
    s = re.sub(r"[.'`\-]", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------- weekly production ----------
stat = defaultdict(lambda: defaultdict(float))
games = defaultdict(set)
pos_of, name_of = {}, {}

for yr in SEASONS:
    for r in rows(f"{NFLV}/wk_{yr}.csv"):
        if r.get("season_type") != "REG":
            continue
        pos = r.get("position")
        gid = r.get("player_id")
        if pos not in POS or not gid:
            continue
        k = (gid, yr)
        s = stat[k]
        for src, dst in (("fantasy_points_ppr", "fp"), ("targets", "tgt"),
                         ("receptions", "rec"), ("carries", "car"),
                         ("receiving_tds", "rec_td"), ("rushing_tds", "rush_td"),
                         ("passing_tds", "pass_td"), ("attempts", "att"),
                         ("receiving_yards", "rec_yd"), ("rushing_yards", "rush_yd"),
                         ("passing_yards", "pass_yd"), ("target_share", "ts_sum"),
                         ("air_yards_share", "ays_sum"), ("wopr", "wopr_sum")):
            s[dst] += num(r.get(src))
        games[k].add(r.get("week"))
        pos_of[gid] = pos
        name_of[gid] = r.get("player_display_name") or ""

# ---------- league touchdown rates, for expected TDs ----------
# Only rushing and receiving. A quarterback's receiving line is a handful of
# trick plays a year; a rate built on it is noise, so QB receiving is excluded.
rn, rd = defaultdict(float), defaultdict(float)
for (gid, yr), s in stat.items():
    pos = pos_of.get(gid)
    if yr != LATEST or pos not in POS:
        continue
    if pos != "QB":
        rn[(pos, "rec")] += s["rec_td"]; rd[(pos, "rec")] += s["tgt"]
    rn[(pos, "rush")] += s["rush_td"]; rd[(pos, "rush")] += s["car"]
RATES = {k: (rn[k] / rd[k] if rd[k] else 0.0) for k in set(rn) | set(rd)}
print("league TD rates:", {f"{a}/{b}": round(v, 4) for (a, b), v in sorted(RATES.items())},
      file=sys.stderr)

# ---------- snap share (joined on normalised name) ----------
snaps = defaultdict(list)
for yr in SEASONS:
    p = f"{NFLV}/snap_{yr}.csv"
    if not os.path.exists(p):
        continue
    for r in rows(p):
        if r.get("game_type") != "REG":
            continue
        v = r.get("offense_pct")
        n = norm(r.get("player"))
        if n and v not in (None, ""):
            snaps[(n, yr)].append(num(v))

# ---------- draft capital ----------
draft = {}
for r in rows(f"{NFLV}/draft.csv"):
    gid = (r.get("gsis_id") or "").strip()
    if gid and num(r.get("round")):
        draft[gid] = {"yr": int(num(r.get("season"))), "rd": int(num(r.get("round"))),
                      "pk": int(num(r.get("pick")))}

# ---------- Sleeper index, by normalised name + position ----------
sleeper = json.load(open("/tmp/sleeper_players.json"))
by_name = defaultdict(list)
for pid, p in sleeper.items():
    if not p or p.get("position") not in POS:
        continue
    n = norm(p.get("full_name"))
    if n and n != "player invalid":
        by_name[(n, p["position"])].append(pid)

out, amb, unmatched = {}, 0, []
for gid, pos in pos_of.items():
    cands = by_name.get((norm(name_of[gid]), pos), [])
    if len(cands) != 1:
        (unmatched if not cands else [None]) and None
        if cands:
            amb += 1
        else:
            unmatched.append(name_of[gid])
        continue                      # never guess between two players
    sid = cands[0]
    seasons = {}
    for yr in SEASONS:
        s = stat.get((gid, yr))
        g = len(games[(gid, yr)])
        if not s or g == 0:
            continue
        x_td = s["car"] * RATES.get((pos, "rush"), 0)
        if pos != "QB":
            x_td += s["tgt"] * RATES.get((pos, "rec"), 0)
        act_td = s["rec_td"] + s["rush_td"]
        # Strip lucky/unlucky touchdowns out of the scoring line. Passing TDs are
        # left alone; QB scoring is volume-driven and far less TD-noisy.
        fp_adj = s["fp"] - 6.0 * (act_td - x_td)
        sn = snaps.get((norm(name_of[gid]), yr), [])
        seasons[str(yr)] = {
            "g": g,
            "ppg": round(s["fp"] / g, 2),
            "xppg": round(fp_adj / g, 2),
            "td": round(act_td, 1),
            "xtd": round(x_td, 2),
            "tgt": round(s["tgt"] / g, 2),
            "car": round(s["car"] / g, 2),
            "ts": round(s["ts_sum"] / g, 4),
            "wopr": round(s["wopr_sum"] / g, 3),
            "snp": round(sum(sn) / len(sn), 3) if sn else None,
        }
    if not seasons:
        continue
    rec = {"pos": pos, "s": seasons}
    if gid in draft:
        rec["d"] = draft[gid]
    out[sid] = rec

meta = {"built": "2026-08-10",
        "source": "nflverse: stats_player, snap_counts, draft_picks",
        "seasons": [str(y) for y in SEASONS], "latest": str(LATEST),
        "join": "normalised name + position against Sleeper",
        "td_rates": {f"{a}_{b}": round(v, 5) for (a, b), v in RATES.items()}}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    json.dump({"meta": meta, "players": out}, f, separators=(",", ":"))
print(f"matched {len(out)} players ({amb} ambiguous skipped, {len(unmatched)} unmatched)",
      file=sys.stderr)
print(f"wrote {OUT} ({os.path.getsize(OUT)/1024:.0f} KB)", file=sys.stderr)
print("unmatched sample:", unmatched[:10], file=sys.stderr)
