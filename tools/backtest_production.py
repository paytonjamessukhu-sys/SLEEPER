#!/usr/bin/env python3
"""Does any of this actually predict anything?

Grades each candidate signal measured in season Y against what the player
actually scored in Y+1. Two transitions available: 2023->2024 and 2024->2025.

The claim under test is the one the whole engine was rebuilt on: that
luck-adjusted points predict next season better than raw points do.
"""
import csv, math, sys
from collections import defaultdict

NFLV = "/tmp/nflv"
SEASONS = [2023, 2024, 2025]
POS = {"QB", "RB", "WR", "TE"}
MIN_G = 8


def num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def load(yr):
    tot = defaultdict(lambda: defaultdict(float))
    games = defaultdict(set)
    pos = {}
    with open(f"{NFLV}/wk_{yr}.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("season_type") != "REG":
                continue
            p, gid = r.get("position"), r.get("player_id")
            if p not in POS or not gid:
                continue
            for src, dst in (("fantasy_points_ppr","fp"), ("targets","tgt"), ("carries","car"),
                             ("receiving_tds","rtd"), ("rushing_tds","rtd2"),
                             ("target_share","ts"), ("wopr","wopr")):
                tot[gid][dst] += num(r.get(src))
            games[gid].add(r.get("week"))
            pos[gid] = p
    out = {}
    for gid, s in tot.items():
        g = len(games[gid])
        if g == 0:
            continue
        out[gid] = {"g": g, "pos": pos[gid], "fp": s["fp"],
                    "ppg": s["fp"]/g, "tgt": s["tgt"]/g, "car": s["car"]/g,
                    "ts": s["ts"]/g, "wopr": s["wopr"]/g,
                    "td": s["rtd"] + s["rtd2"], "tgt_tot": s["tgt"], "car_tot": s["car"]}
    return out


def td_rates(season):
    rn, rd = defaultdict(float), defaultdict(float)
    for s in season.values():
        p = s["pos"]
        if p != "QB":
            rn[(p,"rec")] += 0  # filled below
    # recompute properly
    rn, rd = defaultdict(float), defaultdict(float)
    for s in season.values():
        p = s["pos"]
        if p != "QB":
            rd[(p,"rec")] += s["tgt_tot"]
        rd[(p,"rush")] += s["car_tot"]
    # need rec/rush TDs separately; approximate split is not needed —
    # we only need total expected TDs, so use combined volume rates
    return rd


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs)/n, sum(ys)/n
    sx = math.sqrt(sum((x-mx)**2 for x in xs))
    sy = math.sqrt(sum((y-my)**2 for y in ys))
    if sx == 0 or sy == 0:
        return float("nan")
    return sum((x-mx)*(y-my) for x, y in zip(xs, ys))/(sx*sy)


def spearman(xs, ys):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0]*len(v)
        i = 0
        while i < len(order):
            j = i
            while j+1 < len(order) and v[order[j+1]] == v[order[i]]:
                j += 1
            avg = (i+j)/2 + 1
            for k in range(i, j+1):
                r[order[k]] = avg
            i = j+1
        return r
    return pearson(rank(xs), rank(ys))


data = {y: load(y) for y in SEASONS}
for y in SEASONS:
    print(f"{y}: {len(data[y])} players", file=sys.stderr)

# expected touchdowns, per position, from that season's own league rates
def with_xppg(season):
    rn, rd = defaultdict(float), defaultdict(float)
    for s in season.values():
        p = s["pos"]
        rn[(p,"all")] += s["td"]
        rd[(p,"all")] += s["tgt_tot"] + s["car_tot"]
    rate = {k: (rn[k]/rd[k] if rd[k] else 0) for k in rd}
    for s in season.values():
        p = s["pos"]
        opp = s["tgt_tot"] + s["car_tot"]
        s["xtd"] = opp * rate.get((p,"all"), 0)
        s["tdluck"] = s["td"] - s["xtd"]
        s["xppg"] = (s["fp"] - 6.0*s["tdluck"]) / s["g"]
    return season

for y in SEASONS:
    with_xppg(data[y])

PREDICTORS = [
    ("raw ppg",        lambda s: s["ppg"]),
    ("luck-adj ppg",   lambda s: s["xppg"]),
    ("targets/gm",     lambda s: s["tgt"]),
    ("touches/gm",     lambda s: s["tgt"] + s["car"]),
    ("WOPR",           lambda s: s["wopr"]),
    ("target share",   lambda s: s["ts"]),
]

print("\n" + "="*78)
print("PREDICTING NEXT SEASON'S POINTS PER GAME")
print("="*78)

def run(pairs, label, posf=None):
    rows = []
    for y0, y1 in pairs:
        a, b = data[y0], data[y1]
        ids = [g for g in a if g in b and a[g]["g"] >= MIN_G and b[g]["g"] >= MIN_G
               and (posf is None or a[g]["pos"] == posf)]
        if len(ids) < 25:
            continue
        for name, fn in PREDICTORS:
            xs = [fn(a[g]) for g in ids]
            ys = [b[g]["ppg"] for g in ids]
            rows.append((name, y0, y1, len(ids), pearson(xs, ys), spearman(xs, ys)))
    agg = defaultdict(list)
    for name, y0, y1, n, r, rho in rows:
        agg[name].append((n, r, rho))
    print(f"\n--- {label} ---")
    print(f"{'predictor':<16}{'n':>6}{'Pearson r':>12}{'Spearman':>11}")
    ranked = []
    for name, _ in PREDICTORS:
        v = agg.get(name, [])
        if not v:
            continue
        n = sum(x[0] for x in v)
        r = sum(x[1]*x[0] for x in v)/n
        rho = sum(x[2]*x[0] for x in v)/n
        ranked.append((r, name, n, rho))
        print(f"{name:<16}{n:>6}{r:>12.3f}{rho:>11.3f}")
    return ranked

pairs = [(2023, 2024), (2024, 2025)]
overall = run(pairs, "ALL SKILL POSITIONS (both transitions pooled)")
for p in ("QB", "RB", "WR", "TE"):
    run(pairs, f"{p} only", p)

# --- the specific claim: does luck adjustment beat raw points? ---
print("\n" + "="*78)
print("THE CLAIM UNDER TEST: luck-adjusted points vs raw points")
print("="*78)
for y0, y1 in pairs:
    a, b = data[y0], data[y1]
    ids = [g for g in a if g in b and a[g]["g"] >= MIN_G and b[g]["g"] >= MIN_G]
    ys = [b[g]["ppg"] for g in ids]
    r_raw = pearson([a[g]["ppg"] for g in ids], ys)
    r_adj = pearson([a[g]["xppg"] for g in ids], ys)
    print(f"  {y0}->{y1}  n={len(ids):<4} raw r={r_raw:.3f}   luck-adjusted r={r_adj:.3f}   "
          f"{'ADJ WINS' if r_adj > r_raw else 'RAW WINS'} by {abs(r_adj-r_raw):.3f}")

# --- does TD luck predict the CHANGE in scoring? (the regression hypothesis) ---
print("\n" + "="*78)
print("REGRESSION HYPOTHESIS: does this year's TD luck predict next year's DROP?")
print("="*78)
for y0, y1 in pairs:
    a, b = data[y0], data[y1]
    ids = [g for g in a if g in b and a[g]["g"] >= MIN_G and b[g]["g"] >= MIN_G]
    luck = [a[g]["tdluck"] for g in ids]
    delta = [b[g]["ppg"] - a[g]["ppg"] for g in ids]
    print(f"  {y0}->{y1}  n={len(ids):<4} corr(TD luck, next-year change) = {pearson(luck, delta):+.3f}"
          f"   (negative = lucky players fall back, as predicted)")

# --- bucketed view, the version a human can act on ---
print("\n" + "="*78)
print("BUCKETED: average change in PPG the following season")
print("="*78)
buckets = [("very unlucky (<= -3 TD)", lambda l: l <= -3),
           ("unlucky (-3 to -1)",      lambda l: -3 < l <= -1),
           ("neutral (-1 to +1)",      lambda l: -1 < l < 1),
           ("lucky (+1 to +3)",        lambda l: 1 <= l < 3),
           ("very lucky (>= +3 TD)",   lambda l: l >= 3)]
for label, f in buckets:
    ds, ns = [], 0
    for y0, y1 in pairs:
        a, b = data[y0], data[y1]
        for g in a:
            if g in b and a[g]["g"] >= MIN_G and b[g]["g"] >= MIN_G and f(a[g]["tdluck"]):
                ds.append(b[g]["ppg"] - a[g]["ppg"]); ns += 1
    if ns:
        print(f"  {label:<26} n={ns:<4} avg next-season change: {sum(ds)/len(ds):+.2f} ppg")
