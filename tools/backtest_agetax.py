#!/usr/bin/env python3
"""The age-arbitrage claim on trial.

Claim: dynasty markets over-discount age, so an OLD player costs fewer dynasty
dollars per point of next-season production than a YOUNG player at the same
market value. If true, a competing team should buy vets.

Test, no lookahead: at each August decision date, take DynastyProcess values
and ages; outcome is actual next-season PPG (nflverse, min 8 games). Compare
points-per-1000-value across age groups WITHIN THE SAME VALUE DECILE — the
small-base trap bit twice before, everything is value-matched now. Also check
the two-year points stream where data allows, because "vets score now" has to
survive "and then they retire".

Verdict by permutation court: shuffle age labels within deciles, ask how often
chance produces the observed old-vs-young gap.
"""
import csv, io, json, math, random, re, statistics as st, sys, urllib.request
from collections import defaultdict

random.seed(7)
NFLV = "/tmp/nflv"
POS = {"QB", "RB", "WR", "TE"}
MIN_G = 8


def get(u):
    r = urllib.request.Request(u, headers={"User-Agent": "wc-agetax"})
    return urllib.request.urlopen(r, timeout=90).read()


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


commits = json.load(open("dp_commits.json"))


def snapshot(target):
    d = sorted(x for x in commits if x <= target)[-1]
    raw = get(f"https://raw.githubusercontent.com/dynastyprocess/data/{commits[d]}/files/values-players.csv")
    out = {}
    for r in csv.DictReader(io.StringIO(raw.decode("utf-8", "replace"))):
        p = (r.get("pos") or "").upper()
        v = num(r.get("value_1qb"))
        a = num(r.get("age"))
        if p in POS and v > 0 and a > 0:
            out[(norm(r.get("player")), p)] = (v, a)
    return d, out


def season_ppg(yr):
    tot, games = defaultdict(float), defaultdict(set)
    name_pos = {}
    with open(f"{NFLV}/wk_{yr}.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("season_type") != "REG":
                continue
            p, gid = r.get("position"), r.get("player_id")
            if p not in POS or not gid:
                continue
            tot[gid] += num(r.get("fantasy_points_ppr"))
            games[gid].add(r.get("week"))
            name_pos[gid] = (norm(r.get("player_display_name")), p)
    out = {}
    for gid, pts in tot.items():
        g = len(games[gid])
        if g >= MIN_G:
            out[name_pos[gid]] = pts / g
    return out


def window(decide, out_year, second_year=None):
    d, snap = snapshot(decide)
    nxt = season_ppg(out_year)
    nxt2 = season_ppg(second_year) if second_year else None
    rows = []
    for k, (v, a) in snap.items():
        if v < 500:                      # sub-rosterable noise, the known trap
            continue
        ppg = nxt.get(k)
        if ppg is None:                  # didn't play 8 games next year — that IS part of vet risk,
            ppg = 0.0                    # so count it as zero production, don't silently drop it
        row = {"k": k, "v": v, "age": a, "ppg": ppg,
               "ppk": ppg / (v / 1000.0)}
        if nxt2 is not None:
            row["ppg2"] = (nxt.get(k, 0.0) + nxt2.get(k, 0.0)) / 2
            row["ppk2"] = row["ppg2"] / (v / 1000.0)
        rows.append(row)
    # value deciles
    vals = sorted(r["v"] for r in rows)
    import bisect
    for r in rows:
        r["dec"] = min(9, bisect.bisect_left(vals, r["v"]) * 10 // len(vals))
    return d, rows


def grade(rows, field, label):
    old = [r for r in rows if r["age"] >= 27]
    yng = [r for r in rows if r["age"] <= 24]
    # value-matched: compare each old player to the median of young players in his decile
    ymed = {}
    for dec in range(10):
        ys = [r[field] for r in yng if r["dec"] == dec]
        if len(ys) >= 3:
            ymed[dec] = st.median(ys)
    matched = [r for r in old if r["dec"] in ymed]
    if len(matched) < 10:
        print(f"  {label}: too few matched old players ({len(matched)})")
        return None
    obs = st.median([r[field] - ymed[r["dec"]] for r in matched])
    # permutation: shuffle old/young labels within each decile
    pool_by_dec = defaultdict(list)
    for r in rows:
        if r["age"] >= 27 or r["age"] <= 24:
            pool_by_dec[r["dec"]].append(r)
    nulls = []
    for _ in range(3000):
        diffs = []
        for r in matched:
            alt = random.choice(pool_by_dec[r["dec"]])
            diffs.append(alt[field] - ymed[r["dec"]])
        nulls.append(st.median(diffs))
    p = (sum(1 for x in nulls if x >= obs) + 1) / (len(nulls) + 1)
    o_med = st.median([r[field] for r in matched])
    y_all = st.median([ymed[r["dec"]] for r in matched])
    print(f"  {label}: old(27+) {o_med:.2f} vs value-matched young(<=24) {y_all:.2f} "
          f"per 1k value -> excess {obs:+.2f}  (n_old={len(matched)}, perm p={p:.3f})")
    return obs, p


print("=" * 76)
print("AGE ARBITRAGE ON TRIAL: points per 1,000 dynasty value, value-matched")
print("=" * 76)
d1, r1 = window("2023-08-15", 2024, 2025)
print(f"\ndecide {d1}, outcome 2024 (and 2024+25 avg for the 2-year stream)")
a = grade(r1, "ppk", "next-season pts/1k")
b = grade(r1, "ppk2", "two-year   pts/1k")
d2, r2 = window("2024-08-15", 2025)
print(f"\ndecide {d2}, outcome 2025")
c = grade(r2, "ppk", "next-season pts/1k")

print()
print("=" * 76)
print("VERDICT")
print("=" * 76)
tests = [x for x in (a, b, c) if x]
if all(x[0] > 0 for x in tests):
    worst = max(x[1] for x in tests)
    print(f"  Direction unanimous ({len(tests)} tests): old players out-produce their price.")
    print(f"  Worst permutation p across tests: {worst:.3f}")
    print("  " + ("Survives the court." if worst < 0.05 else
                  "Direction consistent but does not clear p<0.05 everywhere — report as measured, label honestly."))
else:
    print("  Direction NOT unanimous — the claim does not hold as stated.")
