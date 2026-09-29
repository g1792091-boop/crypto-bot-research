"""Verifier part 3: independent drift injection on 5m paths (drift measured in elapsed TIME, not bar count),
break-even IR at 20x and 50x; plus entry-hour check of the zero-edge baseline."""
import numpy as np, pandas as pd, sys
sys.path.insert(0, ".")
from v2_sim import load, COINS, MMR, C, FR, cluster_boot
OUT = "/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sizing/v_math/out"
data = {}
lr = []
for s in COINS:
    df = load(s, "5m")
    data[s] = (df.open.values.astype(float), df.high.values.astype(float), df.low.values.astype(float),
               df.ts.values.astype("datetime64[s]").astype(np.int64))
    lr.append(np.diff(np.log(df.close.values)))
sd5 = float(np.std(np.concatenate(lr)))
print("pooled sd of 5m log returns:", sd5)
YEAR_S = 365*86400

def trade(o,h,l,t,e,d,L,mu_s):
    """mu_s: drift per second (log). Scale of bar j = exp(d*mu_s*(t[j]-t[e])). No drift inside entry bar."""
    P = o[e]; dl = 1/L - MMR; tp = 0.10/L
    up, dn = (P*(1+tp), P*(1-dl)) if d == 1 else (P*(1+dl), P*(1-tp))
    w = 32; a = e; end = min(len(h), e + 25920)
    while a < end:
        b = min(a + w, end)
        sc = np.exp(d*mu_s*(t[a:b]-t[e]))
        hh, ll = h[a:b]*sc, l[a:b]*sc
        hit = np.nonzero((hh >= up) | (ll <= dn))[0]
        if len(hit):
            j = a + hit[0]; i = hit[0]
            oo = o[j]*sc[i]
            tp_t = (hh[i] >= up) if d == 1 else (ll[i] <= dn)
            st_t = (ll[i] <= dn) if d == 1 else (hh[i] >= up)
            gap_st = j > e and ((oo <= dn) if d == 1 else (oo >= up))
            gap_tp = j > e and ((oo >= up) if d == 1 else (oo <= dn))
            win = (not gap_st) and (gap_tp or (tp_t and not st_t))
            nf = (t[j] + 150)//28800 - t[e]//28800
            if win:
                return 1, 0.10 - L*C - L*C*((1+tp) if d == 1 else (1-tp)) - L*FR*nf, (t[j]+150-t[e])/3600
            return 0, -1.0 - L*C - L*FR*nf, (t[j]+150-t[e])/3600
        a = b; w *= 4
    return None

rs = np.random.default_rng(4242)
ent = {}
for s in COINS:
    o,h,l,t = data[s]
    ent[s] = np.sort(rs.choice(len(o) - 25920, 2000, replace=False))

def run(L, ir):
    mu_s = ir*sd5/np.sqrt(YEAR_S/300)/300.0   # per-5m-bar mean = IR*sd5/sqrt(bars/yr); per second = /300
    rec = []
    for s in COINS:
        o,h,l,t = data[s]
        for e in ent[s]:
            for d in (1,-1):
                r = trade(o,h,l,t,int(e),d,L,mu_s)
                if r: rec.append((COINS.index(s)*100000 + t[e]//604800,) + r)
    R = np.array(rec)
    return R[:,1].mean(), 100*R[:,2].mean(), 100*cluster_boot(R[:,2], R[:,0], B=200), R[:,3].mean(), len(R)

rows = []
for L, grid in ((20, [0, 2, 3, 3.5, 4, 5]), (50, [0, 30, 50, 60, 70, 90])):
    for ir in grid:
        p, er, se, mh, n = run(L, ir)
        rows.append(dict(L=L, ir=ir, pTP=p, EROE=er, se=se, mean_h=mh, n=n))
        print(rows[-1], flush=True)
R = pd.DataFrame(rows); R.to_csv(f"{OUT}/v3_drift.csv", index=False)
for L, g in R.groupby("L"):
    x, y, p = g.ir.values, g.EROE.values, g.pTP.values
    k = np.where((y[:-1] < 0) & (y[1:] >= 0))[0]
    if len(k):
        k = k[0]; ir0 = x[k] + (0-y[k])*(x[k+1]-x[k])/(y[k+1]-y[k])
        print(f"L={L}: break-even injected IR ~ {ir0:.2f}, pTP there ~ {np.interp(ir0, x, p):.4f}")
