#!/usr/bin/env python3
"""Value backtest, second pass — this time replicating the SHIPPED engine.

Two corrections over the first attempt:

  1. Age bands. The live engine compares a player only against others his own
     age, which was added precisely to stop it buying declining veterans. A test
     using position-only cohorts is testing a different engine. DynastyProcess
     ships an age column, so we can replicate it properly.

  2. Scale-invariant outcome. Raw percentage change made the whole market look
     like it gained 120% in a year, which means the value scale itself moves.
     We measure each player's SHARE of the total value pool instead, so a call
     is judged against what the market did, not against the units.
"""
import csv, io, json, re, sys, urllib.request
from collections import defaultdict

NFLV = "/tmp/nflv"
POS = {"QB", "RB", "WR", "TE"}
MIN_G, FULL_GP = 8, 14
AGE_BANDS = [(24, "<=24"), (27, "25-27"), (30, "28-30"), (99, "31+")]


def get(url, timeout=90):
    r = urllib.request.Request(url, headers={"User-Agent": "wc-backtest"})
    return urllib.request.urlopen(r, timeout=timeout).read()


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"[.'`\-]", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def band(a):
    return next(b for lim, b in AGE_BANDS if (a or 26) <= lim)


commits = json.load(open("dp_commits.json"))


def snapshot_near(target):
    dates = sorted(d for d in commits if d <= target)
    d = dates[-1]
    raw = get(f"https://raw.githubusercontent.com/dynastyprocess/data/{commits[d]}/files/values-players.csv")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8", "replace"))))
    vals = {}
    for r in rows:
        p = (r.get("pos") or "").upper()
        v = num(r.get("value_1qb"))
        if p in POS and v > 0:
            vals[(norm(r.get("player")), p)] = {"v": v, "age": num(r.get("age")) or None}
    tot = sum(x["v"] for x in vals.values())
    for x in vals.values():
        x["share"] = x["v"]/tot*1e4          # share of the whole market, in basis points
    return d, vals


def load(yr):
    tot = defaultdict(lambda: defaultdict(float))
    games, pos, name = defaultdict(set), {}, {}
    with open(f"{NFLV}/wk_{yr}.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("season_type") != "REG":
                continue
            p, gid = r.get("position"), r.get("player_id")
            if p not in POS or not gid:
                continue
            for src, dst in (("fantasy_points_ppr","fp"), ("targets","tgt"), ("carries","car"),
                             ("receiving_tds","rtd"), ("rushing_tds","rtd2"), ("wopr","wopr")):
                tot[gid][dst] += num(r.get(src))
            games[gid].add(r.get("week")); pos[gid] = p
            name[gid] = r.get("player_display_name") or ""
    out = {}
    for gid, s in tot.items():
        g = len(games[gid])
        if g:
            out[(norm(name[gid]), pos[gid])] = {
                "g": g, "pos": pos[gid], "fp": s["fp"], "td": s["rtd"]+s["rtd2"],
                "opp": s["tgt"]+s["car"], "tgt": s["tgt"]/g, "car": s["car"]/g,
                "wopr": s["wopr"]/g}
    rn, rd = defaultdict(float), defaultdict(float)
    for s in out.values():
        rn[s["pos"]] += s["td"]; rd[s["pos"]] += s["opp"]
    for s in out.values():
        rate = rn[s["pos"]]/rd[s["pos"]] if rd[s["pos"]] else 0
        s["xtd"] = s["opp"]*rate
        s["luck"] = s["td"] - s["xtd"]
        s["xppg"] = s["fp"]/s["g"] if s["pos"] == "QB" else (s["fp"] - 6.0*s["luck"])/s["g"]
    return out


def tag_all(stats, prices, use_age):
    rows, cohorts = {}, defaultdict(list)
    for k, s in stats.items():
        if k not in prices or s["g"] < MIN_G:
            continue
        p = prices[k]
        b = band(p["age"]) if use_age else "all"
        cohorts[(s["pos"], b)].append((k, s, p["v"]))
    for (p, b), lst in cohorts.items():
        if len(lst) < 5:
            continue
        byprice = sorted(lst, key=lambda x: -x[2])
        curve = [x[2] for x in byprice]
        prank = {x[0]: i+1 for i, x in enumerate(byprice)}
        for i, (k, s, v) in enumerate(sorted(lst, key=lambda x: -x[1]["xppg"])):
            implied = curve[i] if i < len(curve) else 0
            edge = (implied - v)*min(1.0, s["g"]/FULL_GP)
            material = v >= 500 and implied >= 1000
            cut = max(5, -(-len(lst)//4))
            tag = ("HOLD" if (not material or abs(edge) < 500) else
                   "BUY" if edge > 0 else
                   "WATCH" if prank[k] <= cut else "SELL")
            use = (s["tgt"]+s["car"]) if p == "RB" else s["wopr"]
            tier = ("elite" if (use >= 18 if p == "RB" else use >= 0.70) else
                    "strong" if (use >= 13 if p == "RB" else use >= 0.55) else "weak")
            rows[k] = {"tag": tag, "edge": edge, "luck": s["luck"], "pos": p,
                       "tier": tier, "band": b}
    return rows


def report(decide, season, outcome, use_age):
    d0, p0 = snapshot_near(decide)
    d1, p1 = snapshot_near(outcome)
    calls = tag_all(load(season), p0, use_age)
    got = {k: (p1[k]["share"] - p0[k]["share"])/p0[k]["share"]*100
           for k in calls if k in p1}
    base = sum(got.values())/len(got) if got else 0
    mode = "WITH age bands (as shipped)" if use_age else "position-only cohorts"
    print(f"\n{'='*78}\n{mode}: decide {d0} on the {season} season -> score {d1}\n{'='*78}")
    print(f"  {len(calls)} gradeable, {len(got)} still priced a year later")
    print(f"  average change in market share among them: {base:+.1f}%  (the bar)\n")
    print(f"  {'call':<26}{'n':>5}{'avg share change':>19}{'vs bar':>10}")
    bucket = defaultdict(list)
    for k, c in calls.items():
        if k in got:
            bucket[c["tag"]].append(got[k])
            if c["luck"] <= -2: bucket["  unlucky (<=-2 TD)"].append(got[k])
            elif c["luck"] >= 2: bucket["  lucky (>=+2 TD)"].append(got[k])
    for key in ("BUY","HOLD","WATCH","SELL","  unlucky (<=-2 TD)","  lucky (>=+2 TD)"):
        v = bucket.get(key, [])
        if len(v) < 5:
            continue
        m = sum(v)/len(v)
        flag = "  <-- beats market" if m > base + 3 else "  <-- LOSES to market" if m < base - 3 else ""
        print(f"  {key:<26}{len(v):>5}{m:>18.1f}%{m-base:>+9.1f}{flag}")
    return {k: (len(v), sum(v)/len(v) - base) for k, v in bucket.items() if len(v) >= 5}


for use_age in (True, False):
    report("2024-08-15", 2023, "2025-08-15", use_age)
    report("2025-08-15", 2024, "2026-08-07", use_age)
