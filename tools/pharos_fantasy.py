#!/usr/bin/env python3
"""Point Pharos at fantasy football.

Three questions, in order of how much they matter:

  1. Does dynasty value follow a power law in positional rank? If it does, the
     fitted curve is a principled replacement for the jagged empirical ladder
     the engine currently reads implied value off, and the exponent measures
     positional scarcity directly.
  2. Do the two markets fit DIFFERENT exponents? That would be a structural
     disagreement about how much premium elite players deserve — deeper than
     the per-player rank gaps already shipped.
  3. Does the engine's own BUY result survive a permutation court? It was
     reported on the strength of sign agreement across two windows and n=22.
     The courts method is exactly the right tool to try to kill it.
"""
import json, math, random, sys, urllib.request
sys.path.insert(0, "pharos")
from pharos_lib import report, courts, fit_power, run_search

random.seed(7)
FC = "https://api.fantasycalc.com/values/current"
POS = ("QB", "RB", "WR", "TE")


def get(url, timeout=90):
    r = urllib.request.Request(url, headers={"User-Agent": "wc-pharos"})
    return json.load(urllib.request.urlopen(r, timeout=timeout))


print("="*70); print("GATES — the instrument must prove itself first"); print("="*70)
# G1: Kepler. period^2 ~ radius^3, so period ~ radius^1.5
rad = [0.387, 0.723, 1.0, 1.524, 5.203, 9.537, 19.19, 30.07]
per = [0.241, 0.615, 1.0, 1.881, 11.86, 29.45, 84.02, 164.8]
v1, _, _ = report("G1 Kepler (law exists, e should be 1.500)", rad, per)
assert v1 == "DISCOVERY", "instrument failed to find Kepler"
# G2: pure noise must be refused
xs = [i+1 for i in range(30)]
v2, _, _ = report("G2 pure noise (must refuse)", xs, [random.uniform(1, 100) for _ in xs])
assert v2 == "NO_DISCOVERY", "instrument hallucinated a law in noise"
# G3: fabricated exact data must trip the alarm
v3, _, _ = report("G3 fabricated exact (must alarm)", xs, [3.0*x**1.7 for x in xs])
assert v3.startswith("TOO_PERFECT"), "instrument failed to catch synthetic data"
print("ALL GATES PASSED\n")

# ---------------------------------------------------------------- Q1 + Q2
sig = json.load(open("/Users/paytonsukhu/Desktop/SLEEPER/data/signals.json"))["players"]
fc_rows = get(f"{FC}?isDynasty=true&numQbs=1&numTeams=12&ppr=1")
fc = {}
for r in fc_rows:
    sid = (r.get("player") or {}).get("sleeperId")
    p = (r.get("player") or {}).get("position")
    if sid and p in POS and (r.get("value") or 0) > 0:
        fc[str(sid)] = (p, r["value"])

print("="*70); print("Q1 — does dynasty value follow a power law in positional rank?")
print("="*70)
exps = {}
for p in POS:
    vals = sorted([v for (pp, v) in fc.values() if pp == p], reverse=True)
    vals = [v for v in vals if v > 0][:60]        # the rosterable part of the board
    if len(vals) < 20:
        continue
    xs = [i+1 for i in range(len(vals))]
    v, params, cv = report(f"FantasyCalc {p} value vs rank (n={len(vals)})", xs, vals)
    exps[p] = (params[1], v)

print("="*70); print("Q2 — do the two markets fit different exponents?")
print("="*70)
for p in POS:
    dp = sorted([sg["dp"]["v1"] for sg in sig.values()
                 if sg.get("pos") == p and sg.get("dp", {}).get("v1", 0) > 0], reverse=True)[:60]
    if len(dp) < 20:
        continue
    xs = [i+1 for i in range(len(dp))]
    v, params, cv = report(f"DynastyProcess {p} value vs rank (n={len(dp)})", xs, dp)
    if p in exps:
        e_fc, e_dp = exps[p][0], params[1]
        print(f"   -> FantasyCalc e={e_fc:+.3f} vs consensus e={e_dp:+.3f}   "
              f"gap {abs(e_fc-e_dp):.3f} — {'DIFFERENT SHAPE' if abs(e_fc-e_dp) > 0.15 else 'same shape'}")
print()
print("positional scarcity ranking (steeper = more top-heavy = elites scarcer):")
for p, (e, v) in sorted(exps.items(), key=lambda kv: kv[1][0]):
    print(f"   {p}: e={e:+.3f}  [{v}]")
