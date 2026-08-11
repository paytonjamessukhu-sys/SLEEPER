import math, random
random.seed(7)

# ---------- law fitting (continuous exponents) ----------
def fit_power(xs, ys):
    """log y = b + e log x  (least squares).  Returns (e, K, cv_resid)."""
    lx=[math.log(x) for x in xs]; ly=[math.log(y) for y in ys]
    n=len(xs); mx=sum(lx)/n; my=sum(ly)/n
    sxx=sum((a-mx)**2 for a in lx) or 1e-18
    e=sum((a-mx)*(b-my) for a,b in zip(lx,ly))/sxx
    b=my-e*mx; K=math.exp(b)
    resid=[y/(K*x**e) for x,y in zip(xs,ys)]
    m=sum(resid)/n
    cv=math.sqrt(sum((r-m)**2 for r in resid)/n)/abs(m)
    return e,K,cv

def fit_offset_power(xs, ys):
    """y = c + K x^e via grid on c, LS on rest. Returns (c,e,K,cv)."""
    best=None
    lo,hi=0.0,0.95*min(ys)
    for i in range(120):
        c=lo+(hi-lo)*i/119
        try:
            e,K,cv=fit_power(xs,[y-c for y in ys])
        except ValueError:
            continue
        if best is None or cv<best[3]:
            best=(c,e,K,cv)
    return best

def score_law(xs, ys, tier):
    if tier==1:
        e,K,cv=fit_power(xs,ys); params=("power",e,K,None)
    else:
        c,e,K,cv=fit_offset_power(xs,ys); params=("offset-power",e,K,c)
    # fold stability: split by x, refit each half, exponent drift
    order=sorted(range(len(xs)),key=lambda i:xs[i]); h=len(xs)//2
    try:
        e1,_,_=fit_power([xs[i] for i in order[:h]],[ys[i]-(params[3] or 0) for i in order[:h]])
        e2,_,_=fit_power([xs[i] for i in order[h:]],[ys[i]-(params[3] or 0) for i in order[h:]])
        drift=abs(e1-e2)/(abs(e)+1e-9)
    except ValueError:
        drift=10.0
    return cv+0.5*drift, params, cv

def run_search(xs, ys):
    """Both tiers; lower score wins. (Search space is the tier choice --
    small, but search-null re-runs it identically on permuted data.)"""
    best=None
    for tier in (1,2):
        s,params,cv=score_law(xs,ys,tier)
        if best is None or s<best[0]: best=(s,params,cv)
    return best

# ---------- courts ----------
def courts(xs, ys, n_winner=5, n_search=6):
    score,params,cv=run_search(xs,ys)
    votes=0; 
    for _ in range(n_winner):
        yp=ys[:]; random.shuffle(yp)
        s2,_,_=run_search(xs,yp)
        if score<s2: votes+=1
    nulls=[]
    for _ in range(n_search):
        yp=ys[:]; random.shuffle(yp)
        s2,_,_=run_search(xs,yp)
        nulls.append(s2)
    # robust court: EVERY null world must lose by >5x (no averages to hide in)
    minratio=min(nulls)/score if score>0 else float("inf")
    meanratio=(sum(nulls)/len(nulls))/score if score>0 else float("inf")
    if meanratio>1e6 or cv<1e-9:
        verdict="TOO_PERFECT (synthetic-data alarm)"
    elif votes>=4 and minratio>5:
        verdict="DISCOVERY"
    else:
        verdict="NO_DISCOVERY"
    return verdict,params,cv,votes,meanratio,minratio

def report(name,xs,ys,truth=""):
    v,params,cv,votes,ratio,z=courts(xs,ys)
    kind,e,K,c=params
    law=(f"y = {K:.4g} * x^{e:.3f}" if kind=="power"
         else f"y = {c:.3f} + {K:.4g} * x^{e:.3f}")
    print(f"{name}: {v}")
    print(f"   law: {law}   CV={cv:.3%}   courts: {votes}/5, mean-null {ratio:.1f}x, WORST-null {z:.1f}x")
    if truth: print(f"   truth: {truth}")
    return v,params,cv
