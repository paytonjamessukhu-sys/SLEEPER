#!/usr/bin/env python3
"""Bake per-player value-path risk from DynastyProcess's git history.

DynastyProcess overwrites files/values-players.csv weekly; the history of that
file IS the historical record — ~330 weekly snapshots back to 2019, each
fetchable at its commit SHA from raw.githubusercontent.com.

Everything is computed on MARKET SHARE, not raw value. The value scale itself
inflates and deflates across years (the whole market "gained" 120% in one
backtest window), so raw-value volatility would mostly measure the unit, not
the player. Share of the total pool is scale-free.

Known bias, stated rather than hidden: players who crash out of the file
entirely stop contributing observations, so drawdowns here are a FLOOR — the
very worst outcomes (retired, cut, out of the league) truncate their own
series before the bottom.

Run occasionally by hand (python3 tools_build_risk.py). Deliberately NOT in
the weekly refresh: it makes ~330 requests and history only grows one
snapshot a week — a monthly manual run keeps it fresh.
Writes data/risk.json.
"""
import csv, io, json, math, os, re, sys, urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "risk.json")
POS = {"QB", "RB", "WR", "TE"}
TRAIL_WEEKS = 104          # judge risk on the last ~2 years, not a 2019 rookie deal
MIN_OBS = 26               # half a year of weekly points before we claim a number


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def get(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": "warchest-risk"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


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


# ---------- every weekly snapshot of the values file ----------
commits = {}
page = 1
while True:
    u = ("https://api.github.com/repos/dynastyprocess/data/commits"
         f"?path=files/values-players.csv&per_page=100&page={page}")
    batch = json.loads(get(u))
    if not batch:
        break
    for c in batch:
        commits[c["commit"]["committer"]["date"][:10]] = c["sha"]
    page += 1
dates = sorted(commits)
log(f"{len(dates)} snapshots, {dates[0]} .. {dates[-1]}")

# ---------- per-player market-share series ----------
series = defaultdict(list)          # (norm_name, pos) -> [(date, share)]
kept = 0
for i, d in enumerate(dates):
    try:
        raw = get(f"https://raw.githubusercontent.com/dynastyprocess/data/{commits[d]}/files/values-players.csv")
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8", "replace"))))
    except Exception as e:
        log(f"  {d}: skipped ({e})")
        continue
    snap = {}
    for r in rows:
        p = (r.get("pos") or "").upper()
        v = num(r.get("value_1qb"))
        if p in POS and v > 0:
            snap[(norm(r.get("player")), p)] = v
    total = sum(snap.values())
    if total <= 0:
        continue
    for k, v in snap.items():
        series[k].append((d, v / total * 1e4))       # basis points of the market
    kept += 1
    if i % 40 == 0:
        log(f"  ... {i}/{len(dates)} snapshots")
log(f"built series for {len(series)} players from {kept} usable snapshots")

# ---------- risk metrics per player, trailing window ----------
def metrics(pts):
    pts = pts[-TRAIL_WEEKS:]
    if len(pts) < MIN_OBS:
        return None
    shares = [s for _, s in pts]
    rets = []
    for a, b in zip(shares, shares[1:]):
        if a > 0 and b > 0:
            rets.append(math.log(b / a))
    if len(rets) < MIN_OBS - 1:
        return None
    mu = sum(rets) / len(rets)
    vol = math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets))
    peak, mdd = shares[0], 0.0
    for s in shares:
        peak = max(peak, s)
        if peak > 0:
            mdd = max(mdd, 1 - s / peak)
    growth = shares[-1] / shares[0] if shares[0] > 0 else 1.0
    return {"vol": round(vol, 4), "mdd": round(mdd, 3),
            "grow": round(growth, 3), "n": len(shares),
            "cur": round(shares[-1], 2)}

risk = {}
for k, pts in series.items():
    m = metrics(pts)
    if m:
        risk[k] = m
log(f"{len(risk)} players clear the {MIN_OBS}-week bar")

# ---------- join to Sleeper ids ----------
sleeper = json.loads(get("https://api.sleeper.app/v1/players/nfl", 240))
by_name = defaultdict(list)
ages = {}
for pid, p in sleeper.items():
    if not p or p.get("position") not in POS:
        continue
    n = norm(p.get("full_name"))
    if n and n != "player invalid":
        by_name[(n, p["position"])].append(pid)
        if p.get("age"):
            ages[pid] = p["age"]

# Raw weekly values per player, downsampled so the file stays shippable:
# everything from the last year, monthly before that. This is the chart — the
# shape of seven years of price, which no aggregate number carries.
def downsample(pts):
    if not pts:
        return []
    cutoff = pts[-1][0][:7]
    yr, mo = int(cutoff[:4]), int(cutoff[5:7])
    recent_from = f"{yr-1:04d}-{mo:02d}"
    keep, seen_month = [], set()
    for d, v in pts:
        if d[:7] >= recent_from:
            keep.append((d, v))
        elif d[:7] not in seen_month:
            seen_month.add(d[:7])
            keep.append((d, v))
    return keep

out, amb = {}, 0
for (n, p), m in risk.items():
    cands = by_name.get((n, p), [])
    if len(cands) != 1:
        amb += 1 if cands else 0
        continue
    ds = downsample(series[(n, p)])
    out[cands[0]] = {**m, "pos": p,
                     "hist": [[d[2:10], round(v, 1)] for d, v in ds]}  # "YY-MM-DD", share bp

# ---------- archetype table: position x absolute value tier ----------
# Tiers are ABSOLUTE share bands, not percentiles. 879 of 1000 players here are
# sub-10bp tail assets whose ~90% churn is normal roster mortality; a
# percentile cut drowns the players anyone actually rosters in that noise —
# the first version of this table said elite WRs median a 94% drawdown, which
# was the tail talking, not the elites.
def med(v):
    s = sorted(v)
    return round(s[len(s) // 2], 4) if s else None

TIERS = [("elite", 100, 1e9), ("startable", 10, 100), ("tail", 0, 10)]
arch = {}
for p in POS:
    for tname, lo, hi in TIERS:
        rows = [m for m in out.values() if m["pos"] == p and lo < m["cur"] <= hi]
        if len(rows) < 5:
            continue
        arch[f"{p}_{tname}"] = {"n": len(rows),
                                "vol_med": med([m["vol"] for m in rows]),
                                "mdd_med": med([m["mdd"] for m in rows])}
log("archetypes:", json.dumps(arch))

meta = {"built": __import__("datetime").date.today().isoformat(),
        "source": "DynastyProcess values-players.csv git history",
        "snapshots": kept, "from": dates[0], "to": dates[-1],
        "window_weeks": TRAIL_WEEKS, "min_obs": MIN_OBS,
        "unit": "share of total market value (scale-free)",
        "survivorship": "players who fall out of the file stop reporting; drawdowns are a floor",
        "arch": arch}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    json.dump({"meta": meta, "players": out}, f, separators=(",", ":"))
log(f"wrote {OUT} ({os.path.getsize(OUT)/1024:.0f} KB), {len(out)} players ({amb} ambiguous skipped)")
