#!/usr/bin/env python3
"""Bake nflverse opportunity data into a compact file the browser can load.

Run with no arguments, from anywhere:  python3 tools_build_signals.py
Writes data/signals.json next to this script. Also runs unattended in CI —
see .github/workflows/refresh-signals.yml.

Why bake at all: nflverse publishes as GitHub Release assets, which a browser
cannot fetch (no CORS headers anywhere in the redirect chain). A GitHub Actions
runner has no such restriction, so the join happens here and the result is
served same-origin from Pages, where no CORS is involved.

Joining is by normalised name + position, not by id: Sleeper stopped populating
gsis_id/espn_id for everyone drafted 2023 onward, so an id join silently loses
Nacua, Gibbs, Bijan and every other young star. Ambiguous names are dropped
rather than guessed at — there is a wide receiver and a linebacker both called
Justin Jefferson.
"""
import csv, io, json, os, re, sys, urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "signals.json")
REL = "https://github.com/nflverse/nflverse-data/releases/download"
SLEEPER_PLAYERS = "https://api.sleeper.app/v1/players/nfl"
SLEEPER_STATE = "https://api.sleeper.app/v1/state/nfl"
POS = {"QB", "RB", "WR", "TE"}
N_SEASONS = 3


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def fetch(url, timeout=180):
    req = urllib.request.Request(url, headers={"User-Agent": "warchest-signals"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_csv(url):
    return list(csv.DictReader(io.StringIO(fetch(url).decode("utf-8", "replace"))))


def num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def norm(s):
    """Fold spelling differences between sources: punctuation, and the
    generational suffixes one source keeps and the other drops."""
    s = (s or "").lower()
    s = re.sub(r"[.'`\-]", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------- which seasons to build ----------
state = json.loads(fetch(SLEEPER_STATE, 60))
cur = int(state.get("season") or 0)
# Preseason has no games logged, so the newest season with real football in it
# is last year. Once the year is underway the current season leads.
latest = cur - 1 if state.get("season_type") == "pre" else cur
seasons = list(range(latest - N_SEASONS + 1, latest + 1))
log(f"sleeper says season={cur} type={state.get('season_type')} -> latest={latest}, building {seasons}")

# ---------- weekly production ----------
stat = defaultdict(lambda: defaultdict(float))
games = defaultdict(set)
pos_of, name_of = {}, {}

FIELDS = (("fantasy_points_ppr", "fp"), ("targets", "tgt"), ("receptions", "rec"),
          ("carries", "car"), ("receiving_tds", "rec_td"), ("rushing_tds", "rush_td"),
          ("target_share", "ts_sum"), ("air_yards_share", "ays_sum"), ("wopr", "wopr_sum"))

for yr in seasons:
    rows = fetch_csv(f"{REL}/stats_player/stats_player_week_{yr}.csv")
    log(f"  stats_player {yr}: {len(rows)} rows")
    for r in rows:
        if r.get("season_type") != "REG":
            continue
        pos, gid = r.get("position"), r.get("player_id")
        if pos not in POS or not gid:
            continue
        k = (gid, yr)
        for src, dst in FIELDS:
            stat[k][dst] += num(r.get(src))
        games[k].add(r.get("week"))
        pos_of[gid] = pos
        name_of[gid] = r.get("player_display_name") or ""

# ---------- league touchdown rates, for expected touchdowns ----------
# Rushing and receiving only. A quarterback's receiving line is a couple of
# trick plays a year; a rate built on it is noise.
rn, rd = defaultdict(float), defaultdict(float)
for (gid, yr), s in stat.items():
    pos = pos_of.get(gid)
    if yr != latest or pos not in POS:
        continue
    if pos != "QB":
        rn[(pos, "rec")] += s["rec_td"]; rd[(pos, "rec")] += s["tgt"]
    rn[(pos, "rush")] += s["rush_td"]; rd[(pos, "rush")] += s["car"]
RATES = {k: (rn[k] / rd[k] if rd[k] else 0.0) for k in set(rn) | set(rd)}
log("league TD rates:", {f"{a}/{b}": round(v, 4) for (a, b), v in sorted(RATES.items())})

# ---------- snap share ----------
snaps = defaultdict(list)
for yr in seasons:
    try:
        rows = fetch_csv(f"{REL}/snap_counts/snap_counts_{yr}.csv")
    except Exception as e:
        log(f"  snap_counts {yr}: unavailable ({e})")
        continue
    for r in rows:
        if r.get("game_type") != "REG":
            continue
        v, n = r.get("offense_pct"), norm(r.get("player"))
        if n and v not in (None, ""):
            snaps[(n, yr)].append(num(v))

# ---------- draft capital ----------
draft_by_gsis, draft_by_name = {}, {}
for r in fetch_csv(f"{REL}/draft_picks/draft_picks.csv"):
    if r.get("position") not in POS or not num(r.get("round")):
        continue
    d = {"yr": int(num(r.get("season"))), "rd": int(num(r.get("round"))),
         "pk": int(num(r.get("pick")))}
    gid = (r.get("gsis_id") or "").strip()
    if gid:
        draft_by_gsis[gid] = d
    nm = norm(r.get("pfr_player_name"))
    if nm:
        draft_by_name[(nm, r["position"])] = d

# ---------- Sleeper index ----------
sleeper = json.loads(fetch(SLEEPER_PLAYERS, 240))
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
        amb += 1 if cands else 0
        if not cands:
            unmatched.append(name_of[gid])
        continue
    sid = cands[0]
    per_season = {}
    for yr in seasons:
        s = stat.get((gid, yr))
        g = len(games[(gid, yr)])
        if not s or g == 0:
            continue
        x_td = s["car"] * RATES.get((pos, "rush"), 0)
        if pos != "QB":
            x_td += s["tgt"] * RATES.get((pos, "rec"), 0)
        act_td = s["rec_td"] + s["rush_td"]
        # Take lucky and unlucky touchdowns back out of the scoring line.
        # Passing TDs are left alone: QB scoring is volume-driven and far less
        # touchdown-noisy than the rushing and receiving kind.
        fp_adj = s["fp"] - 6.0 * (act_td - x_td)
        sn = snaps.get((norm(name_of[gid]), yr), [])
        per_season[str(yr)] = {
            "g": g, "ppg": round(s["fp"] / g, 2), "xppg": round(fp_adj / g, 2),
            "td": round(act_td, 1), "xtd": round(x_td, 2),
            "tgt": round(s["tgt"] / g, 2), "car": round(s["car"] / g, 2),
            "ts": round(s["ts_sum"] / g, 4), "wopr": round(s["wopr_sum"] / g, 3),
            "snp": round(sum(sn) / len(sn), 3) if sn else None,
        }
    if not per_season:
        continue
    rec = {"pos": pos, "s": per_season}
    d = draft_by_gsis.get(gid) or draft_by_name.get((norm(name_of[gid]), pos))
    if d:
        rec["d"] = d
    out[sid] = rec

# ---------- rookies: drafted, no NFL snaps yet ----------
# Without this the newest class is simply absent, and a dynasty rookie draft is
# exactly when you most need an opinion. Draft capital is the only real signal
# they have, and the app is explicit that that is all it is.
rookies = 0
for (nm, pos), d in draft_by_name.items():
    if d["yr"] < latest:                       # only the classes with no full season yet
        continue
    cands = by_name.get((nm, pos), [])
    if len(cands) != 1:
        continue
    sid = cands[0]
    if sid in out:                             # already has production
        continue
    out[sid] = {"pos": pos, "s": {}, "d": d, "rookie": True}
    rookies += 1

meta = {"built": __import__("datetime").date.today().isoformat(),
        "source": "nflverse: stats_player, snap_counts, draft_picks",
        "seasons": [str(y) for y in seasons], "latest": str(latest),
        "join": "normalised name + position against Sleeper",
        "rookieClasses": sorted({d["yr"] for d in draft_by_name.values() if d["yr"] >= latest}),
        "td_rates": {f"{a}_{b}": round(v, 5) for (a, b), v in RATES.items()}}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    json.dump({"meta": meta, "players": out}, f, separators=(",", ":"))

log(f"matched {len(out)} players ({rookies} draft-capital-only rookies, "
    f"{amb} ambiguous skipped, {len(unmatched)} unmatched)")
log(f"wrote {OUT} ({os.path.getsize(OUT)/1024:.0f} KB)")
if len(out) < 400:
    log("REFUSING: implausibly few players matched — not overwriting with a broken join")
    sys.exit(1)
